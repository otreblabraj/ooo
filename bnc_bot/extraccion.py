"""Bot 2 (lógica pura): convierte el detalle de una orden de Binance en datos de transferencia.

Los métodos de pago de Binance traen campos con nombres variables según la plantilla
("Account number", "Número de cuenta", "Bank account number"...). Aquí se buscan por
palabras clave para no depender de un nombre exacto.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .venezuela import (
    DatoInvalido, banco_de_cuenta, normalizar_cedula, normalizar_cuenta, parse_monto,
)

CLAVES_CUENTA = ("account", "cuenta", "acct", "número de cuenta", "numero de cuenta")
CLAVES_TITULAR = ("name", "nombre", "titular", "holder", "beneficiario")
CLAVES_CEDULA = ("cedula", "cédula", "id number", "identification", "documento", "ci", "rif", "id")
EXCLUIR_CUENTA = ("type", "tipo", "name", "nombre")


@dataclass(frozen=True)
class DatosPago:
    order_no: str
    monto: Decimal
    nombre_kyc: str
    titular: str
    cedula: str       # "V12345678"
    cuenta: str       # 20 dígitos
    banco: str
    pay_id: str


def _campo(campos: list[dict], claves: tuple[str, ...], excluir: tuple[str, ...] = ()) -> str:
    for c in campos:
        nombre = str(c.get("fieldName") or c.get("fieldContentType") or "").lower()
        valor = str(c.get("fieldValue") or "").strip()
        if not valor:
            continue
        if any(k in nombre for k in claves) and not any(e in nombre for e in excluir):
            return valor
    return ""


def _es_transferencia(metodo: dict) -> bool:
    """Descarta pago móvil: solo interesan métodos con una cuenta de 20 dígitos."""
    for c in metodo.get("fields", []):
        try:
            normalizar_cuenta(str(c.get("fieldValue") or ""))
            return True
        except DatoInvalido:
            continue
    return False


def extraer(detalle: dict) -> DatosPago:
    order_no = str(detalle.get("orderNumber") or detalle.get("adOrderNo") or "")
    if not order_no:
        raise DatoInvalido("La orden no trae número")
    monto = parse_monto(str(detalle.get("totalPrice") or detalle.get("amount") or ""))
    nombre_kyc = str(detalle.get("sellerName") or detalle.get("sellerRealName")
                     or detalle.get("counterPartRealName") or "").strip()

    metodos = detalle.get("payMethods") or detalle.get("tradeMethods") or []
    candidatos = [m for m in metodos if _es_transferencia(m)]
    if not candidatos:
        raise DatoInvalido(f"Orden {order_no}: el vendedor no tiene método de transferencia con cuenta de 20 dígitos")
    # Si hay varios, preferir BNC (transferencia interna, más rápida)
    candidatos.sort(key=lambda m: 0 if any(
        str(c.get("fieldValue", "")).replace("-", "").replace(" ", "").startswith("0191")
        for c in m.get("fields", [])) else 1)
    metodo = candidatos[0]
    campos = metodo.get("fields", [])

    cuenta_raw = next(
        (str(c["fieldValue"]) for c in campos
         if c.get("fieldValue") and _cuenta_valida(str(c["fieldValue"]))),
        "",
    )
    cuenta = normalizar_cuenta(cuenta_raw)
    titular = _campo(campos, CLAVES_TITULAR, excluir=("bank", "banco")) or nombre_kyc
    ced_raw = _campo(campos, CLAVES_CEDULA, excluir=CLAVES_CUENTA + ("name", "nombre"))
    if not ced_raw:
        raise DatoInvalido(f"Orden {order_no}: no se encontró cédula/RIF del titular")
    tipo, num = normalizar_cedula(ced_raw)

    return DatosPago(
        order_no=order_no, monto=monto, nombre_kyc=nombre_kyc, titular=titular,
        cedula=f"{tipo}{num}", cuenta=cuenta, banco=banco_de_cuenta(cuenta),
        pay_id=str(metodo.get("id") or metodo.get("payId") or ""),
    )


def _cuenta_valida(valor: str) -> bool:
    try:
        normalizar_cuenta(valor)
        return True
    except DatoInvalido:
        return False
