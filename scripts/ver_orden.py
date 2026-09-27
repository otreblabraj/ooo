"""Fase 1: muestra el JSON crudo que devuelve Binance para validar rutas y nombres de campos.

    python scripts/ver_orden.py            # lista órdenes pendientes
    python scripts/ver_orden.py <orden>    # detalle de una orden + datos extraídos
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bnc_bot.binance_client import BinanceC2C  # noqa: E402
from bnc_bot.config import cargar  # noqa: E402
from bnc_bot.extraccion import extraer  # noqa: E402


async def main() -> None:
    cfg = cargar()
    api = BinanceC2C(cfg.binance_api_key, cfg.binance_api_secret, cfg.binance_base_url)
    try:
        if len(sys.argv) > 1:
            det = await api.detalle(sys.argv[1])
            print(json.dumps(det, indent=2, ensure_ascii=False))
            print("\n→ Datos extraídos:", extraer(det))
        else:
            print(json.dumps(await api.ordenes_compra_pendientes(cfg.binance_fiat), indent=2, ensure_ascii=False))
    finally:
        await api.cerrar()


asyncio.run(main())
