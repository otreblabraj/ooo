"""Configuración leída desde variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

from dotenv import load_dotenv


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "si", "sí", "yes"}


def _preguntas(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for par in filter(None, (p.strip() for p in raw.split(";"))):
        if "=" in par:
            k, v = par.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


@dataclass(frozen=True)
class Config:
    binance_api_key: str
    binance_api_secret: str
    binance_base_url: str
    binance_fiat: str

    tg_token_hub: str
    tg_token_binance: str
    tg_token_bnc: str
    tg_token_comprobante: str
    tg_chat_id: str
    tg_admin_id: int

    bnc_url: str
    bnc_usuario: str
    bnc_clave: str
    bnc_preguntas: dict[str, str] = field(repr=False)
    bnc_cuenta_origen: str = ""
    bnc_headful: bool = True

    simulacion: bool = True
    monto_max_orden: Decimal = Decimal("0")
    monto_max_dia: Decimal = Decimal("0")
    umbral_aprobacion: Decimal = Decimal("0")
    similitud_nombre_min: float = 0.6

    db_path: str = "data/bnc_bot.sqlite3"
    poll_segundos: int = 10

    def __repr__(self) -> str:  # nunca imprimir secretos
        return f"Config(simulacion={self.simulacion}, fiat={self.binance_fiat})"


def cargar() -> Config:
    load_dotenv()
    hub = os.getenv("TELEGRAM_TOKEN_HUB", "")
    return Config(
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        binance_fiat=os.getenv("BINANCE_FIAT", "VES"),
        tg_token_hub=hub,
        tg_token_binance=os.getenv("TELEGRAM_TOKEN_BINANCE") or hub,
        tg_token_bnc=os.getenv("TELEGRAM_TOKEN_BNC") or hub,
        tg_token_comprobante=os.getenv("TELEGRAM_TOKEN_COMPROBANTE") or hub,
        tg_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        tg_admin_id=int(os.getenv("TELEGRAM_ADMIN_ID", "0") or 0),
        bnc_url=os.getenv("BNC_URL", ""),
        bnc_usuario=os.getenv("BNC_USUARIO", ""),
        bnc_clave=os.getenv("BNC_CLAVE", ""),
        bnc_preguntas=_preguntas(os.getenv("BNC_PREGUNTAS", "")),
        bnc_cuenta_origen=os.getenv("BNC_CUENTA_ORIGEN", ""),
        bnc_headful=_bool("BNC_HEADFUL", True),
        simulacion=_bool("SIMULACION", True),
        monto_max_orden=Decimal(os.getenv("MONTO_MAX_ORDEN", "50000")),
        monto_max_dia=Decimal(os.getenv("MONTO_MAX_DIA", "500000")),
        umbral_aprobacion=Decimal(os.getenv("UMBRAL_APROBACION", "0")),
        similitud_nombre_min=float(os.getenv("SIMILITUD_NOMBRE_MIN", "0.6")),
        db_path=os.getenv("DB_PATH", "data/bnc_bot.sqlite3"),
        poll_segundos=int(os.getenv("POLL_SEGUNDOS", "10")),
    )
