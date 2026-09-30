# -*- coding: utf-8 -*-
"""App de escritorio para ver y editar las notas. Solo ocupa memoria mientras
está abierta; al cerrarla se libera todo."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import comun

log = comun.configurar_registro("notas")
PUERTO = 47832
SIN_VENTANA = 0x08000000


def _python_consola():
    carpeta = os.path.dirname(sys.executable)
    python = os.path.join(carpeta, "python.exe")
    return python if os.path.exists(python) else sys.executable


def _trabajador(modo, texto, proyecto=""):
    salida = os.path.join(comun.TEMPORAL, f"resultado_app_{time.time_ns()}.json")
    orden = [_python_consola(), os.path.join(comun.BASE, "trabajador.py"),
             "--modo", modo, "--texto", texto, "--salida", salida]
    if proyecto:
        orden += ["--proyecto", proyecto]
    subprocess.run(orden, cwd=comun.BASE, creationflags=SIN_VENTANA if os.name == "nt" else 0,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(salida):
        return {"ok": False, "mensaje": "El asistente no respondió. Revisa datos/registro.log."}
    with open(salida, "r", encoding="utf-8") as f:
        resultado = json.load(f)
    os.remove(salida)
    return resultado


class Api:
    """Funciones que la interfaz puede llamar."""

    def __init__(self):
        self._ventana = None

    def cargar(self):
        comun.asegurar_carpetas()
        cfg = comun.cargar_config()
        return {
            "proyectos": comun.listar_proyectos(),
            "avisos": {k: cfg[k] for k in ("avisar_minutos_antes", "resumen_diario", "sonido_avisos", "voz_avisos")},
            "notas": comun.listar_notas(),
            "reuniones": comun.listar_reuniones(),
            "hoy": f"{comun.ahora():%Y-%m-%d}",
            "fecha_larga": comun.fecha_larga(),
            "firma": self.firma(),
            "atajos": {k: cfg[k] for k in ("atajo_anotar", "atajo_preguntar", "atajo_reunion")},
        }

    def firma(self):
        """Cambia cuando alguien (el asistente o tú) modifica las notas."""
        partes = []
        for ruta in [comun.NOTAS, comun.PROYECTOS] + ([os.path.join(comun.REUNIONES, n) for n in os.listdir(comun.REUNIONES)]
                                     if os.path.isdir(comun.REUNIONES) else []):
            try:
                partes.append(f"{ruta}:{os.path.getmtime(ruta)}")
            except OSError:
                pass
        return str(hash("|".join(sorted(partes))))

    def marcar(self, linea, hecho):
        nota = comun.parsear_linea(linea)
        if not nota:
            return False
        nota["hecho"] = bool(hecho)
        nota["fecha_hecho"] = ""
        if nota["tipo"] not in comun.TIPOS_CON_CASILLA and not hecho:
            nota["tipo"] = "tarea"
        return comun.reemplazar_linea(linea, comun.componer_linea(nota))

    def editar(self, linea, cambios):
        nota = comun.parsear_linea(linea)
        if not nota:
            return False
        for clave in ("texto", "tipo", "fecha", "hora", "proyecto"):
            if clave in cambios:
                nota[clave] = cambios[clave] or ""
        if nota["proyecto"]:
            nota["proyecto"] = comun.asegurar_proyecto(nota["proyecto"])
        if not nota["texto"].strip():
            return False
        return comun.reemplazar_linea(linea, comun.componer_linea(nota))

    def borrar(self, linea):
        return comun.reemplazar_linea(linea, None)

    def agregar(self, tipo, texto, fecha="", hora="", proyecto=""):
        if not (texto or "").strip():
            return False
        comun.agregar_nota(tipo, texto, fecha, hora, proyecto=proyecto)
        return True

    # ---------- proyectos
    def crear_proyecto(self, nombre, descripcion=""):
        return comun.asegurar_proyecto(nombre, descripcion)

    def editar_proyecto(self, viejo, datos):
        lista = comun.listar_proyectos()
        p = next((x for x in lista if x["nombre"] == viejo), None)
        if not p:
            return False
        nuevo = (datos.get("nombre") or viejo).strip()[:40] or viejo
        if nuevo != viejo and comun.buscar_proyecto(nuevo):
            return "Ya existe un proyecto con ese nombre"
        p.update({"nombre": nuevo, "color": datos.get("color") or p["color"],
                  "descripcion": (datos.get("descripcion") or "").strip()[:200]})
        comun.guardar_proyectos(lista)
        if nuevo != viejo:
            comun.cambiar_proyecto_en_notas(viejo, nuevo)
        return True

    def borrar_proyecto(self, nombre):
        comun.guardar_proyectos([x for x in comun.listar_proyectos() if x["nombre"] != nombre])
        comun.cambiar_proyecto_en_notas(nombre, "")
        return True

    # ---------- avisos
    def guardar_avisos(self, datos):
        with open(comun.CONFIG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        cfg["avisar_minutos_antes"] = int(datos.get("avisar_minutos_antes") or 0)
        cfg["resumen_diario"] = comun.limpiar_hora(datos.get("resumen_diario") or "")
        cfg["sonido_avisos"] = bool(datos.get("sonido_avisos"))
        cfg["voz_avisos"] = bool(datos.get("voz_avisos"))
        with open(comun.CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        comun.avisar_asistente("config:recargar")
        return True

    # ---------- versión y actualizaciones
    def version(self):
        import version as v
        return {"version": v.VERSION, "repo": v.REPO_GITHUB}

    def buscar_actualizacion(self, forzar=False):
        import actualizador
        return actualizador.buscar(bool(forzar))

    def instalar_actualizacion(self):
        import actualizador
        info = actualizador.buscar()
        if not info or not info.get("hay"):
            return False
        threading.Thread(target=actualizador.instalar, args=(info,), daemon=True).start()
        return True

    def estado_actualizacion(self):
        import actualizador
        return dict(actualizador.ESTADO)

    def registrar_error(self, texto):
        log.error("Error en la interfaz: %s", str(texto)[:800])
        return True

    def probar_aviso(self):
        comun.avisar_asistente("aviso:prueba")
        return True

    def michi(self):
        import michi_arte
        cfg = comun.cargar_config()
        return {"config": cfg["michi"], "michis": cfg["michis"], "sprites": michi_arte.cargar_sprites(),
                "defecto": michi_arte.MICHI_POR_DEFECTO,
                "estado": michi_arte.estado_michis([m["id"] for m in cfg["michis"]])}

    def guardar_michi(self, cfg):
        limpio = comun.guardar_michi(cfg)
        comun.avisar_asistente("michi:recargar")
        return limpio

    def guardar_michis(self, lista):
        limpios = comun.guardar_michis(lista)
        comun.avisar_asistente("michi:recargar")
        return limpios

    def estado_michis(self):
        import michi_arte
        return michi_arte.estado_michis([m["id"] for m in comun.cargar_config()["michis"]])

    def jugar_afuera(self, tipo):
        """Minimiza la app y juega con los michis en la barra de Windows."""
        if tipo not in ("comida", "premio", "estambre", "guardar"):
            return False
        if self._ventana:
            self._ventana.minimize()
        ESTADO_VENTANA["visible"] = False
        asegurar_asistente()
        time.sleep(0.4)
        comun.avisar_asistente("app:oculta")
        comun.avisar_asistente(f"juego:{tipo}")
        return True

    def cuidar(self, michi_id, accion):
        import michi_arte
        return michi_arte.cuidar(str(michi_id), accion)

    def ordenar_con_ia(self, texto, proyecto=""):
        return _trabajador("nota", texto, proyecto)

    def preguntar(self, texto):
        return _trabajador("pregunta", texto)

    def abrir(self, que):
        if que == "notas":
            subprocess.Popen(["notepad.exe", comun.NOTAS])
        elif que.endswith(".md"):
            subprocess.Popen(["notepad.exe", os.path.join(comun.REUNIONES, os.path.basename(que))])
        else:
            os.startfile(comun.REUNIONES)


def escuchar_segunda_apertura(api):
    """Si ya está abierta y la abres otra vez, traemos la ventana al frente."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.bind(("127.0.0.1", PUERTO))
    except OSError:
        return None
    servidor.listen(2)

    def bucle():
        while True:
            try:
                conexion, _ = servidor.accept()
                with conexion:
                    conexion.settimeout(1)
                    try:
                        texto = conexion.recv(128).decode("utf-8", "ignore")
                    except OSError:
                        texto = ""
                if api._ventana and texto.startswith("vista:"):
                    api._ventana.evaluate_js(f"irA({json.dumps(texto[6:])})")
                if api._ventana:
                    api._ventana.restore()
                    api._ventana.show()
                    api._ventana.on_top = True
                    api._ventana.on_top = False
            except Exception:
                log.exception("Error trayendo la ventana al frente")

    threading.Thread(target=bucle, daemon=True).start()
    return servidor


def asistente_vivo():
    try:
        socket.create_connection(("127.0.0.1", 47831), timeout=1).close()
        return True
    except OSError:
        return False


def asegurar_asistente():
    """Si el asistente (el del ícono y los michis) no está abierto, lo abre."""
    if asistente_vivo():
        return True
    log.warning("El asistente no estaba abierto; lo abro")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    log.info("Abriendo asistente con %s", pythonw)
    subprocess.Popen([pythonw, os.path.join(comun.BASE, "asistente.py")], cwd=comun.BASE)
    for _ in range(30):
        time.sleep(0.5)
        if asistente_vivo():
            return True
    return False


ESTADO_VENTANA = {"visible": True}


def avisar_estado(visible):
    ESTADO_VENTANA["visible"] = visible
    log.info("Ventana de notas %s", "visible" if visible else "oculta")
    def trabajo():
        try:
            ok = asegurar_asistente()
            log.info("Asistente disponible: %s", ok)
            comun.avisar_asistente("app:visible" if ESTADO_VENTANA["visible"] else "app:oculta")
        except Exception:
            log.exception("No se pudo avisar al asistente")
    threading.Thread(target=trabajo, daemon=True).start()


def poner_icono_ventana(ventana=None, titulo="Miauia"):
    """pywebview en Windows usa el ícono de Python: lo cambiamos por la huella."""
    if os.name != "nt":
        return
    import ctypes
    u = ctypes.windll.user32
    ico = os.path.join(comun.BASE, "recursos", "miauia.ico")
    hwnd = None
    try:  # la ventana real de pywebview (WinForms)
        hwnd = int(ventana.native.Handle.ToInt64())
    except Exception:
        for _ in range(40):
            hwnd = u.FindWindowW(None, titulo)
            if hwnd:
                break
            time.sleep(0.25)
    if not hwnd:
        return
    grande = u.LoadImageW(None, ico, 1, 256, 256, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
    chico = u.LoadImageW(None, ico, 1, 32, 32, 0x10)
    if grande:
        u.SendMessageW(hwnd, 0x80, 1, grande)  # WM_SETICON, ICON_BIG
    if chico:
        u.SendMessageW(hwnd, 0x80, 0, chico)   # ICON_SMALL


def main():
    if os.name == "nt":
        try:  # que la barra de tareas muestre la huella y no el ícono de Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Miauia.Notas")
        except Exception:
            pass
    log.info("App de notas abierta (pid %s, %s)", os.getpid(), sys.executable)
    import michi_arte
    if michi_arte.instalado() and not os.path.exists(os.path.join(comun.DATOS, "configuracion.json")):
        # primera vez: falta descargar la IA
        log.info("Falta la configuración inicial; abro el configurador")
        subprocess.Popen([sys.executable, os.path.join(comun.BASE, "configurar.py")], cwd=comun.BASE)
        return
    threading.Thread(target=lambda: avisar_estado(True), daemon=True).start()
    vista = ""
    if "--vista" in sys.argv:
        i = sys.argv.index("--vista")
        vista = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    api = Api()
    servidor = escuchar_segunda_apertura(api)
    if servidor is None:
        try:
            with socket.create_connection(("127.0.0.1", PUERTO), timeout=2) as s:
                s.sendall(f"vista:{vista}".encode() if vista else b"hola")
        except OSError:
            pass
        return
    import webview
    ruta = os.path.join(comun.BASE, "interfaz.html")
    url = pathlib.Path(ruta).as_uri() + (f"?vista={vista}" if vista else "")
    api._ventana = webview.create_window(
        "Miauia", url, js_api=api,
        width=1120, height=740, min_size=(760, 500), background_color="#191919",
    )
    v = api._ventana
    # el michi de la barra de Windows se esconde mientras la app está a la vista
    v.events.shown += lambda: avisar_estado(True)
    v.events.shown += lambda: threading.Thread(target=poner_icono_ventana, args=(v,), daemon=True).start()
    v.events.restored += lambda: avisar_estado(True)
    v.events.minimized += lambda: avisar_estado(False)
    v.events.closed += lambda: (asegurar_asistente(), comun.avisar_asistente("app:oculta"))
    webview.start(private_mode=False, storage_path=os.path.join(comun.DATOS, ".webview"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("La app de notas se cerró por un error")
        raise
