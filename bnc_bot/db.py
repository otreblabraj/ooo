"""Base de datos SQLite: es el "canal" real entre los bots y la memoria de cada orden.

Cada orden de Binance pasa por una máquina de estados. Los cambios de estado son
atómicos (compare-and-set), así dos bots nunca procesan la misma orden y una orden
nunca se paga dos veces aunque el programa se caiga a mitad de camino.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path


class Estado(str, Enum):
    NUEVA = "NUEVA"                        # detectada en Binance (bot Binance)
    POR_APROBAR = "POR_APROBAR"            # esperando tu botón ✅ en Telegram
    APROBADA = "APROBADA"                  # validada, lista para BNC
    BENEFICIARIO_OK = "BENEFICIARIO_OK"    # beneficiario existe/registrado en BNC (bot 3)
    PAGANDO = "PAGANDO"                    # bot 4 empezó a confirmar la transferencia
    PAGADA = "PAGADA"                      # transferencia hecha + comprobante capturado (bot 4/5)
    COMPROBANTE_SUBIDO = "COMPROBANTE_SUBIDO"  # foto en el chat de la orden (bot Binance)
    COMPLETADA = "COMPLETADA"              # orden marcada como pagada en Binance
    RECHAZADA = "RECHAZADA"                # validación falló o la rechazaste tú
    REVISION_MANUAL = "REVISION_MANUAL"    # algo raro: NO se reintenta sola


TRANSICIONES: dict[Estado, set[Estado]] = {
    Estado.NUEVA: {Estado.POR_APROBAR, Estado.APROBADA, Estado.RECHAZADA, Estado.REVISION_MANUAL},
    Estado.POR_APROBAR: {Estado.APROBADA, Estado.RECHAZADA},
    Estado.APROBADA: {Estado.BENEFICIARIO_OK, Estado.REVISION_MANUAL},
    Estado.BENEFICIARIO_OK: {Estado.PAGANDO, Estado.REVISION_MANUAL},
    # Desde PAGANDO nunca se vuelve atrás: si hay duda, revisión manual.
    Estado.PAGANDO: {Estado.PAGADA, Estado.REVISION_MANUAL},
    Estado.PAGADA: {Estado.COMPROBANTE_SUBIDO, Estado.REVISION_MANUAL},
    Estado.COMPROBANTE_SUBIDO: {Estado.COMPLETADA, Estado.REVISION_MANUAL},
    Estado.COMPLETADA: set(),
    Estado.RECHAZADA: set(),
    # Tú puedes devolver una orden en revisión a APROBADA (reintentar) o marcarla como PAGADA
    # (si verificaste en el banco que el pago sí salió).
    Estado.REVISION_MANUAL: {Estado.APROBADA, Estado.PAGADA, Estado.RECHAZADA},
}

class TransicionInvalida(RuntimeError):
    pass


@dataclass
class Orden:
    order_no: str
    estado: Estado
    monto: Decimal
    nombre_kyc: str
    titular: str
    cedula: str
    cuenta: str
    banco: str
    pay_id: str
    comprobante: str
    referencia: str
    nota: str
    datos: dict

    @classmethod
    def de_fila(cls, r: sqlite3.Row) -> "Orden":
        return cls(
            order_no=r["order_no"], estado=Estado(r["estado"]), monto=Decimal(r["monto"]),
            nombre_kyc=r["nombre_kyc"] or "", titular=r["titular"] or "", cedula=r["cedula"] or "",
            cuenta=r["cuenta"] or "", banco=r["banco"] or "", pay_id=r["pay_id"] or "",
            comprobante=r["comprobante"] or "", referencia=r["referencia"] or "",
            nota=r["nota"] or "", datos=json.loads(r["datos"] or "{}"),
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ordenes (
    order_no    TEXT PRIMARY KEY,
    estado      TEXT NOT NULL,
    monto       TEXT NOT NULL,
    nombre_kyc  TEXT,
    titular     TEXT,
    cedula      TEXT,
    cuenta      TEXT,
    banco       TEXT,
    pay_id      TEXT,
    comprobante TEXT,
    referencia  TEXT,
    nota        TEXT,
    datos       TEXT,
    creada      TEXT NOT NULL,
    actualizada TEXT NOT NULL,
    fecha_pago  TEXT
);
CREATE TABLE IF NOT EXISTS beneficiarios (
    cuenta      TEXT PRIMARY KEY,
    titular     TEXT NOT NULL,
    cedula      TEXT NOT NULL,
    registrado  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no  TEXT,
    desde     TEXT,
    hacia     TEXT,
    nota      TEXT,
    momento   TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(_SCHEMA)
        self._lock = threading.Lock()

    # ─── órdenes ───
    def insertar_orden(self, order_no: str, monto: Decimal, datos: dict) -> bool:
        """Inserta la orden como NUEVA. Devuelve False si ya existía (idempotente)."""
        with self._lock:
            cur = self._con.execute(
                "INSERT OR IGNORE INTO ordenes (order_no, estado, monto, datos, creada, actualizada)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (order_no, Estado.NUEVA.value, str(monto), json.dumps(datos, default=str), _ahora(), _ahora()),
            )
            return cur.rowcount == 1

    def obtener(self, order_no: str) -> Orden | None:
        r = self._con.execute("SELECT * FROM ordenes WHERE order_no=?", (order_no,)).fetchone()
        return Orden.de_fila(r) if r else None

    def por_estado(self, estado: Estado) -> list[Orden]:
        filas = self._con.execute(
            "SELECT * FROM ordenes WHERE estado=? ORDER BY creada", (estado.value,)
        ).fetchall()
        return [Orden.de_fila(r) for r in filas]

    def actualizar_campos(self, order_no: str, **campos: str) -> None:
        permitidos = {"monto", "nombre_kyc", "titular", "cedula", "cuenta", "banco", "pay_id",
                      "comprobante", "referencia", "nota"}
        if not campos or set(campos) - permitidos:
            raise ValueError(f"Campos no permitidos: {set(campos) - permitidos}")
        sets = ", ".join(f"{k}=?" for k in campos)
        with self._lock:
            self._con.execute(
                f"UPDATE ordenes SET {sets}, actualizada=? WHERE order_no=?",
                (*campos.values(), _ahora(), order_no),
            )

    def transicion(self, order_no: str, desde: Estado, hacia: Estado, nota: str = "") -> None:
        """Cambia el estado solo si la orden sigue en `desde`. Lanza TransicionInvalida si no."""
        if hacia not in TRANSICIONES[desde]:
            raise TransicionInvalida(f"{desde.value} -> {hacia.value} no está permitido")
        with self._lock:
            extra = ", fecha_pago=?" if hacia is Estado.PAGANDO else ""
            params: tuple = (hacia.value, nota, _ahora())
            if extra:
                params += (datetime.now().date().isoformat(),)
            cur = self._con.execute(
                f"UPDATE ordenes SET estado=?, nota=?, actualizada=?{extra}"
                " WHERE order_no=? AND estado=?",
                (*params, order_no, desde.value),
            )
            if cur.rowcount != 1:
                actual = self.obtener(order_no)
                raise TransicionInvalida(
                    f"Orden {order_no}: se esperaba {desde.value}, está en "
                    f"{actual.estado.value if actual else 'inexistente'}"
                )
            self._con.execute(
                "INSERT INTO eventos (order_no, desde, hacia, nota, momento) VALUES (?, ?, ?, ?, ?)",
                (order_no, desde.value, hacia.value, nota, _ahora()),
            )

    def llego_a_pagar(self, order_no: str) -> bool:
        """True si la orden alguna vez entró en PAGANDO (el dinero pudo haber salido)."""
        r = self._con.execute(
            "SELECT 1 FROM eventos WHERE order_no=? AND hacia=? LIMIT 1",
            (order_no, Estado.PAGANDO.value),
        ).fetchone()
        return r is not None

    def total_pagado_hoy(self) -> Decimal:
        """Suma de órdenes que hoy llegaron a PAGANDO (incluye las que quedaron en revisión,
        porque el dinero pudo haber salido), salvo las que rechazaste después de verificar."""
        hoy = datetime.now().date().isoformat()
        filas = self._con.execute(
            "SELECT monto FROM ordenes WHERE fecha_pago=? AND estado != ?",
            (hoy, Estado.RECHAZADA.value),
        ).fetchall()
        return sum((Decimal(r["monto"]) for r in filas), Decimal("0"))

    # ─── beneficiarios ───
    def beneficiario(self, cuenta: str) -> sqlite3.Row | None:
        return self._con.execute("SELECT * FROM beneficiarios WHERE cuenta=?", (cuenta,)).fetchone()

    def guardar_beneficiario(self, cuenta: str, titular: str, cedula: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO beneficiarios (cuenta, titular, cedula, registrado)"
                " VALUES (?, ?, ?, ?)",
                (cuenta, titular, cedula, _ahora()),
            )
