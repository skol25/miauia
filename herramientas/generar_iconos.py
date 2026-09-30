# -*- coding: utf-8 -*-
"""Genera los íconos de Miauia (huella rosita) a partir del pixel art de michi.py."""
import os
import sys

from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)

from michi_arte import icono_huella as icono  # noqa: E402


if __name__ == "__main__":
    destino = os.path.join(RAIZ, "recursos")
    os.makedirs(destino, exist_ok=True)
    tamanos = [16, 24, 32, 48, 64, 128, 256]
    imgs = [icono("rosa", t) for t in tamanos]
    imgs[-1].save(os.path.join(destino, "miauia.ico"), sizes=[(t, t) for t in tamanos], append_images=imgs[:-1])
    icono("rosa", 256).save(os.path.join(destino, "miauia.png"))
    # imagen lateral del instalador (164x314) y cabecera (150x57), formato BMP
    lateral = Image.new("RGBA", (164, 314), (31, 33, 36, 255))
    lateral.alpha_composite(icono("rosa", 120), (22, 60))
    lateral.convert("RGB").save(os.path.join(destino, "instalador_lateral.bmp"))
    cabecera = Image.new("RGBA", (150, 57), (255, 255, 255, 255))
    cabecera.alpha_composite(icono("rosa", 48), (96, 4))
    cabecera.convert("RGB").save(os.path.join(destino, "instalador_cabecera.bmp"))
    print("Íconos listos en", destino)
