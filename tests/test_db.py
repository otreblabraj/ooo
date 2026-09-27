from decimal import Decimal

import pytest

from bnc_bot.db import DB, Estado, TransicionInvalida


def test_idempotencia_y_transiciones():
    db = DB(":memory:")
    assert db.insertar_orden("1", Decimal("10"), {}) is True
    assert db.insertar_orden("1", Decimal("10"), {}) is False
    db.transicion("1", Estado.NUEVA, Estado.APROBADA)
    # Dos bots intentando lo mismo: el segundo falla
    with pytest.raises(TransicionInvalida):
        db.transicion("1", Estado.NUEVA, Estado.APROBADA)
    # Saltos no permitidos
    with pytest.raises(TransicionInvalida):
        db.transicion("1", Estado.APROBADA, Estado.COMPLETADA)


def test_total_pagado_hoy_y_llego_a_pagar():
    db = DB(":memory:")
    db.insertar_orden("1", Decimal("100.50"), {})
    for a, b in [(Estado.NUEVA, Estado.APROBADA), (Estado.APROBADA, Estado.BENEFICIARIO_OK)]:
        db.transicion("1", a, b)
    assert db.total_pagado_hoy() == 0
    assert not db.llego_a_pagar("1")
    db.transicion("1", Estado.BENEFICIARIO_OK, Estado.PAGANDO)
    assert db.total_pagado_hoy() == Decimal("100.50")
    db.transicion("1", Estado.PAGANDO, Estado.REVISION_MANUAL)
    assert db.llego_a_pagar("1")


def test_revision_tras_pagando_sigue_contando():
    db = DB(":memory:")
    db.insertar_orden("1", Decimal("50"), {})
    for a, b in [(Estado.NUEVA, Estado.APROBADA), (Estado.APROBADA, Estado.BENEFICIARIO_OK),
                 (Estado.BENEFICIARIO_OK, Estado.PAGANDO), (Estado.PAGANDO, Estado.REVISION_MANUAL)]:
        db.transicion("1", a, b)
    assert db.total_pagado_hoy() == Decimal("50")
    db.transicion("1", Estado.REVISION_MANUAL, Estado.RECHAZADA)
    assert db.total_pagado_hoy() == 0
