"""Flujo completo con Binance, Telegram y BNC simulados (sin red ni navegador)."""
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import asyncio
import pytest

from bnc_bot import bots
from bnc_bot.bnc import pago as pago_mod
from bnc_bot.bnc import beneficiario as benef_mod
from bnc_bot.db import DB, Estado
from tests.conftest import detalle_orden


class FakeTG:
    def __init__(self, chat_id="-100"):
        self.chat_id = chat_id
        self.mensajes, self.fotos = [], []

    async def enviar(self, texto, botones=None):
        self.mensajes.append((texto, botones))

    async def enviar_foto(self, foto, caption=""):
        self.fotos.append((foto, caption))


class FakeAPI:
    def __init__(self, detalle):
        self.det = detalle
        self.subidas, self.marcadas = [], []

    async def detalle(self, order_no):
        return self.det

    async def subir_imagen_chat(self, order_no, imagen):
        self.subidas.append((order_no, imagen))

    async def marcar_pagada(self, order_no, pay_id):
        self.marcadas.append((order_no, pay_id))


class FakeSesion:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def asegurar(self):
        return object()


@pytest.fixture
def entorno(cfg, monkeypatch, tmp_path):
    llamadas = []

    async def asegurar_beneficiario(page, datos, pedir_otp):
        llamadas.append("beneficiario")
        return True

    async def llenar(page, datos, origen):
        llamadas.append("llenar")

    async def verificar(page, datos):
        llamadas.append("verificar")

    async def confirmar(page, datos, pedir_otp):
        llamadas.append("confirmar")
        f = tmp_path / "c.png"
        f.write_bytes(b"png")
        return pago_mod.ResultadoPago(f, "123456", simulado=False)

    monkeypatch.setattr(benef_mod, "asegurar_beneficiario", asegurar_beneficiario)
    monkeypatch.setattr(pago_mod, "llenar_transferencia", llenar)
    monkeypatch.setattr(pago_mod, "verificar_resumen", verificar)
    monkeypatch.setattr(pago_mod, "confirmar_y_capturar", confirmar)

    def armar(config=cfg, detalle=None):
        db = DB(":memory:")
        tg, fallos = FakeTG("-100"), FakeTG("-200")
        api = FakeAPI(detalle or detalle_orden())
        hub = bots.Hub(config, db, tg, fallos)
        bb = bots.BotBinance(config, db, api, tg, fallos)
        bnc = bots.BotBNC(config, db, FakeSesion(), hub, tg, tg, fallos, bb)
        armar.fallos = fallos
        return db, tg, api, hub, bb, bnc

    armar.llamadas = llamadas
    return armar


async def test_flujo_completo_automatico(entorno):
    db, tg, api, hub, bb, bnc = entorno()
    no = "22900000000000001"
    db.insertar_orden(no, Decimal("0"), {})
    await bb.procesar_nueva(no)
    o = db.obtener(no)
    assert o.estado is Estado.APROBADA and o.monto == Decimal("1250.50")

    await bnc.pagar(o)
    assert entorno.llamadas == ["beneficiario", "llenar", "verificar", "confirmar"]
    assert db.obtener(no).estado is Estado.PAGADA
    assert len(tg.fotos) == 1

    # subidor: una vuelta del bucle real
    tarea = asyncio.create_task(bb.subidor())
    await asyncio.sleep(0.05)
    tarea.cancel()
    assert db.obtener(no).estado is Estado.COMPLETADA
    assert api.subidas and api.subidas[0][0] == no
    assert api.marcadas == [(no, "222")]


async def test_simulacion_no_confirma(entorno, cfg):
    db, tg, api, hub, bb, bnc = entorno(config=replace(cfg, simulacion=True))
    no = "22900000000000001"
    db.insertar_orden(no, Decimal("0"), {})
    await bb.procesar_nueva(no)
    await bnc.pagar(db.obtener(no))
    assert "confirmar" not in entorno.llamadas
    assert db.obtener(no).estado is Estado.REVISION_MANUAL


async def test_nombre_distinto_espera_aprobacion(entorno):
    db, tg, api, hub, bb, bnc = entorno(detalle=detalle_orden(sellerName="MARIA LOPEZ"))
    no = "22900000000000001"
    db.insertar_orden(no, Decimal("0"), {})
    await bb.procesar_nueva(no)
    assert db.obtener(no).estado is Estado.POR_APROBAR
    assert tg.mensajes[-1][1]  # trae botones
    assert await hub.on_callback(f"ok:{no}") == "Aprobada"
    assert db.obtener(no).estado is Estado.APROBADA


async def test_error_tras_confirmar_no_se_reintenta(entorno, monkeypatch):
    db, tg, api, hub, bb, bnc = entorno()

    async def confirmar_falla(page, datos, pedir_otp):
        raise pago_mod.ErrorTrasConfirmar("timeout esperando recibo")

    monkeypatch.setattr(pago_mod, "confirmar_y_capturar", confirmar_falla)
    no = "22900000000000001"
    db.insertar_orden(no, Decimal("0"), {})
    await bb.procesar_nueva(no)
    await bnc.pagar(db.obtener(no))
    assert db.obtener(no).estado is Estado.REVISION_MANUAL
    fallos = entorno.fallos
    assert "VERIFICA EN EL BANCO" in fallos.mensajes[-1][0]
    assert not any("VERIFICA" in m for m, _ in tg.mensajes)  # el fallo va SOLO al grupo de fallos

    # El comando desde el grupo de fallos se responde en el grupo de fallos
    await hub.on_texto(f"/reintentar {no}", "-200")
    assert db.obtener(no).estado is Estado.REVISION_MANUAL  # bloqueado: evita pago doble
    assert "no se reintenta" in fallos.mensajes[-1][0]


async def test_orden_cancelada_en_binance_no_se_paga(entorno):
    db, tg, api, hub, bb, bnc = entorno()
    no = "22900000000000001"
    db.insertar_orden(no, Decimal("0"), {})
    await bb.procesar_nueva(no)
    api.det = {**api.det, "orderStatus": "CANCELLED"}
    await bnc.pagar(db.obtener(no))
    assert entorno.llamadas == []
    assert db.obtener(no).estado is Estado.REVISION_MANUAL


async def test_otp_por_telegram(entorno):
    db, tg, api, hub, bb, bnc = entorno()
    tarea = asyncio.create_task(hub.pedir_otp("código?"))
    await asyncio.sleep(0)
    await hub.on_texto("123456")
    assert await tarea == "123456"


async def test_fallos_solo_en_grupo_de_fallos(entorno):
    # Orden rechazada por límite + error de extracción: nada de eso en el grupo principal
    db, tg, api, hub, bb, bnc = entorno(detalle=detalle_orden(totalPrice="999999"))
    db.insertar_orden("A", Decimal("0"), {})
    await bb.procesar_nueva("A")
    api.det = {"orderNumber": "B", "totalPrice": "10", "payMethods": []}
    db.insertar_orden("B", Decimal("0"), {})
    await bb.procesar_nueva("B")

    fallos = entorno.fallos
    assert db.obtener("A").estado is Estado.RECHAZADA
    assert db.obtener("B").estado is Estado.REVISION_MANUAL
    assert len(fallos.mensajes) == 2
    assert tg.mensajes == []


async def test_simulacion_va_al_grupo_principal(entorno, cfg):
    db, tg, api, hub, bb, bnc = entorno(config=replace(cfg, simulacion=True))
    db.insertar_orden("22900000000000001", Decimal("0"), {})
    await bb.procesar_nueva("22900000000000001")
    await bnc.pagar(db.obtener("22900000000000001"))
    assert "SIMULACIÓN" in tg.mensajes[-1][0]
    assert entorno.fallos.mensajes == []


async def test_telegram_fallos_nunca_lanza():
    import httpx
    from bnc_bot.telegram import Telegram

    def caido(request):
        raise httpx.ConnectError("sin red")

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(caido))
    assert await Telegram("t", "-200", cliente, nunca_falla=True).enviar("x") == {}
    with pytest.raises(httpx.ConnectError):
        await Telegram("t", "-100", cliente).enviar("x")
