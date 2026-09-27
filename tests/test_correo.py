import asyncio
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from bnc_bot import bots
from bnc_bot.correo import LectorCorreo, extraer_codigo, texto_del_correo
from bnc_bot.db import DB


@pytest.mark.parametrize("texto,esperado", [
    ("Su código de seguridad es: 482913. Vence en 5 minutos.", "482913"),
    ("BNC: Clave de operaciones especiales 7391", "7391"),
    ("Token: 12345678", "12345678"),
    # No debe confundir montos, fechas ni cuentas con el código
    ("Transferencia por 1.250,50 Bs el 27/09/2026 a la cuenta 01340000112222333344. Código 551902", "551902"),
    ("Hola, su OTP para operar es\n\n  903114  \n\nNo lo comparta.", "903114"),
    ("Sin código aquí, solo 12 y 2026", None),
])
def test_extraer_codigo(texto, esperado):
    assert extraer_codigo(texto) == esperado


def test_patron_personalizado():
    assert extraer_codigo("Ref 111111 · PIN BNC => 654321", r"PIN BNC => (\d{6})") == "654321"


def correo(asunto, cuerpo, cuando, html=False):
    m = EmailMessage()
    m["From"] = "BNC en Línea <notificaciones@bnc.com.ve>"
    m["Subject"] = asunto
    m["Date"] = format_datetime(cuando)
    if html:
        m.set_content("")
        m.clear_content()
        m.set_content(cuerpo, subtype="html")
    else:
        m.set_content(cuerpo)
    return m


def test_texto_de_correo_html():
    m = correo("Código BNC", "<html><style>p{color:red}</style><p>Su código es <b>246810</b></p></html>",
               datetime.now(timezone.utc), html=True)
    assert extraer_codigo(texto_del_correo(m)) == "246810"


class FakeIMAP:
    """Buzón IMAP en memoria. `llegadas` = [(segundos_despues_de_conectar, EmailMessage)]."""

    def __init__(self, existentes, llegadas=()):
        self.buzon = [(str(i + 1).encode(), m) for i, m in enumerate(existentes)]
        self.llegadas = list(llegadas)
        self.inicio = None
        self.vistos = set()

    def login(self, u, p): self.inicio = time.monotonic()
    def select(self, c): return ("OK", [b"1"])
    def logout(self): pass

    def noop(self):
        ahora = time.monotonic() - self.inicio
        while self.llegadas and self.llegadas[0][0] <= ahora:
            _, m = self.llegadas.pop(0)
            self.buzon.append((str(len(self.buzon) + 1).encode(), m))

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [b" ".join(u for u, _ in self.buzon)]
        if cmd == "FETCH":
            m = dict(self.buzon)[args[0]]
            return "OK", [(b"1 (BODY[] {n}", m.as_bytes()), b")"]
        if cmd == "STORE":
            self.vistos.add(args[0])
            return "OK", []


async def test_lector_ignora_codigos_viejos_y_toma_el_nuevo():
    ahora = datetime.now(timezone.utc)
    viejo = correo("Código", "Su código es 111111", ahora - timedelta(minutes=10))
    nuevo = correo("Código", "Su código es 222222", ahora)
    imap = FakeIMAP([viejo], llegadas=[(0.3, nuevo)])
    lector = LectorCorreo("imap", "yo", "clave", "bnc.com.ve", cada_segundos=0.1, conectar=lambda h: imap)
    assert await lector.esperar_codigo(ahora, timeout=5) == "222222"
    assert imap.vistos == {b"2"}
    # El mismo correo no se vuelve a usar para el siguiente código
    assert await lector.esperar_codigo(ahora, timeout=0.5) is None


async def test_lector_timeout_sin_correo():
    lector = LectorCorreo("imap", "yo", "clave", "bnc", cada_segundos=0.1, conectar=lambda h: FakeIMAP([]))
    assert await lector.esperar_codigo(datetime.now(timezone.utc), timeout=0.4) is None


class FakeTG:
    def __init__(self, chat_id):
        self.chat_id, self.mensajes = chat_id, []

    async def enviar(self, texto, botones=None):
        self.mensajes.append(texto)


class CorreoFalso:
    activo = True

    def __init__(self, resultado, demora=0.05):
        self.resultado, self.demora = resultado, demora

    async def esperar_codigo(self, desde, timeout):
        await asyncio.sleep(self.demora)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


def hub_con(cfg, correo_):
    tg, fallos = FakeTG("-100"), FakeTG("-200")
    return bots.Hub(cfg, DB(":memory:"), tg, fallos, correo_), tg, fallos


async def test_codigo_llega_por_correo_y_se_ingresa_solo(cfg):
    hub, tg, fallos = hub_con(cfg, CorreoFalso("482913"))
    assert await hub.pedir_otp("🔐 BNC pide código para PAGAR") == "482913"
    assert "Buscando el código en el correo" in tg.mensajes[0]
    assert "482913" not in tg.mensajes[-1] and "••••13" in tg.mensajes[-1]
    assert fallos.mensajes == []


async def test_si_el_correo_falla_avisa_en_fallos_y_acepta_manual(cfg):
    hub, tg, fallos = hub_con(cfg, CorreoFalso(OSError("login rechazado")))
    tarea = asyncio.create_task(hub.pedir_otp("🔐 código", timeout=5))
    await asyncio.sleep(0.2)
    assert "login rechazado" in fallos.mensajes[-1]
    await hub.on_texto("777888", "-100")
    assert await tarea == "777888"


async def test_manual_gana_si_llega_antes(cfg):
    hub, tg, fallos = hub_con(cfg, CorreoFalso("000000", demora=2))
    tarea = asyncio.create_task(hub.pedir_otp("🔐 código", timeout=5))
    await asyncio.sleep(0)
    await hub.on_texto("123123", "-100")
    assert await tarea == "123123"


async def test_preguntas_de_seguridad_no_usan_correo(cfg):
    hub, tg, fallos = hub_con(cfg, CorreoFalso("999999"))
    tarea = asyncio.create_task(hub.pedir_otp("BNC pregunta: color favorito", timeout=5, por_correo=False))
    await asyncio.sleep(0.2)
    assert not tarea.done()
    await hub.on_texto("azul", "-100")
    assert await tarea == "azul"


async def test_timeout_total(cfg):
    hub, tg, fallos = hub_con(cfg, CorreoFalso(None, demora=0.05))
    with pytest.raises(TimeoutError):
        await hub.pedir_otp("🔐 código", timeout=0.3)
