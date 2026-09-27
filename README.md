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

## Inicio rápido (panel de control)

1. Instala **Python 3.11 o superior** desde https://www.python.org/downloads/. En Windows, marca
   la casilla *Add python.exe to PATH* durante la instalación.
2. Descomprime el ZIP en una carpeta.
3. Abre **`Iniciar Panel BNC.bat`** con doble clic (Windows) o `./iniciar_panel.sh` (macOS/Linux).
   La primera vez instala todo automáticamente; tarda unos minutos.
4. Se abre el panel en tu navegador: **http://127.0.0.1:8765**

### Qué puedes hacer en el panel

- **Control**: encender y apagar el bot, elegir **simulación** o **real** (pide confirmación), encender
  solo la lectura de Binance, ver una lista de lo que falta configurar, el pagado de hoy, las órdenes
  recientes y la actividad en vivo. Al apagar, el bot termina el pago en curso antes de detenerse.
  Si hace falta, aparece el botón **Forzar apagado**.
- **Cuentas BNC**: agregar, editar, borrar y elegir la cuenta **en uso** (usuario, clave, cuenta de
  origen 0191… y preguntas de seguridad). Las claves se guardan solo en tu computadora
  (`data/cuentas.json`) y el panel nunca las vuelve a mostrar.
- **Ajustes**: API de Binance, Telegram (grupo principal y de fallos), correo de códigos, límites y
  una clave opcional para el panel.

El panel solo se abre desde tu computadora (127.0.0.1). Si cierras la ventana del panel, el bot se
apaga de forma segura.

## Instalación manual

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env    # y llénalo
```

## Puesta en marcha por fases

1. **Solo lectura de Binance.** Déjalo correr y confirma que las órdenes llegan bien al grupo:
   `python -m bnc_bot --solo-binance`, o desde el panel con la casilla "solo la lectura de Binance".
2. **Mapear BNC.** Corre `python -m playwright codegen <URL de BNC>`, haz el recorrido a mano
   y copia los selectores en `bnc_bot/bnc/selectores.py`. Mientras quede un `TODO`, el bot no toca BNC.
3. **Simulación** (`SIMULACION=true`): llena todo en BNC y verifica el resumen, pero **no confirma**.
4. **Pagos reales pequeños** con `SIMULACION=false` y `UMBRAL_APROBACION=0` (apruebas cada pago con ✅).
5. **Automático**: sube `UMBRAL_APROBACION` y los pagos por debajo de ese monto salen sin intervención.

## Códigos de BNC por correo (automático)

BNC envía sus códigos al correo. Cuando el banco pide uno (al iniciar sesión, al registrar un beneficiario
o al pagar), el bot:

1. Avisa en el grupo principal: `🔐 BNC pide código… 📧 Buscando el código en el correo…`
2. Revisa tu bandeja por IMAP cada 2 segundos y toma solo el correo de BNC que llegó después de la
   solicitud. Los códigos viejos se ignoran y cada correo se usa una sola vez.
3. Saca el código, lo escribe en BNC y confirma en el grupo sin mostrarlo completo: `📧 Código recibido por correo e ingresado (••••13)`.

Si el correo falla o no llega en 3 minutos, avisa en el **grupo de fallos** y puedes escribir el código a
mano en el grupo principal; gana lo que llegue primero. Las preguntas de seguridad nunca se buscan en el correo.

Configuración en `.env`: `CORREO_USUARIO`, `CORREO_CLAVE` y `CORREO_REMITENTE` (la dirección desde la que
escribe BNC). Con Gmail, `CORREO_CLAVE` debe ser una **contraseña de aplicación** (requiere verificación
en 2 pasos), no tu clave normal. Si el código no se detecta solo, define `CORREO_PATRON`.

## Grupos de Telegram

- **Grupo principal** (`TELEGRAM_CHAT_ID`): flujo normal. Órdenes nuevas, aprobaciones ✅/❌, códigos OTP,
  comprobantes y confirmaciones.
- **Grupo de fallos** (`TELEGRAM_CHAT_ID_FALLOS`): **todo** error va **únicamente** aquí. Eso incluye órdenes
  rechazadas por límites, datos de pago ilegibles, revisiones manuales, pagos que salieron pero no se
  pudieron subir o marcar en Binance, caídas de la sesión BNC y errores del lector.
  Agrega a este grupo el bot de fallos y también el bot Hub, para poder usar los comandos desde ahí.
  Las respuestas salen en el mismo grupo donde escribiste el comando.

## Comandos (en cualquiera de los dos grupos)

- `/estado`: órdenes por estado, total pagado hoy y modo.
- `/reintentar <orden>`: vuelve a encolar una orden en revisión. Se bloquea si ya se pulsó "confirmar" en el banco.
- `/pagada <orden>`: verificaste en el banco que el pago salió; sube el comprobante y marca pagada.
- `/rechazar <orden>`: descarta la orden.
- Cualquier texto que no empiece con `/` responde al código OTP que el bot esté pidiendo.

## Pruebas

```bash
python -m pytest -q
```
