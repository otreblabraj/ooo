from decimal import Decimal

import pytest

from bnc_bot.config import Config


def detalle_orden(**extra):
    base = {
        "orderNumber": "22900000000000001",
        "orderStatus": "TRADING",
        "totalPrice": "1250.50",
        "sellerName": "JUAN CARLOS PEREZ GOMEZ",
        "payMethods": [
            {"id": 111, "identifier": "PagoMovil", "fields": [
                {"fieldName": "Phone", "fieldValue": "04141234567"},
            ]},
            {"id": 222, "identifier": "BANK", "fields": [
                {"fieldName": "Name", "fieldValue": "Juan Perez"},
                {"fieldName": "Bank name", "fieldValue": "Banesco"},
                {"fieldName": "Account number", "fieldValue": "0134-0000-11-2222333344"},
                {"fieldName": "ID number (Cédula)", "fieldValue": "V-12.345.678"},
            ]},
        ],
    }
    base.update(extra)
    return base


@pytest.fixture
def cfg():
    return Config(
        binance_api_key="k", binance_api_secret="s", binance_base_url="http://x", binance_fiat="VES",
        tg_token_hub="", tg_token_binance="", tg_token_bnc="", tg_token_comprobante="",
        tg_chat_id="-100", tg_admin_id=1, tg_token_fallos="", tg_chat_fallos="-200", bnc_url="", bnc_usuario="", bnc_clave="", bnc_preguntas={},
        bnc_cuenta_origen="01910000000000000001", simulacion=False,
        monto_max_orden=Decimal("50000"), monto_max_dia=Decimal("100000"),
        umbral_aprobacion=Decimal("5000"), similitud_nombre_min=0.6, db_path=":memory:",
        poll_segundos=1,
    )
