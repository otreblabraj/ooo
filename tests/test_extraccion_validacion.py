from decimal import Decimal

import pytest

from bnc_bot.extraccion import extraer
from bnc_bot.validacion import Decision, evaluar
from bnc_bot.venezuela import DatoInvalido
from tests.conftest import detalle_orden

LIMITES = dict(monto_max_orden=Decimal("50000"), monto_max_dia=Decimal("100000"),
               umbral_aprobacion=Decimal("5000"), similitud_min=0.6)


def test_extrae_transferencia_ignorando_pago_movil():
    d = extraer(detalle_orden())
    assert d.cuenta == "01340000112222333344"
    assert d.banco == "Banesco"
    assert d.cedula == "V12345678"
    assert d.titular == "Juan Perez"
    assert d.monto == Decimal("1250.50")
    assert d.pay_id == "222"


def test_prefiere_cuenta_bnc():
    det = detalle_orden()
    det["payMethods"].append({"id": 333, "fields": [
        {"fieldName": "Account number", "fieldValue": "01910000112222333344"},
        {"fieldName": "Cédula", "fieldValue": "12345678"},
    ]})
    assert extraer(det).cuenta.startswith("0191")


def test_sin_transferencia_falla():
    det = detalle_orden(payMethods=[{"id": 1, "fields": [{"fieldName": "Phone", "fieldValue": "0414"}]}])
    with pytest.raises(DatoInvalido):
        extraer(det)


def test_validacion_automatica():
    r = evaluar(extraer(detalle_orden()), pagado_hoy=Decimal("0"), **LIMITES)
    assert r.decision is Decision.AUTOMATICA, r.motivos


def test_validacion_nombre_distinto_pide_aprobacion():
    r = evaluar(extraer(detalle_orden(sellerName="MARIA LOPEZ")), pagado_hoy=Decimal("0"), **LIMITES)
    assert r.decision is Decision.MANUAL
    assert any("no coincide" in m for m in r.motivos)


def test_validacion_umbral_y_limites():
    d = extraer(detalle_orden(totalPrice="6000"))
    assert evaluar(d, pagado_hoy=Decimal("0"), **LIMITES).decision is Decision.MANUAL
    d = extraer(detalle_orden(totalPrice="60000"))
    assert evaluar(d, pagado_hoy=Decimal("0"), **LIMITES).decision is Decision.RECHAZAR
    d = extraer(detalle_orden(totalPrice="1000"))
    assert evaluar(d, pagado_hoy=Decimal("99500"), **LIMITES).decision is Decision.RECHAZAR


def test_umbral_cero_todo_manual():
    r = evaluar(extraer(detalle_orden()), pagado_hoy=Decimal("0"),
                **{**LIMITES, "umbral_aprobacion": Decimal("0")})
    assert r.decision is Decision.MANUAL
