# Bot de pagos automatizados BNC (P2P Binance)

Automatiza el pago por **transferencia** en BNC de las órdenes P2P donde compras USDT en Binance:
lee la orden → registra el beneficiario → transfiere → captura el comprobante → lo sube al chat
de la orden → **marca la orden como pagada**. Todo queda visible en tu grupo de Telegram.

Diseño completo: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md)

## Los bots

| # | Bot | Archivo | Qué hace |
|---|-----|---------|----------|
| 1 | Sesión BNC | `bnc_bot/bnc/session.py` | Inicia sesión (usuario, clave, preguntas, OTP por Telegram) y la mantiene viva |
| 2 | Lector Binance | `bnc_bot/bots.py` → `BotBinance.lector` + `extraccion.py` | Lee órdenes pendientes y extrae titular, cédula, cuenta y monto |
| 3 | Registro | `bnc_bot/bnc/beneficiario.py` | Registra al beneficiario en BNC si no existe |
| 4 | Pago | `bnc_bot/bnc/pago.py` | Llena la transferencia, **verifica monto y cuenta en el resumen** y confirma |
| 5 | Comprobante | `bnc/pago.py` + `BotBinance.subidor` | Captura el recibo, lo publica en el grupo, lo sube al chat de Binance y marca pagada |
| — | Hub | `bots.py` → `Hub` | Botones ✅/❌, códigos OTP y comandos en el grupo |

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env    # y llénalo
```

## Puesta en marcha por fases

1. **Solo lectura de Binance.** Déjalo correr y confirma que las órdenes llegan bien al grupo:
   `python -m bnc_bot --solo-binance`
2. **Mapear BNC.** Corre `python -m playwright codegen <URL de BNC>`, haz el recorrido a mano
   y copia los selectores en `bnc_bot/bnc/selectores.py`. Mientras quede un `TODO`, el bot no toca BNC.
3. **Simulación** (`SIMULACION=true`): llena todo en BNC y verifica el resumen, pero **no confirma**.
4. **Pagos reales pequeños** con `SIMULACION=false` y `UMBRAL_APROBACION=0` (apruebas cada pago con ✅).
5. **Automático**: sube `UMBRAL_APROBACION` y los pagos por debajo de ese monto salen sin intervención.

## Comandos en el grupo

- `/estado`: órdenes por estado, total pagado hoy y modo.
- `/reintentar <orden>`: vuelve a encolar una orden en revisión. Se bloquea si ya se pulsó "confirmar" en el banco.
- `/pagada <orden>`: verificaste en el banco que el pago salió; sube el comprobante y marca pagada.
- `/rechazar <orden>`: descarta la orden.
- Cualquier texto que no empiece con `/` responde al código OTP que el bot esté pidiendo.

## Pruebas

```bash
python -m pytest -q
```
