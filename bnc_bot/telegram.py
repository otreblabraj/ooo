"""Cliente mínimo de la Bot API de Telegram (sin frameworks).

El grupo de Telegram es la bitácora visible y el panel de control:
  • cada bot publica ahí lo que hace (datos, estado, comprobante);
  • tú apruebas/rechazas pagos con botones y envías los códigos OTP de BNC.

Nota: Telegram NO entrega a un bot los mensajes que envía otro bot en un grupo.
Por eso la coordinación real entre bots va por la base de datos (db.py) y el grupo
queda como vista humana del proceso.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

import httpx


class Telegram:
    def __init__(self, token: str, chat_id: str, cliente: httpx.AsyncClient | None = None,
                 nunca_falla: bool = False):
        """`nunca_falla=True` (grupo de fallos): si Telegram falla, se imprime en consola en vez de
        lanzar la excepción, para que un aviso de error no tumbe al bot que lo envía."""
        self._base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self._http = cliente or httpx.AsyncClient(timeout=70)
        self._activo = bool(token and chat_id)
        self._nunca_falla = nunca_falla

    async def _post(self, metodo: str, **kw) -> dict:
        if not self._activo:
            print(f"[telegram desactivado] {metodo}: {kw.get('data') or kw.get('json')}")
            return {}
        try:
            r = await self._http.post(f"{self._base}/{metodo}", **kw)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {metodo}: {data}")
            return data["result"]
        except Exception as e:
            if not self._nunca_falla:
                raise
            print(f"[telegram fallos] no se pudo enviar ({e}): {kw.get('data') or kw.get('json')}")
            return {}

    async def enviar(self, texto: str, botones: list[tuple[str, str]] | None = None) -> dict:
        payload: dict = {"chat_id": self.chat_id, "text": texto, "parse_mode": "HTML"}
        if botones:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in botones]]}
        return await self._post("sendMessage", json=payload)

    async def enviar_foto(self, foto: Path, caption: str = "") -> dict:
        with foto.open("rb") as f:
            return await self._post(
                "sendPhoto",
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": (foto.name, f, "image/png")},
            )

    async def responder_callback(self, callback_id: str, texto: str) -> None:
        await self._post("answerCallbackQuery", json={"callback_query_id": callback_id, "text": texto})

    async def escuchar(
        self,
        admin_id: int,
        on_callback: Callable[[str], Awaitable[str]],
        on_texto: Callable[[str, str], Awaitable[None]],
        chats_extra: tuple[str, ...] = (),
    ) -> None:
        """Long-polling. Solo atiende mensajes/botones del administrador en los grupos configurados.

        `on_texto(texto, chat_id)` recibe también el grupo de origen para responder ahí mismo.
        """
        chats = {str(self.chat_id), *(str(c) for c in chats_extra if c)}
        if not self._activo:
            return
        offset = 0
        while True:
            try:
                r = await self._http.get(
                    f"{self._base}/getUpdates",
                    params={"offset": offset, "timeout": 50,
                            "allowed_updates": json.dumps(["message", "callback_query"])},
                )
                updates = r.json().get("result", [])
            except httpx.HTTPError:
                await asyncio.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                if cb := u.get("callback_query"):
                    if cb["from"]["id"] != admin_id:
                        await self.responder_callback(cb["id"], "No autorizado")
                        continue
                    await self.responder_callback(cb["id"], await on_callback(cb.get("data", "")))
                elif (msg := u.get("message")) and msg.get("text"):
                    chat = str(msg["chat"]["id"])
                    if msg["from"]["id"] == admin_id and chat in chats:
                        await on_texto(msg["text"].strip(), chat)
