# Arquitectura

## Flujo

```
Binance P2P ──(API)──▶ Bot 2 Lector ──▶ SQLite (NUEVA)
                          │                 │ validación
                          ▼                 ▼
                    Grupo Telegram ◀── POR_APROBAR ──✅ tú──▶ APROBADA
                          ▲                                     │
                          │         Bot 1 Sesión BNC ◀──────────┤
                          │         Bot 3 Beneficiario ─────────▶ BENEFICIARIO_OK
                          │         Bot 4 Pago (verifica resumen)─▶ PAGANDO ─▶ PAGADA
                          │── foto ── Bot 5 Comprobante ◀──────────────────────┘
                          │                                                     │
Binance chat ◀── foto ── Bot Binance subidor ◀─────────────────────────────────┘
Binance      ◀── marcar pagada ──────────────────▶ COMPROBANTE_SUBIDO ─▶ COMPLETADA
```

## Por qué la base de datos y no solo el grupo

En un grupo, **Telegram no entrega a un bot los mensajes que publica otro bot**. Además, un mensaje
perdido o un reinicio podría hacer que una orden se pague dos veces o nunca. Por eso:

- **SQLite** es el canal real entre los bots. Cada orden tiene un estado y los cambios son atómicos.
- **Telegram** es la vista humana: cada bot publica ahí con su propio token (puedes crear 4 bots en
  @BotFather para que se vean separados) y ahí apruebas y envías los códigos OTP.

## Grupo de fallos

Los errores no se mezclan con el flujo normal: todo aviso de fallo sale **solo** por el grupo de fallos
(`TELEGRAM_CHAT_ID_FALLOS`), con su propio bot opcional (`TELEGRAM_TOKEN_FALLOS`). Ese envío nunca lanza
excepción: si Telegram falla, el aviso se imprime en la consola y el bot sigue trabajando.

| Va al grupo de fallos | Sigue en el grupo principal |
|---|---|
| 🚫 Orden rechazada por límites | 📥 Orden nueva / por aprobar |
| ⚠️ No se pudieron leer los datos de pago | ✅ ❌ Aprobaciones |
| ⚠️ / 🆘 Revisión manual (antes o después de confirmar) | 🔐 Pedidos de OTP |
| 🆘 Pago hecho pero no subido/marcado en Binance | 📝 Beneficiario registrado |
| ⚠️ Error del lector Binance / keep-alive BNC | 🧾 Comprobante y 🏁 orden completada |
| 💥 Caída general de los bots | 🧪 Resultado de simulación |

## Estados

| Estado | Significado |
|---|---|
| NUEVA | Detectada en Binance |
| POR_APROBAR | Esperando tu ✅ (monto sobre el umbral o nombre que no coincide) |
| APROBADA | En cola para BNC |
| BENEFICIARIO_OK | Beneficiario registrado |
| PAGANDO | Se pulsó "confirmar" en BNC (desde aquí **nunca** se reintenta sola) |
| PAGADA | Transferencia hecha y comprobante capturado |
| COMPROBANTE_SUBIDO | Foto en el chat de la orden |
| COMPLETADA | Orden marcada como pagada en Binance |
| REVISION_MANUAL | Algo salió mal; te avisa en el grupo |
| RECHAZADA | No se paga |

## Controles de seguridad

1. **Sin pagos dobles.** El número de orden es la clave única; `PAGANDO` se registra *antes* de confirmar
   y `/reintentar` se bloquea si la orden llegó a `PAGANDO`.
2. **Antitriangulación.** Si el nombre KYC del vendedor en Binance no coincide con el titular de la cuenta,
   se pide tu aprobación.
3. **Verificación del resumen.** Antes de confirmar, se leen el monto y la cuenta en la pantalla de BNC;
   si no coinciden con la orden, no se confirma.
4. **La orden sigue vigente.** Justo antes de pagar se consulta Binance; si la orden fue cancelada o expiró, no se paga.
5. **Límites** por orden y por día, y **umbral** de aprobación manual.
6. **Modo simulación** activado por defecto.
7. **Solo tú** (TELEGRAM_ADMIN_ID) puedes aprobar, enviar códigos o usar comandos.
8. La API Key de Binance debe tener **solo lectura + C2C**, sin retiros, y estar restringida por IP.

## Pendientes a validar con datos reales

- **Endpoints de comerciante de Binance** (`binance_client.RUTAS`): detalle de orden, subida de imagen al
  chat y marcar pagada. La documentación pública solo cubre el historial; verificar rutas y nombres de
  campos con tu cuenta oro. El primer paso de la fase 1 es imprimir el JSON real de una orden.
- **Selectores de BNC** (`bnc/selectores.py`): mapearlos con `playwright codegen`.
- **Factores de seguridad de BNC**: qué pide al entrar, al registrar y al pagar (SMS, token, preguntas).
- La automatización de la banca en línea puede ir contra los términos de BNC; el bot escribe con pausas
  "humanas", usa un perfil de navegador persistente y una sola sesión.
