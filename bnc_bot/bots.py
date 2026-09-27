"""Los bots del flujo. Se coordinan por la base de datos y reportan todo en el grupo de Telegram.

  BotBinance.lector    → Bot 2: lee órdenes, extrae datos, valida, publica en el grupo
  Hub                  → aprobaciones ✅/❌, códigos OTP y comandos desde el grupo
  BotBNC               → Bots 1, 3, 4 y 5: sesión, beneficiario, pago y comprobante
  BotBinance.subidor   → Bot 5 (lado Binance): sube la foto al chat y marca pagada

Dos grupos de Telegram:
  • principal: el flujo normal (órdenes nuevas, aprobaciones, OTP, comprobantes);
  • fallos:    TODO error, rechazo o revisión manual va ÚNICAMENTE aquí.
"""
from __future__ import annotations

import asyncio
import html
from decimal import Decimal
from pathlib import Path

from .binance_client import ESTADO_SIN_PAGAR, BinanceC2C
from .config import Config
from .db import DB, Estado, Orden, TransicionInvalida
from .extraccion import DatosPago, extraer
from .telegram import Telegram
from .validacion import Decision, evaluar
from .venezuela import DatoInvalido, formato_bs, parse_monto


def datos_de(o: Orden) -> DatosPago:
    return DatosPago(order_no=o.order_no, monto=o.monto, nombre_kyc=o.nombre_kyc, titular=o.titular,
                     cedula=o.cedula, cuenta=o.cuenta, banco=o.banco, pay_id=o.pay_id)


def ficha(d: DatosPago) -> str:
    e = html.escape
    return (f"<b>Orden</b> <code>{e(d.order_no)}</code>\n"
            f"👤 {e(d.titular)} ({e(d.cedula)})\n"
            f"🪪 KYC Binance: {e(d.nombre_kyc or '—')}\n"
            f"🏦 {e(d.banco)} <code>{e(d.cuenta)}</code>\n"
            f"💵 <b>{formato_bs(d.monto)} Bs</b>")


# ─────────────────────────── Hub (panel de control) ───────────────────────────
class Hub:
    def __init__(self, cfg: Config, db: DB, tg: Telegram, tg_fallos: Telegram):
        self.cfg, self.db, self.tg, self.tg_fallos = cfg, db, tg, tg_fallos
        self._otp: asyncio.Future[str] | None = None
        self._otp_lock = asyncio.Lock()

    async def pedir_otp(self, pregunta: str, timeout: int = 180) -> str:
        async with self._otp_lock:
            self._otp = asyncio.get_running_loop().create_future()
            await self.tg.enviar(pregunta)
            try:
                return await asyncio.wait_for(self._otp, timeout)
            finally:
                self._otp = None

    async def on_callback(self, data: str) -> str:
        accion, _, order_no = data.partition(":")
        try:
            if accion == "ok":
                self.db.transicion(order_no, Estado.POR_APROBAR, Estado.APROBADA, "aprobada por admin")
                await self.tg.enviar(f"✅ Orden <code>{order_no}</code> aprobada → BNC")
                return "Aprobada"
            if accion == "no":
                self.db.transicion(order_no, Estado.POR_APROBAR, Estado.RECHAZADA, "rechazada por admin")
                await self.tg.enviar(f"❌ Orden <code>{order_no}</code> rechazada")
                return "Rechazada"
        except TransicionInvalida as e:
            return str(e)[:190]
        return "Acción desconocida"

    async def on_texto(self, texto: str, chat_id: str = "") -> None:
        # Las respuestas a comandos salen en el mismo grupo donde escribiste
        es_fallos = bool(chat_id) and chat_id == str(self.tg_fallos.chat_id) != str(self.tg.chat_id)
        responder = self.tg_fallos.enviar if es_fallos else self.tg.enviar
        if not texto.startswith("/"):
            if self._otp and not self._otp.done():
                self._otp.set_result(texto)
            return
        cmd, *args = texto.split()
        cmd = cmd.split("@")[0].lower()
        try:
            if cmd == "/estado":
                lineas = []
                for est in Estado:
                    if n := len(self.db.por_estado(est)):
                        lineas.append(f"{est.value}: {n}")
                lineas.append(f"Pagado hoy: {formato_bs(self.db.total_pagado_hoy())} Bs")
                lineas.append("Modo: " + ("🧪 SIMULACIÓN" if self.cfg.simulacion else "🔴 REAL"))
                await responder("\n".join(lineas))
            elif cmd == "/reintentar" and args:
                if self.db.llego_a_pagar(args[0]):
                    await responder("⛔ Esa orden llegó a confirmarse en BNC: no se reintenta. "
                                         "Verifica en el banco y usa /pagada o /rechazar.")
                    return
                self.db.transicion(args[0], Estado.REVISION_MANUAL, Estado.APROBADA, "reintento manual")
                await responder(f"🔁 Orden <code>{args[0]}</code> vuelve a la cola de BNC")
            elif cmd == "/pagada" and args:
                o = self.db.obtener(args[0])
                if not o or not o.comprobante or not Path(o.comprobante).exists():
                    await responder("Esa orden no tiene comprobante guardado; márcala a mano en Binance.")
                    return
                self.db.transicion(args[0], Estado.REVISION_MANUAL, Estado.PAGADA, "verificada por admin")
                await responder(f"👍 Orden <code>{args[0]}</code> marcada PAGADA → se sube a Binance")
            elif cmd == "/rechazar" and args:
                self.db.transicion(args[0], Estado.REVISION_MANUAL, Estado.RECHAZADA, "rechazada por admin")
                await responder(f"❌ Orden <code>{args[0]}</code> rechazada")
            else:
                await responder("Comandos: /estado · /reintentar &lt;orden&gt; · "
                                     "/pagada &lt;orden&gt; · /rechazar &lt;orden&gt;")
        except TransicionInvalida as e:
            await responder(f"⚠️ {html.escape(str(e))}")

    async def correr(self) -> None:
        await self.tg.escuchar(self.cfg.tg_admin_id, self.on_callback, self.on_texto,
                               chats_extra=(self.tg_fallos.chat_id,))


# ─────────────────────────── Bot Binance ───────────────────────────
class BotBinance:
    def __init__(self, cfg: Config, db: DB, api: BinanceC2C, tg: Telegram, tg_fallos: Telegram):
        self.cfg, self.db, self.api, self.tg, self.tg_fallos = cfg, db, api, tg, tg_fallos
        self._fallos: dict[str, int] = {}

    async def procesar_nueva(self, order_no: str) -> None:
        """Lee el detalle, extrae los datos, valida y deja la orden aprobada o por aprobar."""
        try:
            datos = extraer(await self.api.detalle(order_no))
        except Exception as e:
            self.db.transicion(order_no, Estado.NUEVA, Estado.REVISION_MANUAL, f"extracción: {e}")
            await self.tg_fallos.enviar(f"⚠️ Orden <code>{order_no}</code>: no pude leer los datos de pago\n"
                                 f"{html.escape(str(e))}")
            return
        self.db.actualizar_campos(order_no, monto=str(datos.monto), nombre_kyc=datos.nombre_kyc, titular=datos.titular,
                                  cedula=datos.cedula, cuenta=datos.cuenta, banco=datos.banco,
                                  pay_id=datos.pay_id)
        r = evaluar(datos, pagado_hoy=self.db.total_pagado_hoy(),
                    monto_max_orden=self.cfg.monto_max_orden, monto_max_dia=self.cfg.monto_max_dia,
                    umbral_aprobacion=self.cfg.umbral_aprobacion,
                    similitud_min=self.cfg.similitud_nombre_min)
        motivos = "\n".join(f"• {html.escape(m)}" for m in r.motivos)
        if r.decision is Decision.RECHAZAR:
            self.db.transicion(order_no, Estado.NUEVA, Estado.RECHAZADA, "; ".join(r.motivos))
            await self.tg_fallos.enviar(f"🚫 NO se paga\n{ficha(datos)}\n{motivos}")
        elif r.decision is Decision.MANUAL:
            self.db.transicion(order_no, Estado.NUEVA, Estado.POR_APROBAR, "; ".join(r.motivos))
            await self.tg.enviar(f"📥 Nueva orden — requiere aprobación\n{ficha(datos)}\n{motivos}",
                                 botones=[("✅ Pagar", f"ok:{order_no}"), ("❌ Rechazar", f"no:{order_no}")])
        else:
            self.db.transicion(order_no, Estado.NUEVA, Estado.APROBADA, "aprobación automática")
            await self.tg.enviar(f"📥 Nueva orden → BNC\n{ficha(datos)}")

    async def lector(self) -> None:
        while True:
            try:
                for o in await self.api.ordenes_compra_pendientes(self.cfg.binance_fiat):
                    order_no = str(o.get("orderNumber") or o.get("adOrderNo"))
                    if self.db.insertar_orden(order_no, _monto_aprox(o), o):
                        await self.procesar_nueva(order_no)
            except Exception as e:
                await self.tg_fallos.enviar(f"⚠️ Lector Binance: {html.escape(str(e))[:500]}")
            await asyncio.sleep(self.cfg.poll_segundos)

    async def sigue_sin_pagar(self, order_no: str) -> bool:
        d = await self.api.detalle(order_no)
        return str(d.get("orderStatus", "")).upper() in {ESTADO_SIN_PAGAR, "1"}

    async def subidor(self) -> None:
        while True:
            for o in self.db.por_estado(Estado.PAGADA) + self.db.por_estado(Estado.COMPROBANTE_SUBIDO):
                try:
                    if o.estado is Estado.PAGADA:
                        await self.api.subir_imagen_chat(o.order_no, Path(o.comprobante))
                        self.db.transicion(o.order_no, Estado.PAGADA, Estado.COMPROBANTE_SUBIDO)
                    await self.api.marcar_pagada(o.order_no, o.pay_id)
                    self.db.transicion(o.order_no, Estado.COMPROBANTE_SUBIDO, Estado.COMPLETADA)
                    self._fallos.pop(o.order_no, None)
                    await self.tg.enviar(f"🏁 Orden <code>{o.order_no}</code>: comprobante en el chat y "
                                         f"marcada como PAGADA en Binance")
                except Exception as e:
                    n = self._fallos[o.order_no] = self._fallos.get(o.order_no, 0) + 1
                    if n >= 5:
                        actual = self.db.obtener(o.order_no)
                        self.db.transicion(o.order_no, actual.estado, Estado.REVISION_MANUAL, str(e))
                        await self.tg_fallos.enviar(f"🆘 Orden <code>{o.order_no}</code>: el pago SALIÓ del banco pero "
                                             f"no pude subirlo/marcarlo en Binance. Hazlo a mano.\n"
                                             f"{html.escape(str(e))[:300]}")
            await asyncio.sleep(self.cfg.poll_segundos)


def _monto_aprox(o: dict) -> Decimal:
    """Monto del listado (el definitivo se toma del detalle en procesar_nueva)."""
    try:
        return parse_monto(str(o.get("totalPrice") or ""))
    except DatoInvalido:
        return Decimal("0")


# ─────────────────────────── Bot BNC ───────────────────────────
class BotBNC:
    def __init__(self, cfg: Config, db: DB, sesion, hub: Hub, tg_bnc: Telegram,
                 tg_comprobante: Telegram, tg_fallos: Telegram, binance: BotBinance):
        self.cfg, self.db, self.sesion, self.hub = cfg, db, sesion, hub
        self.tg, self.tg_comp, self.tg_fallos, self.binance = tg_bnc, tg_comprobante, tg_fallos, binance

    async def _revision(self, o: Orden, desde: Estado, motivo: str, urgente: bool = False) -> None:
        self.db.transicion(o.order_no, desde, Estado.REVISION_MANUAL, motivo)
        icono = "🆘 VERIFICA EN EL BANCO si el pago salió" if urgente else "⚠️ Revisión manual"
        await self.tg_fallos.enviar(f"{icono} — orden <code>{o.order_no}</code>\n{html.escape(motivo)[:500]}\n"
                             f"Usa /reintentar, /pagada o /rechazar")

    async def pagar(self, o: Orden) -> None:
        from .bnc.beneficiario import asegurar_beneficiario
        from .bnc.pago import (ErrorTrasConfirmar, ResumenNoCoincide, confirmar_y_capturar,
                               llenar_transferencia, verificar_resumen)

        datos = datos_de(o)
        estado = Estado.APROBADA
        try:
            if not await self.binance.sigue_sin_pagar(o.order_no):
                await self._revision(o, estado, "La orden ya no está pendiente en Binance (¿cancelada/expirada?)")
                return
            if self.db.total_pagado_hoy() + o.monto > self.cfg.monto_max_dia:
                await self._revision(o, estado, "Se superaría el máximo diario")
                return

            async with self.sesion.lock:
                page = await self.sesion.asegurar()                          # Bot 1
                if not self.db.beneficiario(o.cuenta):                        # Bot 3
                    nuevo = await asegurar_beneficiario(page, datos, self.hub.pedir_otp)
                    self.db.guardar_beneficiario(o.cuenta, o.titular, o.cedula)
                    if nuevo:
                        await self.tg.enviar(f"📝 Beneficiario registrado: {html.escape(o.titular)} …{o.cuenta[-4:]}")
                self.db.transicion(o.order_no, estado, Estado.BENEFICIARIO_OK)
                estado = Estado.BENEFICIARIO_OK

                await llenar_transferencia(page, datos, self.cfg.bnc_cuenta_origen)  # Bot 4
                await verificar_resumen(page, datos)

                if self.cfg.simulacion:
                    # No es un fallo: se informa en el grupo principal
                    self.db.transicion(o.order_no, estado, Estado.REVISION_MANUAL, "simulación")
                    await self.tg.enviar(f"🧪 SIMULACIÓN — orden <code>{o.order_no}</code>: formulario lleno y "
                                         f"resumen verificado, NO se confirmó")
                    return

                # A partir de aquí el dinero puede salir: marcar ANTES de pulsar confirmar.
                self.db.transicion(o.order_no, estado, Estado.PAGANDO)
                estado = Estado.PAGANDO
                res = await confirmar_y_capturar(page, datos, self.hub.pedir_otp)  # Bot 4 + 5

            self.db.actualizar_campos(o.order_no, comprobante=str(res.comprobante), referencia=res.referencia)
            self.db.transicion(o.order_no, Estado.PAGANDO, Estado.PAGADA, f"ref {res.referencia}")
            estado = Estado.PAGADA
        except ResumenNoCoincide as e:
            await self._revision(o, estado, f"Resumen BNC no coincide, NO se confirmó: {e}")
        except ErrorTrasConfirmar as e:
            await self._revision(o, Estado.PAGANDO, f"Error DESPUÉS de confirmar: {e}", urgente=True)
        except Exception as e:
            await self._revision(o, estado, f"{type(e).__name__}: {e}", urgente=estado is Estado.PAGANDO)
        if estado is Estado.PAGADA:
            try:
                await self.tg_comp.enviar_foto(
                    res.comprobante,
                    f"✅ Pagado {formato_bs(o.monto)} Bs a {html.escape(o.titular)}\n"
                    f"Orden <code>{o.order_no}</code> · Ref {res.referencia or '—'}",
                )
            except Exception as e:  # el pago ya está hecho; solo falló el aviso
                await self.tg_fallos.enviar(f"⚠️ Orden <code>{o.order_no}</code> pagada, pero no pude publicar "
                                            f"el comprobante en el grupo: {html.escape(str(e))[:300]}")

    async def correr(self) -> None:
        while True:
            for o in self.db.por_estado(Estado.APROBADA):
                await self.pagar(o)
            await asyncio.sleep(self.cfg.poll_segundos)
