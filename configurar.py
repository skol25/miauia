# -*- coding: utf-8 -*-
"""Configuración inicial de Miauia: instala Ollama si falta, descarga los modelos de
IA y el de voz, con una ventanita y barras de progreso. Se abre sola al terminar la
instalación y también si algo quedó a medias."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request

import comun
import michi_arte

log = comun.configurar_registro("configurar")
LISTO = os.path.join(comun.DATOS, "configuracion.json")
URL_OLLAMA = "https://ollama.com/download/OllamaSetup.exe"
SIN_VENTANA = 0x08000000

PAQUETES = {
    "completo": {"nombre": "Completo (recomendado)", "rapido": "qwen3.5:4b", "reunion": "qwen3.5:9b",
                 "detalle": "Dos modelos: uno rápido para notas y otro más listo para reuniones. Unos 9 GB."},
    "ligero": {"nombre": "Ligero", "rapido": "qwen3.5:4b", "reunion": "qwen3.5:4b",
               "detalle": "Un solo modelo para todo. Unos 3,5 GB. Ideal con 8 GB de RAM."},
}

FONDO, PANEL, TEXTO, SUAVE, ACENTO, ROSA = "#191919", "#222326", "#f2f2f2", "#9b9a97", "#2383e2", "#f7a8c4"


def configuracion_lista():
    try:
        with open(LISTO, "r", encoding="utf-8") as f:
            return json.load(f).get("lista", False)
    except Exception:
        return False


def ram_gb():
    if os.name != "nt":
        return 16
    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEM()
    m.dwLength = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullTotalPhys / 1024 ** 3)


def disco_libre_gb():
    try:
        return round(shutil.disk_usage(os.path.expanduser("~")).free / 1024 ** 3)
    except Exception:
        return 0


def ruta_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    posible = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return posible if os.path.exists(posible) else None


def ollama_api(ruta, datos=None, tiempo=10):
    url = comun.cargar_config()["ollama_url"].rstrip("/") + ruta
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    return urllib.request.urlopen(urllib.request.Request(url, data=cuerpo, headers={"Content-Type": "application/json"}),
                                  timeout=tiempo)


def ollama_responde():
    try:
        ollama_api("/api/version", tiempo=3).read()
        return True
    except Exception:
        return False


def importar_notas_viejas():
    """Si usabas la versión de la carpeta Documentos\\Asistente, trae tus notas y michis."""
    viejo = os.path.join(os.path.expanduser("~"), "Documents", "Asistente")
    if not os.path.isdir(os.path.join(viejo, "datos")) or os.path.abspath(viejo) == os.path.abspath(comun.USUARIO):
        return False
    if os.path.exists(comun.NOTAS) and len(comun.listar_notas()) > 0:
        return False  # ya hay notas nuevas: no pisamos nada
    for nombre in ("notas.md", "proyectos.json", "michis_estado.json", "avisados.json"):
        origen = os.path.join(viejo, "datos", nombre)
        if os.path.exists(origen):
            shutil.copy2(origen, os.path.join(comun.DATOS, nombre))
    if os.path.isdir(os.path.join(viejo, "datos", "reuniones")):
        shutil.copytree(os.path.join(viejo, "datos", "reuniones"), comun.REUNIONES, dirs_exist_ok=True)
    cfg_viejo = os.path.join(viejo, "config.json")
    if os.path.exists(cfg_viejo) and not os.path.exists(comun.CONFIG):
        shutil.copy2(cfg_viejo, comun.CONFIG)
    log.info("Importé las notas de %s", viejo)
    return True


class Ventana:
    def __init__(self):
        self.raiz = tk.Tk()
        self.raiz.title("Miauia · Configuración")
        self.raiz.configure(bg=FONDO)
        self.raiz.resizable(False, False)
        try:
            self.raiz.iconbitmap(os.path.join(comun.BASE, "recursos", "miauia.ico"))
        except Exception:
            pass
        self.f = max(1.0, self.raiz.winfo_fpixels("1i") / 96.0)
        ancho, alto = int(560 * self.f), int(560 * self.f)
        self.raiz.geometry(f"{ancho}x{alto}+{(self.raiz.winfo_screenwidth() - ancho) // 2}+"
                           f"{(self.raiz.winfo_screenheight() - alto) // 3}")
        self.sprites = michi_arte.cargar_sprites()
        self.colores = michi_arte.paleta(comun.cargar_config()["michi"])
        self.anim, self.cuadro, self.fotos = "sentado", 0, {}
        self.paquete = tk.StringVar(value="completo" if ram_gb() >= 14 else "ligero")
        self.trabajando = False
        self._armar()
        self._animar()

    # ---------- interfaz
    def _armar(self):
        r = self.raiz
        self.gato = tk.Label(r, bg=FONDO)
        self.gato.pack(pady=(int(14 * self.f), 0))
        self.titulo = tk.Label(r, text="¡Hola! Vamos a dejar lista a Miauia", bg=FONDO, fg=TEXTO,
                               font=("Segoe UI", 15, "bold"))
        self.titulo.pack()
        self.subtitulo = tk.Label(r, text="Todo funciona dentro de tu PC, sin pagar nada. Solo falta descargar la IA.",
                                  bg=FONDO, fg=SUAVE, font=("Segoe UI", 9), wraplength=int(480 * self.f))
        self.subtitulo.pack(pady=(2, int(10 * self.f)))

        self.caja = tk.Frame(r, bg=FONDO)
        self.caja.pack(fill="both", expand=True, padx=int(28 * self.f))
        self._pantalla_eleccion()

    def _limpiar(self):
        for w in self.caja.winfo_children():
            w.destroy()

    def _boton(self, padre, texto, accion, primario=True):
        return tk.Button(padre, text=texto, command=accion, bg=ACENTO if primario else "#34363a", fg="white",
                         activebackground="#3190ec" if primario else "#44474d", activeforeground="white",
                         relief="flat", bd=0, padx=18, pady=6, font=("Segoe UI", 10, "bold"), cursor="hand2")

    def _pantalla_eleccion(self):
        self._limpiar()
        ram, libre = ram_gb(), disco_libre_gb()
        tk.Label(self.caja, text=f"Tu PC tiene {ram} GB de RAM y {libre} GB libres en el disco.", bg=FONDO, fg=SUAVE,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))
        for clave, p in PAQUETES.items():
            marco = tk.Frame(self.caja, bg=PANEL, highlightthickness=1, highlightbackground="#34363a")
            marco.pack(fill="x", pady=4)
            tk.Radiobutton(marco, text=p["nombre"], variable=self.paquete, value=clave, bg=PANEL, fg=TEXTO,
                           selectcolor=PANEL, activebackground=PANEL, activeforeground=TEXTO,
                           font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            tk.Label(marco, text=p["detalle"], bg=PANEL, fg=SUAVE, font=("Segoe UI", 9), anchor="w",
                     justify="left", wraplength=int(440 * self.f)).pack(fill="x", padx=32, pady=(0, 8))
        tk.Label(self.caja, text="Se descargan una sola vez. Puede tardar según tu internet (puedes seguir usando la PC).",
                 bg=FONDO, fg=SUAVE, font=("Segoe UI", 8), wraplength=int(480 * self.f), justify="left").pack(anchor="w", pady=(8, 0))
        fila = tk.Frame(self.caja, bg=FONDO)
        fila.pack(fill="x", side="bottom", pady=int(16 * self.f))
        self._boton(fila, "Empezar", self.empezar).pack(side="right")

    def _pantalla_progreso(self):
        self._limpiar()
        self.pasos = {}
        for clave, texto in (("ollama", "Motor de IA (Ollama)"), ("modelos", "Modelos de IA"),
                             ("voz", "Reconocimiento de voz"), ("final", "Últimos detalles")):
            marco = tk.Frame(self.caja, bg=PANEL)
            marco.pack(fill="x", pady=4)
            fila = tk.Frame(marco, bg=PANEL)
            fila.pack(fill="x", padx=12, pady=(8, 2))
            icono = tk.Label(fila, text="○", bg=PANEL, fg=SUAVE, font=("Segoe UI", 11))
            icono.pack(side="left")
            tk.Label(fila, text=texto, bg=PANEL, fg=TEXTO, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
            detalle = tk.Label(marco, text="En espera", bg=PANEL, fg=SUAVE, font=("Segoe UI", 9), anchor="w")
            detalle.pack(fill="x", padx=12)
            barra = tk.Canvas(marco, height=int(6 * self.f), bg="#333", highlightthickness=0)
            barra.pack(fill="x", padx=12, pady=(4, 10))
            self.pasos[clave] = {"icono": icono, "detalle": detalle, "barra": barra, "valor": 0, "indet": False}
        self.pie = tk.Frame(self.caja, bg=FONDO)
        self.pie.pack(fill="x", side="bottom", pady=int(12 * self.f))

    # ---------- actualizar la interfaz desde el hilo de trabajo
    def paso(self, clave, estado=None, detalle=None, valor=None, indeterminado=None):
        def hacer():
            p = self.pasos[clave]
            if estado:
                p["icono"].config(text={"activo": "◐", "ok": "✓", "error": "✕"}[estado],
                                  fg={"activo": ROSA, "ok": "#4dab9a", "error": "#e5484d"}[estado])
            if detalle is not None:
                p["detalle"].config(text=detalle)
            if valor is not None:
                p["valor"] = valor
            if indeterminado is not None:
                p["indet"] = indeterminado
            self._pintar_barra(p)
        self.raiz.after(0, hacer)

    def _pintar_barra(self, p):
        c = p["barra"]
        c.delete("all")
        w, h = c.winfo_width() or 400, c.winfo_height() or 6
        if p["indet"]:
            x = (time.monotonic() * 180) % (w + 80) - 80
            c.create_rectangle(x, 0, x + 80, h, fill=ROSA, width=0)
        else:
            c.create_rectangle(0, 0, w * max(0, min(1, p["valor"])), h, fill=ROSA, width=0)

    def _animar(self):
        try:
            anim = self.sprites["animaciones"][self.anim]
            self.cuadro = (self.cuadro + 1) % len(anim["cuadros"])
            clave = (self.anim, self.cuadro)
            if clave not in self.fotos:
                from PIL import Image, ImageTk
                img = michi_arte.dibujar(anim["cuadros"][self.cuadro], self.colores, "collar", max(3, round(4 * self.f)))
                fondo = Image.new("RGBA", img.size, FONDO)
                fondo.alpha_composite(img)
                self.fotos[clave] = ImageTk.PhotoImage(fondo)
            self.gato.config(image=self.fotos[clave])
            for p in getattr(self, "pasos", {}).values():
                self._pintar_barra(p)
            espera = int(1000 / anim["fps"])
        except Exception:
            espera = 500
        self.raiz.after(min(espera, 120) if getattr(self, "pasos", None) else espera, self._animar)

    # ---------- trabajo
    def empezar(self):
        self.trabajando = True
        self.anim = "pensar"
        self.subtitulo.config(text="Descargando… puedes dejar esta ventana abierta y seguir con lo tuyo.")
        self._pantalla_progreso()
        threading.Thread(target=self._trabajar, daemon=True).start()

    def _trabajar(self):
        try:
            comun.asegurar_carpetas()
            importar_notas_viejas()
            self._paso_ollama()
            self._paso_modelos()
            self._paso_voz()
            self._paso_final()
            self.raiz.after(0, self._terminado)
        except Exception as e:
            log.exception("La configuración falló")
            self.raiz.after(0, lambda: self._fallo(str(e)))

    def _descargar(self, url, destino, clave):
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Miauia"}), timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            hecho = 0
            with open(destino, "wb") as f:
                while True:
                    trozo = r.read(1024 * 256)
                    if not trozo:
                        break
                    f.write(trozo)
                    hecho += len(trozo)
                    if total:
                        self.paso(clave, valor=hecho / total,
                                  detalle=f"Descargando… {hecho / 1024 ** 2:.0f} de {total / 1024 ** 2:.0f} MB")

    def _paso_ollama(self):
        self.paso("ollama", "activo", "Buscando Ollama…")
        if not ruta_ollama():
            archivo = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
            self._descargar(URL_OLLAMA, archivo, "ollama")
            self.paso("ollama", detalle="Instalando Ollama…", indeterminado=True)
            r = subprocess.run([archivo, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=SIN_VENTANA)
            if r.returncode != 0 or not ruta_ollama():
                raise RuntimeError("No se pudo instalar Ollama. Instálalo desde ollama.com y vuelve a abrir Miauia.")
        if not ollama_responde():
            self.paso("ollama", detalle="Encendiendo Ollama…", indeterminado=True)
            subprocess.Popen([ruta_ollama(), "serve"], creationflags=SIN_VENTANA | 0x00000008,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(60):
                time.sleep(1)
                if ollama_responde():
                    break
            else:
                raise RuntimeError("Ollama no arrancó. Ábrelo desde el menú Inicio y vuelve a intentar.")
        self.paso("ollama", "ok", "Listo", 1, indeterminado=False)

    def _paso_modelos(self):
        p = PAQUETES[self.paquete.get()]
        modelos = list(dict.fromkeys([p["rapido"], p["reunion"]]))
        self.paso("modelos", "activo", "Revisando…")
        instalados = {m["name"] for m in json.load(ollama_api("/api/tags")).get("models", [])}
        for i, modelo in enumerate(modelos, 1):
            if modelo in instalados or f"{modelo}:latest" in instalados:
                continue
            etiqueta = f"({i} de {len(modelos)}) {modelo}"
            with ollama_api("/api/pull", {"model": modelo, "stream": True}, tiempo=3600) as r:
                for linea in r:
                    if not linea.strip():
                        continue
                    d = json.loads(linea)
                    if d.get("error"):
                        raise RuntimeError(f"No se pudo descargar {modelo}: {d['error']}")
                    total, hecho = d.get("total"), d.get("completed")
                    if total and hecho:
                        self.paso("modelos", valor=hecho / total, indeterminado=False,
                                  detalle=f"{etiqueta}: {hecho / 1024 ** 3:.1f} de {total / 1024 ** 3:.1f} GB")
                    else:
                        self.paso("modelos", detalle=f"{etiqueta}: {d.get('status', '…')}")
        cfg_path = comun.CONFIG
        comun.cargar_config()  # crea el archivo si no existe
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        cfg["modelo_rapido"], cfg["modelo_reunion"] = p["rapido"], p["reunion"]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        self.paso("modelos", "ok", "Listo", 1, indeterminado=False)

    def _paso_voz(self):
        self.paso("voz", "activo", "Descargando el modelo de voz (unos 500 MB)…", indeterminado=True)
        python = os.path.join(os.path.dirname(sys.executable), "python.exe")
        if not os.path.exists(python):
            python = sys.executable
        r = subprocess.run([python, os.path.join(comun.BASE, "trabajador.py"), "--preparar"],
                           cwd=comun.BASE, creationflags=SIN_VENTANA if os.name == "nt" else 0,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            log.error("Whisper: %s", r.stdout.decode("utf-8", "ignore")[-800:])
            raise RuntimeError("No se pudo descargar el modelo de voz. Revisa tu internet y reintenta.")
        self.paso("voz", "ok", "Listo", 1, indeterminado=False)

    def _paso_final(self):
        self.paso("final", "activo", "Guardando…", indeterminado=True)
        with open(LISTO, "w", encoding="utf-8") as f:
            json.dump({"lista": True, "paquete": self.paquete.get(), "fecha": time.strftime("%Y-%m-%d %H:%M")}, f)
        self.paso("final", "ok", "Listo", 1, indeterminado=False)

    def _terminado(self):
        self.trabajando = False
        self.anim = "festejar"
        self.titulo.config(text="¡Miauia está lista!")
        self.subtitulo.config(text="Tu michi ya te está esperando en la barra de Windows.")
        for w in self.pie.winfo_children():
            w.destroy()
        self._boton(self.pie, "Abrir Miauia", self.abrir_miauia).pack(side="right")

    def _fallo(self, mensaje):
        self.trabajando = False
        self.anim = "sentado"
        self.subtitulo.config(text=mensaje, fg="#ff8c8f")
        for w in self.pie.winfo_children():
            w.destroy()
        self._boton(self.pie, "Reintentar", self._reintentar).pack(side="right")
        self._boton(self.pie, "Cerrar", self.raiz.destroy, primario=False).pack(side="right", padx=8)

    def _reintentar(self):
        self.subtitulo.config(fg=SUAVE)
        self.empezar()

    def abrir_miauia(self):
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        subprocess.Popen([pythonw, os.path.join(comun.BASE, "notas_app.py")], cwd=comun.BASE)
        self.raiz.after(600, self.raiz.destroy)

    def correr(self):
        self.raiz.mainloop()


if __name__ == "__main__":
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Miauia.Configurar")
        except Exception:
            pass
    Ventana().correr()
