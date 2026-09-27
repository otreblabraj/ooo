"""python -m bnc_bot.panel [--puerto 8765] [--sin-navegador]"""
import argparse
import os

from dotenv import load_dotenv

from .servidor import ENV, servir

load_dotenv(ENV)
ap = argparse.ArgumentParser()
ap.add_argument("--puerto", type=int, default=int(os.getenv("PANEL_PUERTO", "8765")))
ap.add_argument("--sin-navegador", action="store_true")
a = ap.parse_args()
servir(a.puerto, abrir_navegador=not a.sin_navegador)
