# -*- coding: utf-8 -*-
"""Asistente de notas y reuniones. Se queda quieto junto al reloj de Windows y
solo trabaja cuando lo activas con un atajo de teclado."""
import ctypes
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import wave

import tkinter as tk
from tkinter import scrolledtext

import comun

log = comun.configurar_registro("asistente")
CFG = comun.cargar_config()

SIN_VENTANA = 0x08000000
PRIORIDAD_BAJA = 0x00004000
NOMBRE_MODO = {"nota": "Anotando", "pregunta": "Escuchando tu pregunta", "reunion": "Grabando reunión"}

# Colores de la interfaz
FONDO = "#1f2124"
TEXTO = "#f2f2f2"
SUAVE = "#a9adb3"
ROJO = "#e5484d"
AMBAR = "#f5a524"
GRIS = "#8b8f96"


# ================================================================ grabación

class Pista:
    """Una fuente de audio que se guarda en un WAV. Si la fuente se queda en
    silencio (el audio del sistema deja de mandar datos), rellenamos con
    silencio para que los tiempos coincidan con el micrófono."""

    def __init__(self, pa, info, ruta, loopback):
        import pyaudiowpatch as pyaudio
        # el audio del sistema hay que abrirlo con todos sus canales; el micrófono basta en mono
        self.canales = max(1, int(info["maxInputChannels"])) if loopback else 1
        self.tasa = int(info["defaultSampleRate"])
        self.ruta = ruta
        self.escritos = 0
        self.t0 = None
        self.cerrojo = threading.Lock()
        self.wav = wave.open(ruta, "wb")
        self.wav.setnchannels(self.canales)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.tasa)
        self.stream = pa.open(format=pyaudio.paInt16, channels=self.canales, rate=self.tasa,
                              input=True, input_device_index=info["index"],
                              frames_per_buffer=1024, stream_callback=self._cb)

    def arrancar(self, t0):
        self.t0 = t0
        self.stream.start_stream()

    def _rellenar_hasta(self, momento):
        esperado = int((momento - self.t0) * self.tasa)
        falta = esperado - self.escritos
        if falta > self.tasa * 0.25:
            self.wav.writeframes(b"\x00\x00" * self.canales * falta)
            self.escritos += falta

    def _cb(self, datos, cuadros, _info, _estado):
        import pyaudiowpatch as pyaudio
        with self.cerrojo:
            if self.wav is None:
                return (None, pyaudio.paComplete)
            self._rellenar_hasta(time.monotonic() - cuadros / self.tasa)
            self.wav.writeframes(datos)
            self.escritos += cuadros
        return (None, pyaudio.paContinue)

    def cerrar(self, fin):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass
        with self.cerrojo:
            if self.wav is not None:
                self._rellenar_hasta(fin)
                self.wav.close()
                self.wav = None


class Grabador:
    def __init__(self, modo):
        import pyaudiowpatch as pyaudio
        self.modo = modo
        self.pa = pyaudio.PyAudio()
        marca = time.strftime("%Y%m%d_%H%M%S")
        self.pistas = {}
        info_mic = self.pa.get_default_input_device_info()
        self.pistas["mic"] = Pista(self.pa, info_mic, os.path.join(comun.TEMPORAL, f"{marca}_mic.wav"), False)
        if modo == "reunion" and CFG["grabar_audio_sistema_en_reunion"]:
            try:
                info_sis = self.pa.get_default_wasapi_loopback()
                self.pistas["sistema"] = Pista(self.pa, info_sis,
                                               os.path.join(comun.TEMPORAL, f"{marca}_sistema.wav"), True)
            except Exception:
                log.exception("No se pudo capturar el audio del sistema; sigo solo con el micrófono")
        self.inicio = time.monotonic()
        self.inicio_txt = comun.fecha_larga()
        for pista in self.pistas.values():
            pista.arrancar(self.inicio)

    def duracion(self):
        return time.monotonic() - self.inicio

    def detener(self):
        fin = time.monotonic()
        for pista in self.pistas.values():
            pista.cerrar(fin)
        self.pa.terminate()
        return {k: p.ruta for k, p in self.pistas.items()}

    def descartar(self):
        for ruta in self.detener().values():
            try:
                os.remove(ruta)
            except OSError:
                pass


# ================================================================ aplicación

class App:
    def __init__(self, candado=None):
        self.cola = queue.Queue()
        self.candado = candado
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        self.raiz.report_callback_exception = lambda t, v, tb: log.error("Error en la interfaz", exc_info=(t, v, tb))
        try:  # la huella en todas las ventanitas del asistente
            self.raiz.iconbitmap(default=os.path.join(comun.BASE, "recursos", "miauia.ico"))
        except Exception:
            pass
        self.f = max(1.0, self.raiz.winfo_fpixels("1i") / 96.0)  # escala de pantalla (125 %, 150 %...)
        self.michi = None
        self.app_visible = False
        self.grabador = None
        self.procesando = 0
        self.barra = None
        self.icono = None
        self.imagenes = {}

    # ---------- arranque
    def correr(self):
        self._iniciar_icono()
        self._iniciar_michi()
        self._iniciar_avisos()
        self._iniciar_atajos()
        self.raiz.after(90 * 1000, self._revisar_actualizacion)
        if self.candado:
            threading.Thread(target=self._escuchar_mensajes, daemon=True).start()
        self.raiz.after(100, self._revisar_cola)
        self.raiz.mainloop()

    def _iniciar_atajos(self):
        try:
            import keyboard
            keyboard.add_hotkey(CFG["atajo_anotar"], lambda: self.cola.put(("alternar", "nota")))
            keyboard.add_hotkey(CFG["atajo_preguntar"], lambda: self.cola.put(("alternar", "pregunta")))
            keyboard.add_hotkey(CFG["atajo_reunion"], lambda: self.cola.put(("alternar", "reunion")))
        except Exception as e:
            log.exception("No se pudieron registrar los atajos")
            self.cola.put(("aviso", "Atajos de teclado", f"No se pudieron activar: {e}. Usa el menú del ícono."))

    def _escuchar_mensajes(self):
        """La app de notas nos avisa cuando se abre, se minimiza o cambia al michi."""
        while True:
            try:
                conexion, _ = self.candado.accept()
                with conexion:
                    conexion.settimeout(1)
                    try:
                        texto = conexion.recv(256).decode("utf-8", "ignore").strip()
                    except OSError:  # solo querían saber si estoy abierto
                        texto = ""
                if texto:
                    self.cola.put(("mensaje", texto))
            except Exception:
                log.exception("Error recibiendo un mensaje")
                time.sleep(1)

    def _iniciar_michi(self):
        try:
            from michi import Manada
            self.michi = Manada(self.raiz, CFG["michis"], al_clic=lambda: self.abrir("app"),
                                al_menu=self._menu_michi)
        except Exception:
            log.exception("No se pudo iniciar el michi")
            self.michi = None

    def _revisar_actualizacion(self):
        """Cada 6 horas mira si hay una versión nueva en GitHub y lo cuenta una vez."""
        def trabajo():
            try:
                import actualizador
                if not actualizador.activo():
                    return
                info = actualizador.buscar()
                if info and info.get("hay"):
                    marca = os.path.join(comun.DATOS, "actualizacion_avisada.txt")
                    ya = open(marca, encoding="utf-8").read().strip() if os.path.exists(marca) else ""
                    if ya != info["version"]:
                        with open(marca, "w", encoding="utf-8") as f:
                            f.write(info["version"])
                        self.cola.put(("aviso_miauia", f"¡Hay una versión nueva de Miauia ({info['version']})!",
                                       "Abre Miauia y toca «Actualizar»."))
            except Exception:
                log.exception("No se pudo revisar si hay actualizaciones")
        threading.Thread(target=trabajo, daemon=True).start()
        self.raiz.after(6 * 3600 * 1000, self._revisar_actualizacion)

    def _iniciar_avisos(self):
        try:
            from avisos import Avisador
            self.avisador = Avisador(
                self.raiz, CFG, self.f,
                al_avisar=lambda: self.michi and self.michi.alerta(),
                hablar=lambda t: threading.Thread(target=hablar, args=(t,), daemon=True).start())
        except Exception:
            log.exception("No se pudieron iniciar los avisos")
            self.avisador = None

    def jugar(self, tipo, x=None):
        """Comida, premio o estambre para los michis de la barra de Windows."""
        if not self.michi:
            return
        self.michi.mostrar("usuario")
        if tipo == "guardar":
            self.michi.guardar_estambre()
        else:
            self.michi.dar(tipo, x)

    def _menu_michi(self, x, y, desde_patita=False):
        from michi import MenuFlotante
        opciones = []
        if self.michi:
            pos = None if desde_patita else x
            opciones += [("🍗   Darles comida", lambda: self.jugar("comida", pos)),
                         ("🐟   Dar un premio", lambda: self.jugar("premio", pos))]
            if self.michi.hay_estambre():
                opciones.append(("🧶   Guardar el estambre", lambda: self.jugar("guardar")))
            else:
                opciones.append(("🧶   Jugar con estambre", lambda: self.jugar("estambre", pos)))
            opciones.append(None)
        opciones += [
            ("📝   Abrir mis notas", lambda: self.abrir("app")),
            ("🎙   Anotar por voz", lambda: self.alternar("nota")),
            ("❓   Preguntar por voz", lambda: self.alternar("pregunta")),
            ("✏️   Escribir una nota…", lambda: self.pedir_texto("nota")),
            None,
            ("🐱   Mis michis (agregar, personalizar)…", lambda: self.abrir("app", vista="michi")),
            ("🙈   Esconder michis", lambda: self.michi and self.michi.ocultar("usuario")),
            None,
            ("Salir de Miauia", self.salir),
        ]
        try:
            MenuFlotante(self.raiz, x, y, opciones, titulo="Tus michis" if desde_patita else None)
        except Exception:
            log.exception("No se pudo abrir el menú")

    def _dibujar(self, color):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=color)
        # micrófono sencillo en blanco
        d.rounded_rectangle((25, 14, 39, 38), radius=7, fill="white")
        d.arc((19, 24, 45, 46), start=0, end=180, fill="white", width=4)
        d.line((32, 46, 32, 52), fill="white", width=4)
        return img

    def _iniciar_icono(self):
        import pystray
        from pystray import MenuItem as Item, Menu
        import michi_arte
        self.imagenes = {"reposo": michi_arte.icono_huella("rosa", 64),
                         "grabando": michi_arte.icono_huella("rojo", 64),
                         "procesando": michi_arte.icono_huella("ambar", 64)}
        poner = lambda *ev: (lambda icon, item: self.cola.put(ev))
        menu = Menu(
            Item(f"Anotar por voz   ({CFG['atajo_anotar']})", poner("alternar", "nota")),
            Item(f"Preguntar por voz   ({CFG['atajo_preguntar']})", poner("alternar", "pregunta")),
            Item(f"Grabar reunión   ({CFG['atajo_reunion']})", poner("alternar", "reunion")),
            Menu.SEPARATOR,
            Item("Escribir una nota…", poner("escribir", "nota")),
            Item("Preguntar por escrito…", poner("escribir", "pregunta")),
            Menu.SEPARATOR,
            Item("Abrir mis notas", poner("abrir", "app"), default=True),
            Item("Abrir notas en Bloc de notas", poner("abrir", "notas")),
            Item("Abrir carpeta de reuniones", poner("abrir", "reuniones")),
            Item("Michis", Menu(
                Item("🍗  Darles comida", poner("juego", "comida")),
                Item("🐟  Dar un premio", poner("juego", "premio")),
                Item("🧶  Jugar con estambre", poner("juego", "estambre")),
                Item("🧶  Guardar el estambre", poner("juego", "guardar")),
                Menu.SEPARATOR,
                Item("Mostrar / esconder michis", poner("michi_alternar")),
                Item("Mis michis (agregar, personalizar)…", poner("abrir_michis")),
            )),
            Item("Configuración", poner("abrir", "config")),
            Menu.SEPARATOR,
            Item("Salir", poner("salir")),
        )
        self.icono = pystray.Icon("miauia", self.imagenes["reposo"], "Miauia", menu)
        threading.Thread(target=self.icono.run, daemon=True).start()

    def _estado_icono(self):
        if not self.icono:
            return
        if self.grabador:
            clave, texto = "grabando", f"Miauia: {NOMBRE_MODO[self.grabador.modo].lower()}"
        elif self.procesando:
            clave, texto = "procesando", "Miauia: procesando…"
        else:
            clave, texto = "reposo", "Miauia"
        try:
            self.icono.icon = self.imagenes[clave]
            self.icono.title = texto
        except Exception:
            pass
        if self.michi:
            if self.grabador:
                self.michi.poner_estado("reunion" if self.grabador.modo == "reunion" else "escuchando")
            elif self.procesando:
                self.michi.poner_estado("procesando")
            else:
                self.michi.poner_estado(None)

    def avisar(self, titulo, mensaje):
        try:
            self.icono.notify(mensaje[:250] or " ", titulo)
        except Exception:
            log.exception("No se pudo mostrar el aviso")

    # ---------- cola de eventos (todo lo visual pasa por aquí)
    def _revisar_cola(self):
        try:
            while True:
                evento = self.cola.get_nowait()
                try:
                    self._atender(*evento)
                except Exception:
                    log.exception("Error atendiendo %s", evento)
        except queue.Empty:
            pass
        if self.grabador:
            self._actualizar_barra()
        self.raiz.after(150, self._revisar_cola)

    def _atender(self, tipo, *args):
        if tipo == "alternar":
            self.alternar(args[0])
        elif tipo == "escribir":
            self.pedir_texto(args[0])
        elif tipo == "abrir":
            self.abrir(args[0])
        elif tipo == "aviso":
            self.avisar(*args)
        elif tipo == "resultado":
            self.mostrar_resultado(*args)
        elif tipo == "salir":
            self.salir()
        elif tipo == "aviso_miauia":
            self.contar(args[0], args[1], feliz=True, tambien_aviso=True)
        elif tipo == "juego":
            self.jugar(args[0])
        elif tipo == "abrir_michis":
            self.abrir("app", vista="michi")
        elif tipo == "michi_alternar" and self.michi:
            if "usuario" in self.michi.motivos_ocultar:
                self.michi.mostrar("usuario")
            else:
                self.michi.ocultar("usuario")
        elif tipo == "mensaje":
            self.recibir_mensaje(args[0])

    def recibir_mensaje(self, texto):
        if texto == "salir":  # se abrió una versión nueva
            log.info("Otra copia del asistente pidió el lugar; cerrando esta")
            self.salir()
        elif texto == "app:visible":
            self.app_visible = True
            if self.michi:
                self.michi.ocultar("app")
        elif texto == "app:oculta":
            self.app_visible = False
            if self.michi:
                self.michi.mostrar("app")
                self.michi.reaccion(None)
        elif texto == "config:recargar":
            nuevo = comun.cargar_config()
            for clave in ("avisar_minutos_antes", "resumen_diario", "sonido_avisos", "voz_avisos", "michi", "michis"):
                CFG[clave] = nuevo[clave]
        elif texto.startswith("juego:"):
            if self.michi:
                self.michi.mostrar("app")
            self.jugar(texto[6:])
        elif texto == "aviso:prueba" and getattr(self, "avisador", None):
            self.avisador.prueba()
        elif texto == "michi:recargar":
            nuevo = comun.cargar_config()
            CFG["michi"], CFG["michis"] = nuevo["michi"], nuevo["michis"]
            if self.michi:
                self.michi.aplicar_configs(CFG["michis"])
            else:
                self._iniciar_michi()

    # ---------- grabar
    def alternar(self, modo):
        if self.grabador:
            if self.grabador.modo == modo:
                self.detener()
            else:
                self.avisar("Ya estoy grabando", f"Primero detén: {NOMBRE_MODO[self.grabador.modo].lower()}.")
            return
        try:
            self.grabador = Grabador(modo)
        except Exception as e:
            log.exception("No se pudo abrir el micrófono")
            self.grabador = None
            self.avisar("Micrófono", f"No pude abrir el micrófono: {e}")
            return
        self._mostrar_barra()
        self._estado_icono()

    def detener(self, cancelar=False):
        grabador, self.grabador = self.grabador, None
        self._ocultar_barra()
        if not grabador:
            return
        if cancelar or grabador.duracion() < 0.8:
            grabador.descartar()
            self._estado_icono()
            return
        rutas = grabador.detener()
        self.procesar(grabador.modo, audio=rutas.get("mic"), audio_sistema=rutas.get("sistema"),
                      inicio=grabador.inicio_txt)
        if grabador.modo == "reunion":
            self.contar("Reunión guardada", "La estoy procesando. Te aviso cuando esté lista.", feliz=False)

    # ---------- procesar en un proceso aparte
    def procesar(self, modo, audio=None, audio_sistema=None, texto=None, inicio=None):
        self.procesando += 1
        self._estado_icono()
        threading.Thread(target=self._trabajar, args=(modo, audio, audio_sistema, texto, inicio),
                         daemon=True).start()

    def _trabajar(self, modo, audio, audio_sistema, texto, inicio):
        salida = os.path.join(comun.TEMPORAL, f"resultado_{time.time_ns()}.json")
        carpeta = os.path.dirname(sys.executable)
        python = os.path.join(carpeta, "python.exe")
        if not os.path.exists(python):
            python = sys.executable
        orden = [python, os.path.join(comun.BASE, "trabajador.py"), "--modo", modo, "--salida", salida]
        if audio:
            orden += ["--audio", audio]
        if audio_sistema:
            orden += ["--audio-sistema", audio_sistema]
        if texto:
            orden += ["--texto", texto]
        if inicio:
            orden += ["--inicio", inicio]
        banderas = (SIN_VENTANA | PRIORIDAD_BAJA) if os.name == "nt" else 0
        try:
            proc = subprocess.run(orden, cwd=comun.BASE, creationflags=banderas,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(salida):
                with open(salida, "r", encoding="utf-8") as f:
                    resultado = json.load(f)
                os.remove(salida)
            else:
                error = proc.stderr.decode("utf-8", "ignore")[-400:]
                log.error("El trabajador terminó sin resultado: %s", error)
                resultado = {"ok": False, "titulo": "Algo falló",
                             "mensaje": "Revisa datos/registro.log para ver el detalle."}
        except Exception as e:
            log.exception("No se pudo ejecutar el trabajador")
            resultado = {"ok": False, "titulo": "Algo falló", "mensaje": str(e)}
        self.cola.put(("resultado", modo, resultado))

    def mostrar_resultado(self, modo, r):
        self.procesando = max(0, self.procesando - 1)
        self._estado_icono()
        if modo == "pregunta" and r.get("ok"):
            self.ventana_respuesta(r.get("pregunta", ""), r.get("mensaje", ""))
            if CFG["leer_respuestas_en_voz"]:
                threading.Thread(target=hablar, args=(r.get("mensaje", ""),), daemon=True).start()
        else:
            self.contar(r.get("titulo", "Miauia"), r.get("mensaje", ""), feliz=bool(r.get("ok")),
                        tambien_aviso=(modo == "reunion" or not r.get("ok")))
        if modo == "pregunta" and r.get("ok") and self.michi:
            self.michi.reaccion(None)

    def contar(self, titulo, mensaje, feliz=True, tambien_aviso=False):
        """Si el michi está a la vista, te lo dice él con un globito; si no, un aviso de Windows."""
        if self.michi and self.michi.visible():
            self.michi.reaccion(f"{titulo}\n{mensaje}" if mensaje else titulo, feliz=feliz, segundos=6)
            if tambien_aviso:
                self.avisar(titulo, mensaje)
        else:
            self.avisar(titulo, mensaje)

    # ---------- ventanas
    def _ventana_base(self, titulo, ancho, alto):
        v = tk.Toplevel(self.raiz)
        v.title(titulo)
        v.configure(bg=FONDO)
        v.attributes("-topmost", True)
        ancho, alto = int(ancho * self.f), int(alto * self.f)
        x = v.winfo_screenwidth() - ancho - 24
        y = v.winfo_screenheight() - alto - 72
        v.geometry(f"{ancho}x{alto}+{x}+{y}")
        return v

    def _boton(self, padre, texto, accion, color="#3a3d42"):
        return tk.Button(padre, text=texto, command=accion, bg=color, fg=TEXTO, relief="flat",
                         activebackground="#4a4e54", activeforeground=TEXTO, padx=12, pady=4,
                         font=("Segoe UI", 9), cursor="hand2", bd=0)

    def _mostrar_barra(self):
        b = tk.Toplevel(self.raiz)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.configure(bg=FONDO)
        ancho, alto = int(360 * self.f), int(44 * self.f)
        b.geometry(f"{ancho}x{alto}+{(b.winfo_screenwidth() - ancho) // 2}+{b.winfo_screenheight() - alto - 70}")
        tk.Label(b, text="●", fg=ROJO, bg=FONDO, font=("Segoe UI", 14)).pack(side="left", padx=(12, 6))
        self.barra_texto = tk.Label(b, text="", fg=TEXTO, bg=FONDO, font=("Segoe UI", 10))
        self.barra_texto.pack(side="left")
        self._boton(b, "Cancelar", lambda: self.detener(cancelar=True)).pack(side="right", padx=(4, 10))
        self._boton(b, "Detener", self.detener, color=ROJO).pack(side="right", padx=4)
        self.barra = b
        self._actualizar_barra()

    def _actualizar_barra(self):
        if not (self.barra and self.grabador):
            return
        s = int(self.grabador.duracion())
        tiempo = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
        self.barra_texto.config(text=f"{NOMBRE_MODO[self.grabador.modo]}…  {tiempo}")
        if self.grabador.modo != "reunion" and s >= int(CFG["max_segundos_nota"]):
            self.detener()

    def _ocultar_barra(self):
        if self.barra:
            self.barra.destroy()
            self.barra = None

    def ventana_respuesta(self, pregunta, respuesta):
        v = self._ventana_base("Miauia", 460, 320)
        tk.Label(v, text=pregunta, fg=SUAVE, bg=FONDO, font=("Segoe UI", 9, "italic"),
                 wraplength=420, justify="left", anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        caja = scrolledtext.ScrolledText(v, wrap="word", bg="#2a2d31", fg=TEXTO, relief="flat",
                                         font=("Segoe UI", 11), padx=10, pady=8, bd=0,
                                         insertbackground=TEXTO)
        caja.insert("1.0", respuesta)
        caja.config(state="disabled")
        caja.pack(fill="both", expand=True, padx=16)
        fila = tk.Frame(v, bg=FONDO)
        fila.pack(fill="x", padx=16, pady=10)

        def copiar():
            v.clipboard_clear()
            v.clipboard_append(respuesta)

        self._boton(fila, "Cerrar", v.destroy).pack(side="right")
        self._boton(fila, "Copiar", copiar).pack(side="right", padx=6)
        v.focus_force()

    def pedir_texto(self, modo):
        titulo = "Escribir una nota" if modo == "nota" else "Preguntar al asistente"
        pista = ("Ej.: el jueves a las 3 reunión con el cliente" if modo == "nota"
                 else "Ej.: ¿qué tengo pendiente esta semana?")
        v = self._ventana_base(titulo, 460, 150)
        tk.Label(v, text=pista, fg=SUAVE, bg=FONDO, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(14, 6))
        entrada = tk.Entry(v, bg="#2a2d31", fg=TEXTO, relief="flat", font=("Segoe UI", 11),
                           insertbackground=TEXTO)
        entrada.pack(fill="x", padx=16, ipady=6)

        def enviar(_e=None):
            texto = entrada.get().strip()
            v.destroy()
            if texto:
                self.procesar(modo, texto=texto)

        fila = tk.Frame(v, bg=FONDO)
        fila.pack(fill="x", padx=16, pady=12)
        self._boton(fila, "Enviar", enviar, color="#2f6fdf").pack(side="right")
        self._boton(fila, "Cancelar", v.destroy).pack(side="right", padx=6)
        entrada.bind("<Return>", enviar)
        entrada.bind("<Escape>", lambda _e: v.destroy())
        v.focus_force()
        entrada.focus_set()

    # ---------- otros
    def abrir(self, que, vista=None):
        comun.asegurar_carpetas()
        if que == "app":
            pythonw = sys.executable  # el asistente ya corre con pythonw.exe
            orden = [pythonw, os.path.join(comun.BASE, "notas_app.py")] + (["--vista", vista] if vista else [])
            subprocess.Popen(orden, cwd=comun.BASE)
        elif que == "notas":
            subprocess.Popen(["notepad.exe", comun.NOTAS])
        elif que == "config":
            subprocess.Popen(["notepad.exe", comun.CONFIG])
            self.avisar("Configuración", "Si cambias algo, cierra y vuelve a abrir el asistente.")
        else:
            os.startfile(comun.REUNIONES)

    def salir(self):
        log.info("Saliendo del asistente")
        if self.grabador:
            self.detener()
        try:
            self.icono.stop()
        except Exception:
            pass
        self.raiz.quit()


def hablar(texto):
    guion = (
        "[Console]::InputEncoding=[Text.Encoding]::UTF8;"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'es*'}|select -First 1;"
        "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
        "$s.Speak([Console]::In.ReadToEnd())"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", guion], input=texto.encode("utf-8"),
                       creationflags=SIN_VENTANA, timeout=300)
    except Exception:
        log.exception("No se pudo leer la respuesta en voz alta")


def una_sola_vez():
    """Evita dos asistentes a la vez. Si ya hay uno abierto (por ejemplo, una versión
    vieja), le pide que se cierre y toma su lugar."""
    for intento in range(20):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 47831))
            s.listen(5)
            return s
        except OSError:
            s.close()
            if intento == 0:
                comun.avisar_asistente("salir")
            elif intento == 5 and os.name == "nt":
                cerrar_copias_viejas()
            time.sleep(0.4)
    return None


def cerrar_copias_viejas():
    """Una versión vieja no entiende el mensaje "salir": la cerramos directamente."""
    orden = ("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*asistente.py*' -and $_.ProcessId -ne {os.getpid()} -and $_.ProcessId -ne {os.getppid()} }} | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", orden], creationflags=SIN_VENTANA, timeout=20)
    except Exception:
        log.exception("No se pudo cerrar la copia vieja del asistente")


def registrar_fallos():
    """Con pythonw no hay consola: cualquier error (incluso los graves) va al registro."""
    import faulthandler
    try:
        faulthandler.enable(open(os.path.join(comun.DATOS, "fallos.log"), "a"))
    except Exception:
        pass
    sys.excepthook = lambda t, v, tb: log.error("Error no controlado", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.error("Error en un hilo", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


if __name__ == "__main__":
    comun.asegurar_carpetas()
    registrar_fallos()
    candado = una_sola_vez()
    if candado is None:
        log.warning("No pude tomar el lugar de otra copia del asistente; me cierro")
        sys.exit(0)
    log.info("Asistente iniciado (pid %s)", os.getpid())
    if os.name == "nt":  # que el michi se vea nítido con la escala de Windows (125 %, 150 %...)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:  # para que Windows muestre la huella y no el ícono de Python
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Miauia.Asistente")
        except Exception:
            pass
    try:
        App(candado).correr()
        log.info("Asistente cerrado")
    except Exception:
        log.exception("El asistente se cerró por un error")
        raise
