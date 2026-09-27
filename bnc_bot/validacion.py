"""Reglas de seguridad antes de mover dinero."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .extraccion import DatosPago
from .venezuela import similitud_nombres


class Decision(str, Enum):
    AUTOMATICA = "AUTOMATICA"
    MANUAL = "MANUAL"
    RECHAZAR = "RECHAZAR"


@dataclass
class Resultado:
    decision: Decision
    motivos: list[str] = field(default_factory=list)


def evaluar(
    datos: DatosPago,
    *,
    pagado_hoy: Decimal,
    monto_max_orden: Decimal,
    monto_max_dia: Decimal,
    umbral_aprobacion: Decimal,
    similitud_min: float,
) -> Resultado:
    motivos: list[str] = []

    if datos.monto > monto_max_orden:
        return Resultado(Decision.RECHAZAR, [f"Monto {datos.monto} supera el máximo por orden {monto_max_orden}"])
    if pagado_hoy + datos.monto > monto_max_dia:
        return Resultado(Decision.RECHAZAR, [f"Se superaría el máximo diario ({pagado_hoy} + {datos.monto} > {monto_max_dia})"])

    manual = False
    sim = similitud_nombres(datos.nombre_kyc, datos.titular)
    if not datos.nombre_kyc:
        manual = True
        motivos.append("Binance no devolvió el nombre KYC del vendedor")
    elif sim < similitud_min:
        # Posible triangulación: el titular de la cuenta no es quien vende.
        manual = True
        motivos.append(f"⚠️ Titular '{datos.titular}' no coincide con KYC '{datos.nombre_kyc}' (similitud {sim:.0%})")

    if umbral_aprobacion == 0 or datos.monto > umbral_aprobacion:
        manual = True
        motivos.append("Monto requiere aprobación manual")

    return Resultado(Decision.MANUAL if manual else Decision.AUTOMATICA, motivos)
