"""Arranque: python -m bnc_bot [--solo-binance]

--solo-binance  Fase 1: solo lee órdenes de Binance y las publica en el grupo (no abre BNC).
"""
from __future__ import annotations

import argparse
import asyncio

from .binance_client import BinanceC2C
from .bots import BotBinance, BotBNC, Hub
from .config import cargar
from .correo import LectorCorreo
from .db import DB
from .telegram import Telegram


async def main(solo_binance: bool) -> None:
    cfg = cargar()
    db = DB(cfg.db_path)
    tg_hub = Telegram(cfg.tg_token_hub, cfg.tg_chat_id)
    tg_binance = Telegram(cfg.tg_token_binance, cfg.tg_chat_id)
    tg_bnc = Telegram(cfg.tg_token_bnc, cfg.tg_chat_id)
    tg_comp = Telegram(cfg.tg_token_comprobante, cfg.tg_chat_id)
    tg_fallos = Telegram(cfg.tg_token_fallos, cfg.tg_chat_fallos, nunca_falla=True)
    api = BinanceC2C(cfg.binance_api_key, cfg.binance_api_secret, cfg.binance_base_url)

    correo = LectorCorreo(cfg.correo_imap, cfg.correo_usuario, cfg.correo_clave,
                          cfg.correo_remitente, cfg.correo_patron, cfg.correo_carpeta)
    hub = Hub(cfg, db, tg_hub, tg_fallos, correo)
    binance = BotBinance(cfg, db, api, tg_binance, tg_fallos)
    tareas = [hub.correr(), binance.lector()]
    modo = "🧪 SIMULACIÓN" if cfg.simulacion else "🔴 REAL"
    if not correo.activo:
        await tg_fallos.enviar("⚠️ Lector de correo sin configurar: los códigos de BNC habrá que escribirlos a mano.")

    if not solo_binance:
        from .bnc.session import SesionBNC

        sesion = SesionBNC(cfg, hub.pedir_otp, tg_bnc.enviar, tg_fallos.enviar)
        bnc = BotBNC(cfg, db, sesion, hub, tg_bnc, tg_comp, tg_fallos, binance)
        tareas += [bnc.correr(), sesion.mantener_viva(), binance.subidor()]

    await tg_hub.enviar(f"🤖 Bots BNC arrancados — modo {modo}"
                        + (" — solo lectura Binance" if solo_binance else ""))
    try:
        await asyncio.gather(*tareas)
    except Exception as e:
        await tg_fallos.enviar(f"💥 Los bots se detuvieron por un error: {e}")
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-binance", action="store_true")
    asyncio.run(main(ap.parse_args().solo_binance))
