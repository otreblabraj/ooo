"""Bot 1: inicio y mantenimiento de la sesión en BNC (Playwright)."""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import BrowserContext, Page, async_playwright

from ..config import Config
from . import selectores as S

PERFIL = Path("data/perfil_bnc")  # perfil persistente: BNC reconoce el equipo


async def pausa_humana(min_s: float = 0.4, max_s: float = 1.2) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def escribir(page: Page, selector: str, texto: str) -> None:
    campo = page.locator(selector)
    await campo.click()
    await campo.fill("")
    await campo.press_sequentially(texto, delay=random.randint(60, 140))
    await pausa_humana()


async def existe(page: Page, selector: str, timeout_ms: int = 1500) -> bool:
    if selector == "TODO":
        return False
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


class SesionBNC:
    """Mantiene UNA sola pestaña abierta con la sesión de BNC."""

    def __init__(self, cfg: Config, pedir_otp: Callable[[str], Awaitable[str]],
                 avisar: Callable[[str], Awaitable[None]]):
        self.cfg = cfg
        self._pedir_otp = pedir_otp
        self._avisar = avisar
        self._pw = None
        self._ctx: BrowserContext | None = None
        self.page: Page | None = None
        self.lock = asyncio.Lock()  # nunca dos operaciones a la vez en el banco

    async def abrir(self) -> None:
        if faltan := S.faltantes():
            raise RuntimeError(f"Selectores BNC sin mapear ({len(faltan)}): {', '.join(faltan[:5])}…")
        PERFIL.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(PERFIL), headless=not self.cfg.bnc_headful, locale="es-VE",
            viewport={"width": 1366, "height": 850},
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()

    async def cerrar(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    async def activa(self) -> bool:
        return self.page is not None and await existe(self.page, S.LOGIN["sesion_activa"])

    async def asegurar(self) -> Page:
        """Devuelve la página con sesión iniciada; si expiró, vuelve a entrar."""
        if self.page is None:
            await self.abrir()
        if not await self.activa():
            await self._login()
        return self.page  # type: ignore[return-value]

    async def _login(self) -> None:
        page = self.page
        assert page is not None
        L = S.LOGIN
        await page.goto(self.cfg.bnc_url, wait_until="domcontentloaded")
        await pausa_humana(1, 2)

        await escribir(page, L["usuario"], self.cfg.bnc_usuario)
        if await existe(page, L["boton_continuar"]):
            await page.locator(L["boton_continuar"]).click()
            await pausa_humana(1, 2)

        # Preguntas de seguridad (pueden venir antes o después de la clave)
        for _ in range(3):
            if not await existe(page, L["pregunta_texto"]):
                break
            pregunta = (await page.locator(L["pregunta_texto"]).inner_text()).strip().lower()
            respuesta = next((r for p, r in self.cfg.bnc_preguntas.items() if p in pregunta), None)
            if respuesta is None:
                respuesta = await self._pedir_otp(f"BNC pregunta: «{pregunta}». Responde en el grupo:")
            await escribir(page, L["pregunta_input"], respuesta)
            await page.locator(L["pregunta_boton"]).click()
            await pausa_humana(1, 2)

        await escribir(page, L["clave"], self.cfg.bnc_clave)
        await page.locator(L["boton_entrar"]).click()
        await pausa_humana(2, 3)

        if await existe(page, L["otp_input"], 4000):
            codigo = await self._pedir_otp("🔐 BNC pide código para INICIAR SESIÓN. Envíalo en el grupo:")
            await escribir(page, L["otp_input"], codigo)
            await page.locator(L["otp_boton"]).click()

        if not await existe(page, L["sesion_activa"], 15000):
            raise RuntimeError("No se pudo iniciar sesión en BNC (revisa credenciales/selectores)")
        await self._avisar("🏦 Sesión BNC iniciada")

    async def mantener_viva(self, cada_segundos: int = 240) -> None:
        """Tarea de fondo: mueve la página cada tanto para que la sesión no expire."""
        while True:
            await asyncio.sleep(cada_segundos)
            async with self.lock:
                try:
                    if self.page and await self.activa():
                        await self.page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                except Exception as e:  # la próxima operación hará login de nuevo
                    await self._avisar(f"⚠️ Keep-alive BNC falló: {e}")
