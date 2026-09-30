# -*- coding: utf-8 -*-
"""Bóveda de credenciales por proyecto.

Las contraseñas (y el usuario, la dirección y la nota de cada credencial) se guardan
cifradas con la protección de datos de Windows (DPAPI): solo tu usuario de Windows, en
esta PC, puede descifrarlas. Si alguien copia el archivo a otra PC, no le sirve.
La IA de Miauia nunca lee la bóveda."""
import base64
import ctypes
import json
import os
import threading
import time
import uuid

import comun

RUTA = os.path.join(comun.DATOS, "boveda.json")
ENTROPIA = b"miauia-boveda-v1"
_cerrojo = threading.Lock()


# ---------------------------------------------------------------- cifrado (Windows DPAPI)

if os.name == "nt":
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _a_blob(datos):
        buf = ctypes.create_string_buffer(datos, len(datos))
        return _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _cifrar(datos: bytes) -> bytes:
        entrada, _b1 = _a_blob(datos)
        extra, _b2 = _a_blob(ENTROPIA)
        salida = _BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), "Miauia", ctypes.byref(extra),
                                                       None, None, 0x1, ctypes.byref(salida)):
            raise OSError("Windows no pudo cifrar la credencial")
        try:
            return ctypes.string_at(salida.pbData, salida.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(salida.pbData)

    def _descifrar(datos: bytes) -> bytes:
        entrada, _b1 = _a_blob(datos)
        extra, _b2 = _a_blob(ENTROPIA)
        salida = _BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(extra),
                                                         None, None, 0x1, ctypes.byref(salida)):
            raise OSError("No se pudo descifrar (¿otra PC u otro usuario de Windows?)")
        try:
            return ctypes.string_at(salida.pbData, salida.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(salida.pbData)
    CIFRADO_REAL = True
else:  # solo para pruebas fuera de Windows
    def _cifrar(datos: bytes) -> bytes:
        return b"PRUEBA:" + datos

    def _descifrar(datos: bytes) -> bytes:
        return datos[len(b"PRUEBA:"):]
    CIFRADO_REAL = False


def _sellar(secreto: dict) -> str:
    return base64.b64encode(_cifrar(json.dumps(secreto, ensure_ascii=False).encode("utf-8"))).decode("ascii")


def _abrir(texto: str) -> dict:
    return json.loads(_descifrar(base64.b64decode(texto)).decode("utf-8"))


# ---------------------------------------------------------------- archivo

def _leer():
    try:
        with open(RUTA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": 1, "entradas": []}


def _guardar(datos):
    comun.asegurar_carpetas()
    temporal = RUTA + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(temporal, RUTA)


# ---------------------------------------------------------------- uso

def listar(proyecto):
    """Credenciales del proyecto SIN la contraseña (solo si hay una)."""
    lista = []
    for e in _leer()["entradas"]:
        if e.get("proyecto") != proyecto:
            continue
        try:
            s = _abrir(e["secreto"])
        except Exception:
            s = {"usuario": "", "url": "", "nota": "", "clave": None, "error": True}
        lista.append({"id": e["id"], "nombre": e.get("nombre", ""), "usuario": s.get("usuario", ""),
                      "url": s.get("url", ""), "nota": s.get("nota", ""), "tiene_clave": bool(s.get("clave")),
                      "actualizado": e.get("actualizado", ""), "error": bool(s.get("error"))})
    lista.sort(key=lambda x: x["nombre"].lower())
    return lista


def revelar(id_):
    for e in _leer()["entradas"]:
        if e["id"] == id_:
            return _abrir(e["secreto"]).get("clave", "")
    return None


def dato(id_, campo):
    for e in _leer()["entradas"]:
        if e["id"] == id_:
            return _abrir(e["secreto"]).get(campo, "")
    return None


def guardar(entrada):
    """entrada: {id?, proyecto, nombre, usuario, clave, url, nota}. Si 'clave' es None, se conserva la anterior."""
    with _cerrojo:
        datos = _leer()
        previo = next((e for e in datos["entradas"] if e["id"] == entrada.get("id")), None)
        clave = entrada.get("clave")
        if clave is None and previo:
            clave = _abrir(previo["secreto"]).get("clave", "")
        secreto = {"usuario": (entrada.get("usuario") or "").strip(), "clave": clave or "",
                   "url": (entrada.get("url") or "").strip(), "nota": (entrada.get("nota") or "").strip()}
        nueva = {"id": entrada.get("id") or uuid.uuid4().hex[:12], "proyecto": entrada["proyecto"],
                 "nombre": (entrada.get("nombre") or "Sin nombre").strip()[:80],
                 "actualizado": time.strftime("%Y-%m-%d %H:%M"), "secreto": _sellar(secreto)}
        datos["entradas"] = [e for e in datos["entradas"] if e["id"] != nueva["id"]] + [nueva]
        _guardar(datos)
        return nueva["id"]


def borrar(id_):
    with _cerrojo:
        datos = _leer()
        datos["entradas"] = [e for e in datos["entradas"] if e["id"] != id_]
        _guardar(datos)


def renombrar_proyecto(viejo, nuevo):
    with _cerrojo:
        datos = _leer()
        for e in datos["entradas"]:
            if e.get("proyecto") == viejo:
                e["proyecto"] = nuevo
        _guardar(datos)


def borrar_proyecto(nombre):
    with _cerrojo:
        datos = _leer()
        datos["entradas"] = [e for e in datos["entradas"] if e.get("proyecto") != nombre]
        _guardar(datos)


# ---------------------------------------------------------------- portapapeles con borrado automático

def copiar(texto, segundos=30):
    """Copia al portapapeles de Windows y, pasados unos segundos, lo borra si sigue ahí."""
    if os.name != "nt":
        return False
    if not _poner_portapapeles(texto):
        return False

    def limpiar():
        time.sleep(segundos)
        if _leer_portapapeles() == texto:
            _poner_portapapeles("")
    threading.Thread(target=limpiar, daemon=True).start()
    return True


def _abrir_portapapeles():
    u = ctypes.windll.user32
    for _ in range(20):
        if u.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False


def _poner_portapapeles(texto):
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    if not _abrir_portapapeles():
        return False
    try:
        u.EmptyClipboard()
        if not texto:
            return True
        datos = (texto + "\0").encode("utf-16-le")
        h = k.GlobalAlloc(0x0042, len(datos))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        p = k.GlobalLock(h)
        ctypes.memmove(p, datos, len(datos))
        k.GlobalUnlock(h)
        u.SetClipboardData(13, h)  # CF_UNICODETEXT
        return True
    finally:
        u.CloseClipboard()


def _leer_portapapeles():
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not _abrir_portapapeles():
        return None
    try:
        h = u.GetClipboardData(13)
        if not h:
            return ""
        p = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()
