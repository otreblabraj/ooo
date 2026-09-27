"""Bot 4 y Bot 5: ejecuta la transferencia en BNC y captura el comprobante."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import Page

from ..extraccion import DatosPago
from ..venezuela import DatoInvalido, formato_bs, parse_monto
from . import selectores as S
from .beneficiario import elegir
from .session import escribir, existe, pausa_humana

COMPROBANTES = Path("data/comprobantes")


class ResumenNoCoincide(RuntimeError):
    """El resumen de BNC no coincide con la orden: NO se confirmó nada."""


class ErrorTrasConfirmar(RuntimeError):
    """Falló algo DESPUÉS de pulsar confirmar: el dinero pudo haber salido."""


@dataclass
class ResultadoPago:
    comprobante: Path | None
    referencia: str
    simulado: bool


async def llenar_transferencia(page: Page, datos: DatosPago, cuenta_origen: str) -> None:
    """Bot 4 (parte 1): llena el formulario hasta la pantalla de resumen. No mueve dinero."""
    P = S.PAGO
    await page.locator(P["ir_a_transferir"]).click()
    await pausa_humana(1, 2)
    await elegir(page, P["cuenta_origen"], cuenta_origen, cuenta_origen[-4:])
    await elegir(page, P["beneficiario"], datos.cuenta, datos.cuenta[-4:])
    await escribir(page, P["monto"], formato_bs(datos.monto))
    await escribir(page, P["concepto"], f"P2P {datos.order_no[-8:]}")
    await page.locator(P["continuar"]).click()
    await pausa_humana(1, 2)


async def verificar_resumen(page: Page, datos: DatosPago) -> None:
    """Lee la pantalla de resumen y exige que monto y cuenta coincidan con la orden."""
    P = S.PAGO
    texto_monto = await page.locator(P["resumen_monto"]).inner_text()
    texto_cuenta = await page.locator(P["resumen_cuenta"]).inner_text()
    try:
        monto_bnc = parse_monto(texto_monto)
    except DatoInvalido as e:
        raise ResumenNoCoincide(f"No se pudo leer el monto del resumen: {texto_monto!r}") from e
    if monto_bnc != datos.monto:
        raise ResumenNoCoincide(f"Monto en BNC {monto_bnc} ≠ orden {datos.monto}")
    if datos.cuenta[-4:] not in re.sub(r"\D", "", texto_cuenta):
        raise ResumenNoCoincide(f"Cuenta en BNC {texto_cuenta!r} no termina en {datos.cuenta[-4:]}")


async def confirmar_y_capturar(
    page: Page, datos: DatosPago, pedir_otp: Callable[[str], Awaitable[str]]
) -> ResultadoPago:
    """Bot 4 (parte 2) + Bot 5: confirma, espera el recibo y le toma captura."""
    P = S.PAGO
    await page.locator(P["confirmar"]).click()
    try:
        if await existe(page, P["otp_input"], 5000):
            codigo = await pedir_otp(
                f"🔐 BNC pide código para PAGAR {formato_bs(datos.monto)} Bs a {datos.titular}")
            await escribir(page, P["otp_input"], codigo)
            await page.locator(P["otp_boton"]).click()

        recibo = page.locator(P["comprobante"])
        await recibo.wait_for(state="visible", timeout=30000)
        referencia = ""
        if await existe(page, P["referencia"]):
            referencia = re.sub(r"\D", "", await page.locator(P["referencia"]).inner_text())
        COMPROBANTES.mkdir(parents=True, exist_ok=True)
        archivo = COMPROBANTES / f"{datos.order_no}.png"
        await recibo.screenshot(path=str(archivo))
        return ResultadoPago(archivo, referencia, simulado=False)
    except Exception as e:
        raise ErrorTrasConfirmar(str(e)) from e
