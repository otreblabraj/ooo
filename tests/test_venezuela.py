from decimal import Decimal

import pytest

from bnc_bot.venezuela import (
    DatoInvalido, banco_de_cuenta, formato_bs, normalizar_cedula, normalizar_cuenta,
    parse_monto, similitud_nombres,
)


def test_cuenta():
    assert normalizar_cuenta("0191-0000-11-1234567890") == "01910000111234567890"
    assert banco_de_cuenta("0134 0000 00 0000000000") == "Banesco"
    with pytest.raises(DatoInvalido):
        normalizar_cuenta("0191123")
    with pytest.raises(DatoInvalido):
        normalizar_cuenta("9999" + "0" * 16)


def test_cedula():
    assert normalizar_cedula("V-12.345.678") == ("V", "12345678")
    assert normalizar_cedula("12345678") == ("V", "12345678")
    assert normalizar_cedula("j-40123456-7".replace("-7", "7")) == ("J", "401234567")
    with pytest.raises(DatoInvalido):
        normalizar_cedula("abc")


@pytest.mark.parametrize("raw,esperado", [
    ("1250.5", "1250.50"), ("1.250,50", "1250.50"), ("1,250.50", "1250.50"),
    ("Bs. 12.345.678,9", "12345678.90"), ("100", "100.00"),
])
def test_monto(raw, esperado):
    assert parse_monto(raw) == Decimal(esperado)


def test_monto_invalido():
    for raw in ("", "0", "-5", "abc"):
        with pytest.raises(DatoInvalido):
            parse_monto(raw)


def test_formato_bs():
    assert formato_bs(Decimal("1234567.5")) == "1.234.567,50"
    assert formato_bs(Decimal("12")) == "12,00"


def test_similitud():
    assert similitud_nombres("JUAN CARLOS PÉREZ GÓMEZ", "Juan Perez") == 1.0
    assert similitud_nombres("JUAN PEREZ", "MARIA LOPEZ") == 0.0
    assert similitud_nombres("", "x") == 0.0
