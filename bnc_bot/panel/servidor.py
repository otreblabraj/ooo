"""Panel de control local: encender/apagar el bot, cuentas BNC y ajustes.

    python -m bnc_bot.panel        → http://127.0.0.1:8765

Solo escucha en 127.0.0.1 (tu computadora). Si defines PANEL_CLAVE en .env, el navegador
pedirá usuario (cualquiera) y esa clave.
"""
from __future__ import annotations

import atexit
import base64
import hmac
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import dotenv_values

from ..venezuela import CODIGO_BNC, DatoInvalido, normalizar_cuenta
from . import envfile

RAIZ = Path(__file__).resolve().parents[2]
ENV = RAIZ / ".env"
DATA = RAIZ / "data"
CUENTAS = DATA / "cuentas.json"
LOG = DATA / "bot.log"
DETENER = DATA / "detener"
PAGINA = Path(__file__).with_name("pagina.html")

# (clave, sección, etiqueta, tipo)  tipo: texto | secreto | numero | bool
AJUSTES: list[tuple[str, str, str, str]] = [
    ("BINANCE_API_KEY", "Binance", "API Key", "secreto"),
    ("BINANCE_API_SECRET", "Binance", "API Secret", "secreto"),
    ("BINANCE_FIAT", "Binance", "Moneda de las órdenes", "texto"),
    ("TELEGRAM_CHAT_ID", "Telegram", "ID del grupo principal", "texto"),
    ("TELEGRAM_CHAT_ID_FALLOS", "Telegram", "ID del grupo de fallos", "texto"),
    ("TELEGRAM_ADMIN_ID", "Telegram", "Tu user_id de Telegram", "texto"),
    ("TELEGRAM_TOKEN_HUB", "Telegram", "Token bot Hub", "secreto"),
    ("TELEGRAM_TOKEN_BINANCE", "Telegram", "Token bot Binance (opcional)", "secreto"),
    ("TELEGRAM_TOKEN_BNC", "Telegram", "Token bot BNC (opcional)", "secreto"),
    ("TELEGRAM_TOKEN_COMPROBANTE", "Telegram", "Token bot Comprobante (opcional)", "secreto"),
    ("TELEGRAM_TOKEN_FALLOS", "Telegram", "Token bot Fallos (opcional)", "secreto"),
    ("CORREO_USUARIO", "Correo de códigos BNC", "Correo", "texto"),
    ("CORREO_CLAVE", "Correo de códigos BNC", "Contraseña de aplicación", "secreto"),
    ("CORREO_REMITENTE", "Correo de códigos BNC", "Remitente de BNC", "texto"),
    ("CORREO_IMAP", "Correo de códigos BNC", "Servidor IMAP", "texto"),
    ("CORREO_PATRON", "Correo de códigos BNC", "Patrón del código (opcional)", "texto"),
    ("BNC_URL", "BNC", "Dirección de BNC en línea", "texto"),
    ("BNC_HEADFUL", "BNC", "Mostrar el navegador mientras trabaja", "bool"),
    ("MONTO_MAX_ORDEN", "Límites", "Máximo por orden (Bs)", "numero"),
    ("MONTO_MAX_DIA", "Límites", "Máximo por día (Bs)", "numero"),
    ("UMBRAL_APROBACION", "Límites", "Pedir aprobación por encima de (Bs, 0 = siempre)", "numero"),
    ("SIMILITUD_NOMBRE_MIN", "Límites", "Similitud mínima de nombre (0 a 1)", "numero"),
    ("POLL_SEGUNDOS", "Límites", "Revisar Binance cada (segundos)", "numero"),
    ("PANEL_CLAVE", "Panel", "Clave para abrir este panel (opcional)", "secreto"),
]
TIPOS = {k: t for k, _, _, t in AJUSTES}


# ─────────────────────────── cuentas BNC ───────────────────────────
_lock_cuentas = threading.Lock()


def leer_cuentas() -> dict:
    try:
        return json.loads(CUENTAS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cuentas": [], "activa": None}


def _guardar_cuentas(data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CUENTAS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CUENTAS)


def cuentas_publicas() -> dict:
    data = leer_cuentas()
    return {
        "activa": data.get("activa"),
        "cuentas": [{
            "id": c["id"], "alias": c["alias"], "usuario": c["usuario"],
            "cuenta_origen": c["cuenta_origen"], "tiene_clave": bool(c.get("clave")),
            "preguntas": len([p for p in c.get("preguntas", "").split(";") if "=" in p]),
        } for c in data["cuentas"]],
    }


def guardar_cuenta(entrada: dict) -> dict:
    alias = str(entrada.get("alias", "")).strip()
    usuario = str(entrada.get("usuario", "")).strip()
    if not alias or not usuario:
        raise ValueError("Escribe un nombre para la cuenta y el usuario de BNC.")
    try:
        cuenta = normalizar_cuenta(str(entrada.get("cuenta_origen", "")))
    except DatoInvalido as e:
        raise ValueError(str(e)) from e
    if not cuenta.startswith(CODIGO_BNC):
        raise ValueError("La cuenta de origen debe ser de BNC (empieza por 0191).")
    with _lock_cuentas:
        data = leer_cuentas()
        existente = next((c for c in data["cuentas"] if c["id"] == entrada.get("id")), None)
        clave = str(entrada.get("clave", ""))
        preguntas = str(entrada.get("preguntas", ""))
        if existente is None:
            if not clave:
                raise ValueError("Escribe la clave de BNC de la cuenta nueva.")
            existente = {"id": uuid.uuid4().hex[:10]}
            data["cuentas"].append(existente)
        existente.update(alias=alias, usuario=usuario, cuenta_origen=cuenta)
        if clave:
            existente["clave"] = clave
        if preguntas or "preguntas" not in existente:
            existente["preguntas"] = preguntas
        if not data.get("activa"):
            data["activa"] = existente["id"]
        _guardar_cuentas(data)
    return cuentas_publicas()


def activar_cuenta(id_: str) -> dict:
    with _lock_cuentas:
        data = leer_cuentas()
        if not any(c["id"] == id_ for c in data["cuentas"]):
            raise ValueError("Esa cuenta no existe.")
        data["activa"] = id_
        _guardar_cuentas(data)
    return cuentas_publicas()


def borrar_cuenta(id_: str) -> dict:
    with _lock_cuentas:
        data = leer_cuentas()
        data["cuentas"] = [c for c in data["cuentas"] if c["id"] != id_]
        if data.get("activa") == id_:
            data["activa"] = data["cuentas"][0]["id"] if data["cuentas"] else None
        _guardar_cuentas(data)
    return cuentas_publicas()


def cuenta_activa() -> dict | None:
    data = leer_cuentas()
    return next((c for c in data["cuentas"] if c["id"] == data.get("activa")), None)


# ─────────────────────────── ajustes (.env) ───────────────────────────
def ajustes_publicos() -> dict:
    valores = dotenv_values(ENV) if ENV.exists() else {}
    campos = []
    for clave, seccion, etiqueta, tipo in AJUSTES:
        v = valores.get(clave) or ""
        campos.append({
            "clave": clave, "seccion": seccion, "etiqueta": etiqueta, "tipo": tipo,
            "valor": "" if tipo == "secreto" else v, "tiene_valor": bool(v),
        })
    return {"campos": campos, "simulacion": _es_verdad(valores.get("SIMULACION", "true"))}


def _es_verdad(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "si", "sí", "yes"}


def guardar_ajustes(entrada: dict) -> dict:
    cambios: dict[str, str] = {}
    for clave, valor in entrada.items():
        if clave == "SIMULACION":
            cambios[clave] = "true" if valor else "false"
            continue
        tipo = TIPOS.get(clave)
        if tipo is None:
            continue
        if tipo == "secreto" and valor in ("", None):
            continue  # vacío = no cambiar
        if tipo == "bool":
            valor = "true" if valor in (True, "true", "1") else "false"
        valor = str(valor).strip()
        if tipo == "numero" and valor:
            try:
                float(valor)
            except ValueError:
                raise ValueError(f"«{clave}» debe ser un número.")
        cambios[clave] = valor
    envfile.actualizar(ENV, cambios)
    return ajustes_publicos()


# ─────────────────────────── proceso del bot ───────────────────────────
class ControlBot:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.desde: float | None = None
        self.solo_binance = False
        self.apagando = False
        self.ultimo_codigo: int | None = None
        self._lock = threading.Lock()

    def corriendo(self) -> bool:
        if self.proc is not None and self.proc.poll() is not None:
            self.ultimo_codigo = self.proc.returncode
            self.proc, self.desde, self.apagando = None, None, False
            DETENER.unlink(missing_ok=True)
        return self.proc is not None

    def encender(self, solo_binance: bool) -> None:
        with self._lock:
            if self.corriendo():
                raise ValueError("El bot ya está encendido.")
            env = {**os.environ, **{k: v for k, v in (dotenv_values(ENV) if ENV.exists() else {}).items() if v is not None}}
            cuenta = cuenta_activa()
            if cuenta:
                env.update(BNC_USUARIO=cuenta["usuario"], BNC_CLAVE=cuenta.get("clave", ""),
                           BNC_PREGUNTAS=cuenta.get("preguntas", ""), BNC_CUENTA_ORIGEN=cuenta["cuenta_origen"])
            if not solo_binance and not env.get("BNC_USUARIO"):
                raise ValueError("Agrega una cuenta BNC (pestaña Cuentas) o enciende en modo «solo Binance».")
            if not env.get("BINANCE_API_KEY"):
                raise ValueError("Falta la API Key de Binance (pestaña Ajustes).")
            env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            DATA.mkdir(parents=True, exist_ok=True)
            DETENER.unlink(missing_ok=True)
            log = LOG.open("a", encoding="utf-8")
            log.write(f"\n──── {datetime.now():%Y-%m-%d %H:%M:%S} encendido desde el panel"
                      f"{' (solo Binance)' if solo_binance else ''} ────\n")
            log.flush()
            args = [sys.executable, "-m", "bnc_bot"] + (["--solo-binance"] if solo_binance else [])
            self.proc = subprocess.Popen(args, cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT)
            log.close()
            self.desde, self.solo_binance, self.apagando = time.time(), solo_binance, False

    def apagar(self, forzar: bool = False) -> None:
        with self._lock:
            if not self.corriendo():
                return
            if not forzar:
                DATA.mkdir(parents=True, exist_ok=True)
                DETENER.touch()
                self.apagando = True
                return
            self.proc.terminate() if os.name == "nt" else self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.corriendo()

    def estado(self) -> dict:
        activo = self.corriendo()
        return {
            "corriendo": activo, "apagando": self.apagando and activo,
            "pid": self.proc.pid if activo else None,
            "desde": self.desde, "solo_binance": self.solo_binance if activo else False,
            "ultimo_codigo": self.ultimo_codigo,
        }

    def cerrar_al_salir(self) -> None:
        if self.corriendo():
            self.apagar()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.apagar(forzar=True)


BOT = ControlBot()
atexit.register(BOT.cerrar_al_salir)


def ultimas_lineas(n: int = 120) -> list[str]:
    try:
        with LOG.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64_000))
            return f.read().decode("utf-8", errors="replace").splitlines()[-n:]
    except FileNotFoundError:
        return []


def ordenes() -> dict:
    db_path = RAIZ / (dotenv_values(ENV).get("DB_PATH") if ENV.exists() and dotenv_values(ENV).get("DB_PATH")
                      else "data/bnc_bot.sqlite3")
    if not db_path.exists():
        return {"lista": [], "conteo": {}, "pagado_hoy": "0"}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        lista = [dict(r) for r in con.execute(
            "SELECT order_no, estado, monto, titular, banco, referencia, nota, actualizada"
            " FROM ordenes ORDER BY actualizada DESC LIMIT 40")]
        conteo = {r["estado"]: r["n"] for r in con.execute(
            "SELECT estado, COUNT(*) n FROM ordenes GROUP BY estado")}
        hoy = datetime.now().date().isoformat()
        pagado = sum(float(r["monto"]) for r in con.execute(
            "SELECT monto FROM ordenes WHERE fecha_pago=? AND estado != 'RECHAZADA'", (hoy,)))
    finally:
        con.close()
    return {"lista": lista, "conteo": conteo, "pagado_hoy": f"{pagado:.2f}"}


def estado_general() -> dict:
    from ..bnc.selectores import faltantes

    valores = dotenv_values(ENV) if ENV.exists() else {}
    cuenta = cuenta_activa()
    return {
        "bot": BOT.estado(),
        "simulacion": _es_verdad(valores.get("SIMULACION", "true")),
        "cuenta_activa": ({"alias": cuenta["alias"], "cuenta": cuenta["cuenta_origen"]} if cuenta else None),
        "chequeos": {
            "binance": bool(valores.get("BINANCE_API_KEY") and valores.get("BINANCE_API_SECRET")),
            "telegram": bool(valores.get("TELEGRAM_TOKEN_HUB") and valores.get("TELEGRAM_CHAT_ID")),
            "fallos": bool(valores.get("TELEGRAM_CHAT_ID_FALLOS")),
            "correo": bool(valores.get("CORREO_USUARIO") and valores.get("CORREO_CLAVE")
                           and valores.get("CORREO_REMITENTE")),
            "cuenta_bnc": cuenta is not None,
            "selectores_faltantes": len(faltantes()),
        },
        "ordenes": ordenes(),
        "log": ultimas_lineas(),
    }


# ─────────────────────────── HTTP ───────────────────────────
class Manejador(BaseHTTPRequestHandler):
    server_version = "PanelBNC"

    def log_message(self, *_):  # silencioso
        pass

    def _autorizado(self) -> bool:
        clave = (dotenv_values(ENV).get("PANEL_CLAVE") if ENV.exists() else "") or ""
        if not clave:
            return True
        cab = self.headers.get("Authorization", "")
        if cab.startswith("Basic "):
            try:
                _, _, dada = base64.b64decode(cab[6:]).decode().partition(":")
                if hmac.compare_digest(dada, clave):
                    return True
            except Exception:
                pass
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Panel BNC"')
        self.end_headers()
        return False

    def _json(self, datos, codigo=HTTPStatus.OK) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self) -> None:
        if not self._autorizado():
            return
        rutas = {"/api/estado": estado_general, "/api/cuentas": cuentas_publicas, "/api/ajustes": ajustes_publicos}
        if self.path in rutas:
            return self._json(rutas[self.path]())
        if self.path in ("/", "/index.html"):
            cuerpo = PAGINA.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return
        self._json({"error": "No existe"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._autorizado():
            return
        # Protección contra sitios web que intenten mandar órdenes a este panel
        if self.headers.get("X-Panel") != "1" or "application/json" not in self.headers.get("Content-Type", ""):
            return self._json({"error": "Solicitud rechazada"}, HTTPStatus.FORBIDDEN)
        try:
            largo = int(self.headers.get("Content-Length", "0"))
            datos = json.loads(self.rfile.read(largo) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "Datos inválidos"}, HTTPStatus.BAD_REQUEST)
        acciones = {
            "/api/encender": lambda: (BOT.encender(bool(datos.get("solo_binance"))), estado_general())[1],
            "/api/apagar": lambda: (BOT.apagar(bool(datos.get("forzar"))), estado_general())[1],
            "/api/cuentas": lambda: guardar_cuenta(datos),
            "/api/cuentas/activar": lambda: activar_cuenta(str(datos.get("id", ""))),
            "/api/cuentas/borrar": lambda: borrar_cuenta(str(datos.get("id", ""))),
            "/api/ajustes": lambda: guardar_ajustes(datos),
        }
        if self.path not in acciones:
            return self._json({"error": "No existe"}, HTTPStatus.NOT_FOUND)
        try:
            self._json(acciones[self.path]())
        except ValueError as e:
            self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)


def servir(puerto: int = 8765, abrir_navegador: bool = True) -> None:
    os.chdir(RAIZ)
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    url = f"http://127.0.0.1:{puerto}"
    print(f"Panel BNC en {url}  (Ctrl+C para cerrar el panel; el bot se apaga de forma segura)", flush=True)
    if abrir_navegador:
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        BOT.cerrar_al_salir()
