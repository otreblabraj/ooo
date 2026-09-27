@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Panel BNC

if not exist ".venv\listo.txt" (
  echo Preparando el bot por primera vez. Tarda unos minutos...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo No se encontro Python. Instala Python 3.11 o superior desde https://www.python.org/downloads/
    echo y marca la casilla "Add python.exe to PATH". Luego vuelve a abrir este archivo.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Fallo la instalacion. Revisa tu conexion a internet. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m playwright install chromium || (echo Fallo la descarga del navegador. & pause & exit /b 1)
  echo ok> ".venv\listo.txt"
)

if not exist ".env" copy ".env.example" ".env" >nul

echo Abriendo el panel en tu navegador: http://127.0.0.1:8765
echo Deja esta ventana abierta mientras uses el bot. Para cerrar: Ctrl+C
".venv\Scripts\python.exe" -m bnc_bot.panel
pause
