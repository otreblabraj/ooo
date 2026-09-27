"""Cliente de la API C2C (P2P) de Binance.

⚠️  IMPORTANTE: la API pública documentada de C2C solo trae `listUserOrderHistory`.
El detalle de orden, el chat (subir foto) y "marcar como pagado" son endpoints SAPI
de comerciante. Las rutas de abajo son las conocidas para cuentas de comerciante, pero
DEBEN verificarse contra la documentación que Binance te dé para tu nivel (oro).
Por eso todas están centralizadas en `RUTAS` para cambiarlas en un solo sitio.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

RUTAS = {
    "historial": ("GET", "/sapi/v1/c2c/orderMatch/listUserOrderHistory"),
    "listar_ordenes": ("POST", "/sapi/v1/c2c/orderMatch/listOrders"),
    "detalle": ("POST", "/sapi/v1/c2c/orderMatch/getUserOrderDetail"),
    "marcar_pagada": ("POST", "/sapi/v1/c2c/orderMatch/markOrderAsPaid"),
    "chat_credencial": ("GET", "/sapi/v1/c2c/chat/retrieveChatCredential"),
    "chat_presigned": ("POST", "/sapi/v1/c2c/chat/image/pre-signed-url"),
}

# Estado de una orden sin pagar todavía (el comprador aún no transfirió)
ESTADO_SIN_PAGAR = "TRADING"


class BinanceError(RuntimeError):
    pass


def firmar(secret: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BinanceC2C:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.binance.com",
                 cliente: httpx.AsyncClient | None = None):
        self._key = api_key
        self._secret = api_secret
        self._http = cliente or httpx.AsyncClient(base_url=base_url, timeout=20)

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def _llamar(self, nombre: str, query: dict | None = None, body: dict | None = None) -> Any:
        metodo, ruta = RUTAS[nombre]
        params = {**(query or {}), "timestamp": int(time.time() * 1000), "recvWindow": 10000}
        params["signature"] = firmar(self._secret, params)
        r = await self._http.request(
            metodo, ruta, params=params, json=body,
            headers={"X-MBX-APIKEY": self._key, "clientType": "web"},
        )
        try:
            data = r.json()
        except json.JSONDecodeError:
            raise BinanceError(f"{nombre}: HTTP {r.status_code} {r.text[:200]}")
        if r.status_code != 200 or (isinstance(data, dict) and data.get("success") is False):
            raise BinanceError(f"{nombre}: HTTP {r.status_code} {data}")
        return data.get("data", data) if isinstance(data, dict) else data

    # ─── lectura ───
    async def ordenes_compra_pendientes(self, fiat: str) -> list[dict]:
        """Órdenes donde tú COMPRAS cripto y todavía debes transferir los bolívares."""
        data = await self._llamar("listar_ordenes", body={
            "page": 1, "rows": 50, "tradeType": "BUY", "orderStatusList": [1],  # 1 = TRADING
        })
        filas = data if isinstance(data, list) else data.get("list", [])
        return [o for o in filas if o.get("fiat", fiat) == fiat and
                str(o.get("orderStatus", ESTADO_SIN_PAGAR)).upper() in {ESTADO_SIN_PAGAR, "1"}]

    async def detalle(self, order_no: str) -> dict:
        return await self._llamar("detalle", body={"adOrderNo": order_no})

    # ─── escritura ───
    async def marcar_pagada(self, order_no: str, pay_id: str | int) -> None:
        await self._llamar("marcar_pagada", body={"orderNumber": order_no, "payId": int(pay_id)})

    async def subir_imagen_chat(self, order_no: str, imagen: Path) -> None:
        """Sube la imagen al almacenamiento de Binance y la envía al chat de la orden."""
        nombre = f"{order_no}_{uuid.uuid4().hex[:8]}.png"
        pre = await self._llamar("chat_presigned", body={"imageName": nombre})
        upload_url, image_url = pre["uploadUrl"], pre["imageUrl"]
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(upload_url, content=imagen.read_bytes(), headers={"Content-Type": "image/png"})
            r.raise_for_status()
        await self._enviar_mensaje_chat(order_no, {"type": "image", "imageUrl": image_url})

    async def _enviar_mensaje_chat(self, order_no: str, contenido: dict) -> None:
        import websockets

        cred = await self._llamar("chat_credencial")
        url = f"{cred['chatWssUrl']}/{cred['listenKey']}?token={cred['listenToken']}&clientType=web"
        mensaje = {
            **contenido,
            "uuid": str(uuid.uuid4()),
            "orderNo": order_no,
            "content": contenido.get("imageUrl", contenido.get("content", "")),
            "self": True,
            "clientType": "web",
            "createTime": int(time.time() * 1000),
            "sendStatus": 0,
        }
        async with websockets.connect(url, open_timeout=20) as ws:
            await ws.send(json.dumps(mensaje))
