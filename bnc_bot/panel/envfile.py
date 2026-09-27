"""Edita el archivo .env conservando comentarios y orden."""
from __future__ import annotations

import re
from pathlib import Path

_LINEA = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _citar(valor: str) -> str:
    if valor == "" or re.fullmatch(r"[A-Za-z0-9_.:/@+\-,]+", valor):
        return valor
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def actualizar(ruta: Path, cambios: dict[str, str]) -> None:
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    pendientes = dict(cambios)
    for i, linea in enumerate(lineas):
        m = _LINEA.match(linea)
        if m and m.group(1) in pendientes:
            clave = m.group(1)
            lineas[i] = f"{clave}={_citar(pendientes.pop(clave))}"
    if pendientes:
        lineas.append("")
        lineas += [f"{k}={_citar(v)}" for k, v in pendientes.items()]
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    tmp.replace(ruta)
