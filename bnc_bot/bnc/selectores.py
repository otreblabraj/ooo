"""Selectores de la banca en línea de BNC.

⚠️  Aún NO están mapeados: hay que sacarlos de las pantallas reales de BNC con tu sesión.
Para mapearlos corre:

    python -m playwright codegen https://personas.bncenlinea.com

Haz el recorrido a mano (login → registrar beneficiario → transferir) y copia aquí
los selectores que genera. Mientras quede algún "TODO", el bot se niega a operar en BNC.
"""

LOGIN = {
    "usuario": "TODO",            # input del usuario
    "boton_continuar": "TODO",    # algunos bancos piden usuario y luego clave en otra pantalla
    "clave": "TODO",              # input de la clave
    "boton_entrar": "TODO",
    "pregunta_texto": "TODO",     # texto de la pregunta de seguridad (si BNC la pide)
    "pregunta_input": "TODO",
    "pregunta_boton": "TODO",
    "otp_input": "TODO",          # código SMS / token (si lo pide al entrar)
    "otp_boton": "TODO",
    "sesion_activa": "TODO",      # elemento que SOLO existe con la sesión iniciada (ej. menú, nombre)
}

BENEFICIARIO = {
    "ir_a_beneficiarios": "TODO",   # menú: Transferencias > Beneficiarios / Directorio
    "buscar": "TODO",               # input para buscar por cuenta
    "resultado": "TODO",            # fila que aparece si el beneficiario existe
    "boton_nuevo": "TODO",
    "tipo_transferencia": "TODO",   # select: mismo banco / otros bancos
    "banco": "TODO",                # select del banco destino
    "cuenta": "TODO",
    "tipo_documento": "TODO",       # select V/E/J/P/G
    "numero_documento": "TODO",
    "titular": "TODO",
    "alias": "TODO",
    "guardar": "TODO",
    "otp_input": "TODO",            # si BNC pide clave especial/OTP para registrar
    "otp_boton": "TODO",
    "exito": "TODO",                # mensaje de beneficiario registrado
}

PAGO = {
    "ir_a_transferir": "TODO",
    "cuenta_origen": "TODO",        # select de tu cuenta
    "beneficiario": "TODO",         # select/buscador del beneficiario registrado
    "monto": "TODO",
    "concepto": "TODO",
    "continuar": "TODO",
    # Pantalla de resumen: se leen para verificar ANTES de confirmar
    "resumen_monto": "TODO",
    "resumen_cuenta": "TODO",
    "confirmar": "TODO",
    "otp_input": "TODO",            # clave de operaciones especiales / token / SMS
    "otp_boton": "TODO",
    # Pantalla final
    "comprobante": "TODO",          # contenedor del recibo (se le toma captura solo a este bloque)
    "referencia": "TODO",           # número de referencia de la operación
}


def faltantes() -> list[str]:
    out = []
    for grupo, sel in (("LOGIN", LOGIN), ("BENEFICIARIO", BENEFICIARIO), ("PAGO", PAGO)):
        out += [f"{grupo}.{k}" for k, v in sel.items() if v == "TODO"]
    return out
