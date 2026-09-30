# -*- coding: utf-8 -*-
"""Construye el instalador de Miauia.

    python herramientas/construir.py --version 1.2.0 --repo usuario/miauia

Deja en dist/ el archivo Miauia-Setup-1.2.0.exe. Funciona en Linux (GitHub Actions)
y en Windows (con NSIS instalado)."""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
BUILD = os.path.join(RAIZ, "build")
APP = os.path.join(BUILD, "app")
DIST = os.path.join(RAIZ, "dist")

ARCHIVOS = [
    "asistente.py", "avisos.py", "boveda.py", "comun.py", "configurar.py", "actualizador.py", "michi.py",
    "michi_arte.py", "notas_app.py", "trabajador.py", "interfaz.html", "michi.json", "requirements.txt",
]


def conseguir_uv():
    """uv.exe (Windows) desde PyPI: sirve para instalar Python y las librerías en la PC del usuario."""
    cache = os.path.join(BUILD, "cache")
    os.makedirs(cache, exist_ok=True)
    listo = os.path.join(cache, "uv.exe")
    if os.path.exists(listo):
        return listo
    subprocess.check_call([sys.executable, "-m", "pip", "download", "uv", "--only-binary=:all:",
                           "--platform", "win_amd64", "--no-deps", "-d", cache])
    rueda = sorted(glob.glob(os.path.join(cache, "uv-*.whl")))[-1]
    with zipfile.ZipFile(rueda) as z:
        nombre = next(n for n in z.namelist() if n.endswith("/uv.exe"))
        with z.open(nombre) as origen, open(listo, "wb") as destino:
            shutil.copyfileobj(origen, destino)
    return listo


def buscar_makensis():
    for c in (shutil.which("makensis"), r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"):
        if c and os.path.exists(c):
            return c
    sys.exit("No encuentro NSIS (makensis). En Windows instálalo desde https://nsis.sourceforge.io")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--repo", default="")
    a = p.parse_args()
    version = a.version.lstrip("vV")

    subprocess.check_call([sys.executable, os.path.join(AQUI, "generar_iconos.py")])
    shutil.rmtree(APP, ignore_errors=True)
    os.makedirs(os.path.join(APP, "instalacion"))
    for nombre in ARCHIVOS:
        shutil.copy2(os.path.join(RAIZ, nombre), os.path.join(APP, nombre))
    shutil.copytree(os.path.join(RAIZ, "recursos"), os.path.join(APP, "recursos"))
    with open(os.path.join(APP, "version.py"), "w", encoding="utf-8") as f:
        f.write(f'# -*- coding: utf-8 -*-\nVERSION = "{version}"\nREPO_GITHUB = "{a.repo}"\n')
    with open(os.path.join(APP, "instalado.txt"), "w", encoding="utf-8") as f:
        f.write("Miauia instalada con el instalador. Tus datos están en %APPDATA%\\Miauia\n")
    # PowerShell 5 necesita BOM para leer bien los acentos
    with open(os.path.join(RAIZ, "instalacion", "preparar.ps1"), encoding="utf-8") as f:
        texto = f.read().replace("\r\n", "\n").replace("\n", "\r\n")
    with open(os.path.join(APP, "instalacion", "preparar.ps1"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(texto)
    shutil.copy2(conseguir_uv(), os.path.join(APP, "instalacion", "uv.exe"))

    os.makedirs(DIST, exist_ok=True)
    salida = os.path.join(DIST, f"Miauia-Setup-{version}.exe")
    subprocess.check_call([buscar_makensis(), "-V2", f"-DVERSION={version}", f"-DAPPDIR={APP}",
                           f"-DRECURSOS={os.path.join(RAIZ, 'recursos')}", f"-DSALIDA={salida}",
                           os.path.join(AQUI, "miauia.nsi")])
    print(f"Instalador listo: {salida} ({os.path.getsize(salida) / 1024 ** 2:.1f} MB)")


if __name__ == "__main__":
    main()
