"""Lector de códigos de BNC que llegan por correo electrónico (IMAP).

Cuando BNC pide un código (inicio de sesión, registro de beneficiario o pago), el bot
revisa la bandeja cada pocos segundos, toma el correo de BNC que llegó DESPUÉS de la
solicitud, extrae el código y lo devuelve para escribirlo en el banco.

Gmail: activa la verificación en 2 pasos y crea una "contraseña de aplicación"
(Cuenta de Google → Seguridad → Contraseñas de aplicaciones). Úsala en CORREO_CLAVE.
"""
from __future__ import annotations

import asyncio
import email
import html
import imaplib
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Callable

# Palabra clave cerca del código: "Su código de seguridad es: 123456"
_CERCA_DE_CLAVE = re.compile(
    r"(?:c[oó]digo|clave|token|otp|pin)[^0-9]{0,60}?(?<!\d)(\d{4,8})(?!\d)", re.IGNORECASE)
_SEIS_DIGITOS = re.compile(r"(?<![\d.,/-])(\d{6})(?![\d.,/-])")


def extraer_codigo(texto: str, patron: str = "") -> str | None:
    """Saca el código del cuerpo del correo.

    Con `patron` (CORREO_PATRON) se usa esa expresión; su primer grupo es el código.
    Sin patrón: primero busca un número de 4 a 8 dígitos cerca de "código/clave/token";
    si no hay, el primer número suelto de exactamente 6 dígitos.
    """
    if patron:
        m = re.search(patron, texto, re.IGNORECASE | re.DOTALL)
        return (m.group(1) if m and m.groups() else m.group(0) if m else None)
    m = _CERCA_DE_CLAVE.search(texto) or _SEIS_DIGITOS.search(texto)
    return m.group(1) if m else None


def texto_del_correo(msg: Message) -> str:
    """Asunto + cuerpo en texto plano (convierte el HTML si no hay versión de texto)."""
    planos, htmls = [], []
    for parte in msg.walk() if msg.is_multipart() else [msg]:
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html"):
            continue
        carga = parte.get_payload(decode=True) or b""
        contenido = carga.decode(parte.get_content_charset() or "utf-8", errors="replace")
        (planos if tipo == "text/plain" else htmls).append(contenido)
    cuerpo = "\n".join(planos)
    if not cuerpo and htmls:
        sin_estilos = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(htmls))
        cuerpo = html.unescape(re.sub(r"<[^>]+>", " ", sin_estilos))
    asunto = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
    cuerpo = re.sub(r"[ \t]+", " ", cuerpo)
    return f"{asunto}\n{cuerpo}"


class LectorCorreo:
    def __init__(self, host: str, usuario: str, clave: str, remitente: str, patron: str = "",
                 carpeta: str = "INBOX", cada_segundos: float = 2.0,
                 conectar: Callable[[str], imaplib.IMAP4] | None = None):
        self.host, self.usuario, self._clave = host, usuario, clave
        self.remitente, self.patron, self.carpeta = remitente, patron, carpeta
        self.cada_segundos = cada_segundos
        self._conectar = conectar or (lambda h: imaplib.IMAP4_SSL(h))
        self._usados: set[bytes] = set()

    @property
    def activo(self) -> bool:
        return bool(self.host and self.usuario and self._clave and self.remitente)

    def _buscar_una_vez(self, imap: imaplib.IMAP4, desde: datetime) -> str | None:
        imap.noop()  # obliga al servidor a mostrar correos nuevos
        fecha = (desde - timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = imap.uid("SEARCH", None, f'(FROM "{self.remitente}" SINCE {fecha})')
        if typ != "OK" or not data or not data[0]:
            return None
        for uid in reversed(data[0].split()):  # del más reciente al más viejo
            if uid in self._usados:
                continue
            typ, partes = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            crudo = next((p[1] for p in partes if isinstance(p, tuple)), None)
            if typ != "OK" or crudo is None:
                continue
            msg = email.message_from_bytes(crudo)
            try:
                llegado = parsedate_to_datetime(msg["Date"])
            except (TypeError, ValueError):
                continue
            if llegado.tzinfo is None:
                llegado = llegado.replace(tzinfo=timezone.utc)
            if llegado < desde:
                return None  # los demás son más viejos: códigos vencidos
            codigo = extraer_codigo(texto_del_correo(msg), self.patron)
            if codigo:
                self._usados.add(uid)
                imap.uid("STORE", uid, "+FLAGS", r"(\Seen)")
                return codigo
        return None

    def _esperar_bloqueante(self, desde: datetime, timeout: float, cancelado) -> str | None:
        imap = self._conectar(self.host)
        try:
            imap.login(self.usuario, self._clave)
            imap.select(self.carpeta)
            limite = datetime.now(timezone.utc) + timedelta(seconds=timeout)
            while datetime.now(timezone.utc) < limite and not cancelado():
                if codigo := self._buscar_una_vez(imap, desde):
                    return codigo
                cancelado_o_espera(self.cada_segundos, cancelado)
            return None
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    async def esperar_codigo(self, desde: datetime, timeout: float = 180) -> str | None:
        """Espera el correo de BNC que llegue después de `desde` y devuelve el código.

        Se toma un margen de 60 s antes de `desde` por diferencias de reloj con el servidor.
        """
        margen = desde.astimezone(timezone.utc) - timedelta(seconds=60)
        cancelar = {"si": False}
        try:
            return await asyncio.to_thread(
                self._esperar_bloqueante, margen, timeout, lambda: cancelar["si"])
        finally:
            cancelar["si"] = True


def cancelado_o_espera(segundos: float, cancelado) -> None:
    """Duerme en pasos cortos para poder salir rápido si se canceló la espera."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin and not cancelado():
        time.sleep(0.1)
