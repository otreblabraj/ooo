"""Arranque: python -m bnc_bot [--solo-binance]

--solo-binance  Fase 1: solo lee órdenes de Binance y las publica en el grupo (no abre BNC).

Apagado seguro: si existe el archivo data/detener (lo crea el panel), el bot espera a
terminar el pago que esté haciendo en BNC y luego se detiene.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .binance_client import BinanceC2C
from .bots import BotBinance, BotBNC, Hub
from .config import cargar
from .correo import LectorCorreo
from .db import DB
from .telegram import Telegram

ARCHIVO_DETENER = Path("data/detener")


class Apagado(Exception):
    pass


async def vigilar_apagado(lock_bnc: asyncio.Lock | None, avisar) -> None:
    while not ARCHIVO_DETENER.exists():
        await asyncio.sleep(1)
    print("Apagado solicitado: esperando a que termine el pago en curso…", flush=True)
    if lock_bnc is not None:
        await lock_bnc.acquire()  # nunca cortar un pago a la mitad
    await avisar("🛑 Bots apagados desde el panel")
    raise Apagado()


async def main(solo_binance: bool) -> None:
    cfg = cargar()
    ARCHIVO_DETENER.unlink(missing_ok=True)
    db = DB(cfg.db_path)
    tg_hub = Telegram(cfg.tg_token_hub, cfg.tg_chat_id, nombre="Hub")
    tg_binance = Telegram(cfg.tg_token_binance, cfg.tg_chat_id, nombre="Binance")
    tg_bnc = Telegram(cfg.tg_token_bnc, cfg.tg_chat_id, nombre="BNC")
    tg_comp = Telegram(cfg.tg_token_comprobante, cfg.tg_chat_id, nombre="Comprobante")
    tg_fallos = Telegram(cfg.tg_token_fallos, cfg.tg_chat_fallos, nunca_falla=True, nombre="FALLOS")
    api = BinanceC2C(cfg.binance_api_key, cfg.binance_api_secret, cfg.binance_base_url)

    correo = LectorCorreo(cfg.correo_imap, cfg.correo_usuario, cfg.correo_clave,
                          cfg.correo_remitente, cfg.correo_patron, cfg.correo_carpeta)
    hub = Hub(cfg, db, tg_hub, tg_fallos, correo)
    binance = BotBinance(cfg, db, api, tg_binance, tg_fallos)
    tareas = [hub.correr(), binance.lector()]
    modo = "🧪 SIMULACIÓN" if cfg.simulacion else "🔴 REAL"
    if not correo.activo:
        await tg_fallos.enviar("⚠️ Lector de correo sin configurar: los códigos de BNC habrá que escribirlos a mano.")

    sesion = None
    if not solo_binance:
        from .bnc.session import SesionBNC

        sesion = SesionBNC(cfg, hub.pedir_otp, tg_bnc.enviar, tg_fallos.enviar)
        bnc = BotBNC(cfg, db, sesion, hub, tg_bnc, tg_comp, tg_fallos, binance)
        tareas += [bnc.correr(), sesion.mantener_viva(), binance.subidor()]
    tareas.append(vigilar_apagado(sesion.lock if sesion else None, tg_hub.enviar))

    await tg_hub.enviar(f"🤖 Bots BNC arrancados — modo {modo}"
                        + (" — solo lectura Binance" if solo_binance else ""))
    try:
        async with asyncio.TaskGroup() as grupo:
            for t in tareas:
                grupo.create_task(t)
    except* Apagado:
        pass
    except* Exception as errores:
        for e in errores.exceptions:
            await tg_fallos.enviar(f"💥 Los bots se detuvieron por un error: {e}")
        raise
    finally:
        ARCHIVO_DETENER.unlink(missing_ok=True)
        if sesion:
            await sesion.cerrar()
        await api.cerrar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-binance", action="store_true")
    asyncio.run(main(ap.parse_args().solo_binance))
