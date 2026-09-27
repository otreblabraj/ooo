"""Utilidades específicas de Venezuela: códigos de banco, montos y comparación de nombres."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Primeros 4 dígitos de la cuenta (código SUDEBAN) -> banco
BANCOS: dict[str, str] = {
    "0102": "Banco de Venezuela",
    "0104": "Venezolano de Crédito",
    "0105": "Mercantil",
    "0108": "Provincial",
    "0114": "Bancaribe",
    "0115": "Exterior",
    "0128": "Caroní",
    "0134": "Banesco",
    "0137": "Sofitasa",
    "0138": "Plaza",
    "0146": "Bangente",
    "0151": "BFC",
    "0156": "100% Banco",
    "0157": "DelSur",
    "0163": "Banco del Tesoro",
    "0166": "Banco Agrícola",
    "0168": "Bancrecer",
    "0169": "R4 / Mi Banco",
    "0171": "Banco Activo",
    "0172": "Bancamiga",
    "0173": "Banco Internacional de Desarrollo",
    "0174": "Banplus",
    "0175": "Banco Digital de los Trabajadores",
    "0177": "Banfanb",
    "0178": "N58 Banco Digital",
    "0191": "BNC",
}
CODIGO_BNC = "0191"


class DatoInvalido(ValueError):
    pass


def normalizar_cuenta(raw: str) -> str:
    """Devuelve la cuenta en 20 dígitos o lanza DatoInvalido."""
    digitos = re.sub(r"\D", "", raw or "")
    if len(digitos) != 20:
        raise DatoInvalido(f"La cuenta debe tener 20 dígitos (tiene {len(digitos)}): {raw!r}")
    if digitos[:4] not in BANCOS:
        raise DatoInvalido(f"Código de banco desconocido {digitos[:4]} en {raw!r}")
    return digitos


def banco_de_cuenta(cuenta: str) -> str:
    return BANCOS[normalizar_cuenta(cuenta)[:4]]


def normalizar_cedula(raw: str) -> tuple[str, str]:
    """'V-12.345.678' -> ('V', '12345678'). Si no trae letra se asume V."""
    s = (raw or "").upper().strip()
    m = re.match(r"^\s*([VEJPG])?\s*[-.]?\s*([\d.\s]+)\s*$", s)
    if not m:
        raise DatoInvalido(f"Cédula/RIF inválido: {raw!r}")
    numero = re.sub(r"\D", "", m.group(2))
    if not 5 <= len(numero) <= 10:
        raise DatoInvalido(f"Cédula/RIF con longitud inválida: {raw!r}")
    return (m.group(1) or "V", numero)


def parse_monto(raw: str | int | float | Decimal) -> Decimal:
    """Acepta '1250.5', '1.250,50', '1,250.50' y devuelve Decimal con 2 decimales."""
    if isinstance(raw, Decimal):
        valor = raw
    elif isinstance(raw, (int, float)):
        valor = Decimal(str(raw))
    else:
        s = re.sub(r"[^\d,.\-]", "", raw)
        if "," in s and "." in s:
            # el separador decimal es el último que aparece
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            valor = Decimal(s)
        except InvalidOperation as e:
            raise DatoInvalido(f"Monto inválido: {raw!r}") from e
    if valor <= 0:
        raise DatoInvalido(f"Monto debe ser positivo: {raw!r}")
    return valor.quantize(Decimal("0.01"))


def formato_bs(monto: Decimal) -> str:
    """Decimal('1250.5') -> '1.250,50' (formato que usan los bancos venezolanos)."""
    entero, dec = f"{monto:.2f}".split(".")
    entero = f"{int(entero):,}".replace(",", ".")
    return f"{entero},{dec}"


def _tokens(nombre: str) -> set[str]:
    s = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z ]", " ", s)
    return {t for t in s.split() if len(t) > 1 and t not in {"DE", "DEL", "LA", "LOS", "LAS", "Y"}}


def similitud_nombres(a: str, b: str) -> float:
    """Proporción de palabras del nombre más corto que aparecen en el otro (0 a 1).

    'JUAN CARLOS PEREZ GOMEZ' vs 'Juan Pérez' -> 1.0
    'JUAN PEREZ' vs 'MARIA LOPEZ' -> 0.0
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    corto, largo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(corto & largo) / len(corto)
