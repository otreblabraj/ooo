"""Bot 3: registra (o encuentra) al beneficiario en BNC."""
from __future__ import annotations

from typing import Awaitable, Callable

from playwright.async_api import Page

from ..extraccion import DatosPago
from ..venezuela import CODIGO_BNC
from . import selectores as S
from .session import escribir, existe, pausa_humana


async def elegir(page: Page, selector: str, valor: str, etiqueta: str) -> None:
    """Selecciona una opción de un <select> por value y, si no existe, por texto visible."""
    campo = page.locator(selector)
    try:
        await campo.select_option(value=valor, timeout=3000)
    except Exception:
        await campo.select_option(label=etiqueta)
    await pausa_humana()


async def asegurar_beneficiario(
    page: Page, datos: DatosPago, pedir_otp: Callable[[str], Awaitable[str]]
) -> bool:
    """Devuelve True si hubo que registrarlo, False si ya existía en BNC."""
    B = S.BENEFICIARIO
    await page.locator(B["ir_a_beneficiarios"]).click()
    await pausa_humana(1, 2)

    await escribir(page, B["buscar"], datos.cuenta)
    if await existe(page, B["resultado"], 3000):
        return False

    await page.locator(B["boton_nuevo"]).click()
    await pausa_humana(1, 2)
    mismo_banco = datos.cuenta.startswith(CODIGO_BNC)
    await elegir(page, B["tipo_transferencia"], "mismo" if mismo_banco else "otros",
                 "Mismo banco" if mismo_banco else "Otros bancos")
    if not mismo_banco:
        await elegir(page, B["banco"], datos.cuenta[:4], datos.banco)
    await escribir(page, B["cuenta"], datos.cuenta)
    await elegir(page, B["tipo_documento"], datos.cedula[0], datos.cedula[0])
    await escribir(page, B["numero_documento"], datos.cedula[1:])
    await escribir(page, B["titular"], datos.titular[:40])
    if await existe(page, B["alias"]):
        await escribir(page, B["alias"], f"P2P {datos.titular.split()[0]} {datos.cuenta[-4:]}")
    await page.locator(B["guardar"]).click()

    if await existe(page, B["otp_input"], 4000):
        codigo = await pedir_otp(f"🔐 BNC pide código para REGISTRAR a {datos.titular} (…{datos.cuenta[-4:]})")
        await escribir(page, B["otp_input"], codigo)
        await page.locator(B["otp_boton"]).click()

    if not await existe(page, B["exito"], 15000):
        raise RuntimeError("BNC no confirmó el registro del beneficiario")
    return True
