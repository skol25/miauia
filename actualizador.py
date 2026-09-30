# -*- coding: utf-8 -*-
"""Actualizaciones de Miauia desde GitHub Releases.

Cada versión publicada en GitHub trae un instalador "Miauia-Setup-X.Y.Z.exe". Miauia
revisa de vez en cuando si hay una versión más nueva y, si le das a "Actualizar",
descarga el instalador y lo ejecuta en silencio. Tus notas no se tocan: viven en
%APPDATA%\\Miauia, separadas del programa."""
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

import comun
import version

log = comun.configurar_registro("actualizador")
CACHE = os.path.join(comun.DATOS, "actualizacion.json")
CADA = 6 * 3600  # revisar como mucho cada 6 horas


def _tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3]) or (0,)


def activo():
    import michi_arte
    return bool(version.REPO_GITHUB) and michi_arte.instalado()


def buscar(forzar=False):
    """Devuelve {"hay": bool, "version", "url", "notas", "tamano"} o None si no se pudo revisar."""
    if not version.REPO_GITHUB:
        return {"hay": False, "actual": version.VERSION, "motivo": "sin_repo"}
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if not forzar and time.time() - cache.get("revisado", 0) < CADA:
            cache["hay"] = _tupla(cache.get("version")) > _tupla(version.VERSION)
            cache["actual"] = version.VERSION
            return cache
    except Exception:
        pass
    url = f"https://api.github.com/repos/{version.REPO_GITHUB}/releases/latest"
    try:
        pet = urllib.request.Request(url, headers={"User-Agent": "Miauia", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(pet, timeout=15) as r:
            datos = json.load(r)
    except Exception as e:
        log.warning("No se pudo revisar actualizaciones: %s", e)
        return None
    instalador = next((a for a in datos.get("assets", []) if a["name"].lower().endswith(".exe")), None)
    info = {
        "version": (datos.get("tag_name") or "").lstrip("vV"),
        "url": instalador["browser_download_url"] if instalador else "",
        "tamano": instalador["size"] if instalador else 0,
        "notas": (datos.get("body") or "")[:2000],
        "revisado": time.time(),
    }
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
    except Exception:
        pass
    info["hay"] = bool(info["url"]) and _tupla(info["version"]) > _tupla(version.VERSION)
    info["actual"] = version.VERSION
    return info


ESTADO = {"fase": "", "progreso": 0.0, "error": ""}


def instalar(info, al_terminar_descarga=None):
    """Descarga el instalador nuevo y lo ejecuta en silencio (/S). El instalador cierra
    Miauia, actualiza el programa y lo vuelve a abrir."""
    try:
        ESTADO.update(fase="descargando", progreso=0.0, error="")
        destino = os.path.join(tempfile.gettempdir(), f"Miauia-Setup-{info['version']}.exe")
        pet = urllib.request.Request(info["url"], headers={"User-Agent": "Miauia"})
        with urllib.request.urlopen(pet, timeout=60) as r, open(destino, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.get("tamano") or 0)
            hecho = 0
            while True:
                trozo = r.read(1024 * 256)
                if not trozo:
                    break
                f.write(trozo)
                hecho += len(trozo)
                if total:
                    ESTADO["progreso"] = hecho / total
        ESTADO.update(fase="instalando", progreso=1.0)
        log.info("Ejecutando instalador %s", destino)
        if al_terminar_descarga:
            al_terminar_descarga()
        subprocess.Popen([destino, "/S", "/ACTUALIZAR"], creationflags=0x00000008 | 0x00000200)  # separado del proceso
        return True
    except Exception as e:
        log.exception("Falló la actualización")
        ESTADO.update(fase="error", error=str(e))
        return False
