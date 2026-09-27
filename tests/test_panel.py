import pytest
from dotenv import dotenv_values

from bnc_bot.panel import envfile, servidor


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "DATA", tmp_path)
    monkeypatch.setattr(servidor, "CUENTAS", tmp_path / "cuentas.json")
    monkeypatch.setattr(servidor, "ENV", tmp_path / ".env")
    return tmp_path


def test_envfile_conserva_comentarios_y_cita(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# Binance\nBINANCE_API_KEY=viejo\nOTRA=1\n", encoding="utf-8")
    envfile.actualizar(env, {"BINANCE_API_KEY": "nuevo", "BNC_PREGUNTAS": 'mascota=Luna "la gata";ciudad=Valencia'})
    texto = env.read_text(encoding="utf-8")
    assert texto.startswith("# Binance\nBINANCE_API_KEY=nuevo\nOTRA=1\n")
    assert dotenv_values(env)["BNC_PREGUNTAS"] == 'mascota=Luna "la gata";ciudad=Valencia'


def test_cuentas_validacion_y_secretos(rutas):
    with pytest.raises(ValueError, match="0191"):
        servidor.guardar_cuenta({"alias": "A", "usuario": "u", "clave": "c", "cuenta_origen": "0134" + "0" * 16})
    with pytest.raises(ValueError, match="clave"):
        servidor.guardar_cuenta({"alias": "A", "usuario": "u", "cuenta_origen": "0191" + "0" * 16})
    pub = servidor.guardar_cuenta({"alias": "A", "usuario": "u", "clave": "secreta",
                                   "cuenta_origen": "0191" + "1" * 16, "preguntas": "p=r"})
    assert "secreta" not in str(pub) and pub["cuentas"][0]["tiene_clave"]
    id_ = pub["activa"]
    # Editar sin clave conserva la anterior
    servidor.guardar_cuenta({"id": id_, "alias": "B", "usuario": "u2", "cuenta_origen": "0191" + "1" * 16})
    assert servidor.cuenta_activa()["clave"] == "secreta"
    assert servidor.cuenta_activa()["preguntas"] == "p=r"
    b = servidor.guardar_cuenta({"alias": "C", "usuario": "x", "clave": "k", "cuenta_origen": "0191" + "2" * 16})
    otra = [c for c in b["cuentas"] if c["alias"] == "C"][0]["id"]
    servidor.activar_cuenta(otra)
    assert servidor.cuenta_activa()["alias"] == "C"
    servidor.borrar_cuenta(otra)
    assert servidor.cuenta_activa()["alias"] == "B"


def test_ajustes_secretos_vacios_no_borran(rutas):
    servidor.guardar_ajustes({"BINANCE_API_KEY": "abc", "MONTO_MAX_ORDEN": "1000", "NO_PERMITIDA": "x"})
    servidor.guardar_ajustes({"BINANCE_API_KEY": "", "SIMULACION": False})
    v = dotenv_values(rutas / ".env")
    assert v["BINANCE_API_KEY"] == "abc" and v["SIMULACION"] == "false" and "NO_PERMITIDA" not in v
    pub = servidor.ajustes_publicos()
    assert all(c["valor"] == "" for c in pub["campos"] if c["tipo"] == "secreto")
    with pytest.raises(ValueError):
        servidor.guardar_ajustes({"MONTO_MAX_DIA": "mucho"})
