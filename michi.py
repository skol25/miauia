# -*- coding: utf-8 -*-
"""Los michis de escritorio: gatitos pixel art que caminan encima de la barra de
Windows. El primero es el del asistente (te muestra lo que está haciendo); los
demás son compañeros. Puedes darles comida, premios, jugar con un estambre y
hacerles mimos."""
import ctypes
import logging
import os
import random
import time
import tkinter as tk

import michi_arte

log = logging.getLogger("michi")
CLAVE = "#ff00fe"  # color que Windows vuelve transparente (no se usa en el gato)
ES_WINDOWS = os.name == "nt"

PESOS = {  # qué tan seguido hace cada cosa según su personalidad
    "tranquilo": {"caminar": 15, "sentado": 30, "dormir": 45, "lavarse": 10, "amigo": 6},
    "normal": {"caminar": 40, "sentado": 25, "dormir": 20, "lavarse": 15, "amigo": 12},
    "jugueton": {"caminar": 50, "sentado": 15, "dormir": 10, "lavarse": 10, "festejar": 7, "amigo": 20},
}
DURACION = {"sentado": (4, 10), "dormir": (25, 90), "parado": (1.5, 3)}
UNA_VEZ = {"lavarse", "festejar"}
ESTADOS = {"escuchando": "escuchar", "reunion": "audifonos", "procesando": "pensar"}
FRASES_HAMBRE = ["Tengo hambre…", "¿Y mi comida?", "Miau… (hambre)", "Un pescadito no estaría mal"]


# ---------------------------------------------------------------- Windows

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def area_de_trabajo(raiz):
    """Rectángulo de la pantalla sin la barra de tareas."""
    if ES_WINDOWS:
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right, r.bottom
    return 0, 0, raiz.winfo_screenwidth(), raiz.winfo_screenheight() - 48


def hay_pantalla_completa(propias):
    """True si la ventana activa ocupa toda la pantalla (video, presentación, juego)."""
    if not ES_WINDOWS:
        return False
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd or hwnd in propias:
        return False
    clase = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, clase, 64)
    if clase.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False
    r = RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left <= 0 and r.top <= 0 and r.right >= u.GetSystemMetrics(0) and r.bottom >= u.GetSystemMetrics(1)


def factor_pantalla(raiz):
    try:
        return max(1.0, raiz.winfo_fpixels("1i") / 96.0)
    except Exception:
        return 1.0


def ventana_transparente(raiz):
    v = tk.Toplevel(raiz)
    v.overrideredirect(True)
    v.attributes("-topmost", True)
    v.configure(bg=CLAVE)
    if ES_WINDOWS:
        v.attributes("-transparentcolor", CLAVE)
    return v


def a_foto(img):
    from PIL import Image, ImageTk
    if ES_WINDOWS:  # fondo del color clave para que Windows lo vuelva transparente
        fondo = Image.new("RGBA", img.size, CLAVE)
        fondo.alpha_composite(img)
        img = fondo
    return ImageTk.PhotoImage(img)


# ---------------------------------------------------------------- huella y menú propio

from michi_arte import HUELLA  # la huella rosita (pixel art)
COLORES_HUELLA = {"o": "#3a222e", "P": "#f7a8c4", "L": "#ffd6e4", "D": "#d67a9e"}
COLORES_HUELLA_ENCIMA = {"o": "#3a222e", "P": "#ffc2d8", "L": "#ffffff", "D": "#ef93b5"}


def dibujar_huella(escala, encima=False):
    from PIL import Image
    colores = COLORES_HUELLA_ENCIMA if encima else COLORES_HUELLA
    img = Image.new("RGBA", (len(HUELLA[0]), len(HUELLA)), (0, 0, 0, 0))
    for y, fila in enumerate(HUELLA):
        for x, c in enumerate(fila):
            if c != ".":
                img.putpixel((x, y), michi_arte._rgb(colores[c]) + (255,))
    return img.resize((img.width * escala, img.height * escala), Image.NEAREST)


class MenuFlotante:
    """Menú oscuro propio (el menú nativo de Windows no siempre abre desde ventanas sin marco)."""
    abierto = None

    def __init__(self, raiz, x, y, opciones, titulo=None):
        if MenuFlotante.abierto:
            MenuFlotante.abierto.cerrar()
        f = factor_pantalla(raiz)
        self.v = v = tk.Toplevel(raiz)
        v.overrideredirect(True)
        v.attributes("-topmost", True)
        v.configure(bg="#44474e")
        marco = tk.Frame(v, bg="#25272b")
        marco.pack(padx=1, pady=1)
        if titulo:
            tk.Label(marco, text=titulo, bg="#25272b", fg="#8b8f96", font=("Segoe UI", 8, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        for op in opciones:
            if op is None:
                tk.Frame(marco, bg="#3a3d42", height=1).pack(fill="x", padx=8, pady=4)
                continue
            texto, accion = op
            et = tk.Label(marco, text=texto, bg="#25272b", fg="#f2f2f2", font=("Segoe UI", 10),
                          anchor="w", padx=12, pady=int(5 * f), cursor="hand2")
            et.pack(fill="x", padx=4)
            et.bind("<Enter>", lambda e, w=et: w.configure(bg="#3a3d42"))
            et.bind("<Leave>", lambda e, w=et: w.configure(bg="#25272b"))
            et.bind("<ButtonRelease-1>", lambda e, a=accion: self._elegir(a))
        tk.Frame(marco, bg="#25272b", height=4).pack()
        v.update_idletasks()
        w, h = v.winfo_reqwidth(), v.winfo_reqheight()
        sw, sh = raiz.winfo_screenwidth(), raiz.winfo_screenheight()
        px = max(4, min(int(x - w + 20), sw - w - 4))
        py = int(y - h - 6) if y - h - 6 > 0 else int(y + 6)
        py = max(4, min(py, sh - h - 4))
        v.geometry(f"+{px}+{py}")
        v.bind("<Escape>", lambda e: self.cerrar())
        v.bind("<FocusOut>", lambda e: v.after(150, self._quizas_cerrar))
        v.after(50, lambda: (v.focus_force(), v.lift()))
        self.fuera_desde = None
        v.after(400, self._vigilar)
        MenuFlotante.abierto = self

    def _elegir(self, accion):
        self.cerrar()
        try:
            accion()
        except Exception:
            log.exception("Error en una opción del menú")

    def _dentro(self):
        try:
            x, y = self.v.winfo_pointerxy()
            return (self.v.winfo_rootx() <= x <= self.v.winfo_rootx() + self.v.winfo_width() and
                    self.v.winfo_rooty() <= y <= self.v.winfo_rooty() + self.v.winfo_height())
        except Exception:
            return False

    def _quizas_cerrar(self):
        if not self._dentro():
            self.cerrar()

    def _vigilar(self):
        """Si el mouse se va del menú por un rato, se cierra solo."""
        if MenuFlotante.abierto is not self:
            return
        if self._dentro():
            self.fuera_desde = None
        elif self.fuera_desde is None:
            self.fuera_desde = time.monotonic()
        elif time.monotonic() - self.fuera_desde > 2.5:
            return self.cerrar()
        self.v.after(300, self._vigilar)

    def cerrar(self):
        if MenuFlotante.abierto is self:
            MenuFlotante.abierto = None
        try:
            self.v.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- objetos: plato, premio, estambre

class Objeto:
    def __init__(self, manada, tipo, x):
        self.manada = manada
        self.tipo = tipo  # comida, premio, estambre
        self.escala = manada.escala_objetos
        self.porciones = 3 if tipo == "comida" else 1
        self.vx = 0.0
        self.creado = self.tocado = time.monotonic()
        self.comiendo = set()
        self.fase = 0
        nombre = {"comida": "plato", "premio": "pescado", "estambre": "estambre"}[tipo]
        self.fotos = {}
        for n in ([nombre] + (["plato_vacio"] if tipo == "comida" else []) + (["estambre2"] if tipo == "estambre" else [])):
            self.fotos[n] = a_foto(michi_arte.dibujar_objeto(manada.sprites, n, self.escala))
        img = michi_arte.dibujar_objeto(manada.sprites, nombre, self.escala)
        self.ancho, self.alto = img.size
        self.v = ventana_transparente(manada.raiz)
        self.etiqueta = tk.Label(self.v, bg=CLAVE, bd=0, highlightthickness=0, image=self.fotos[nombre],
                                 cursor="hand2" if tipo == "estambre" else "")
        self.etiqueta.pack()
        self.x = float(x)
        if tipo == "estambre":
            self.arrastre = None
            self.etiqueta.bind("<ButtonPress-1>", self._presionar)
            self.etiqueta.bind("<B1-Motion>", self._mover)
            self.etiqueta.bind("<ButtonRelease-1>", self._soltar)
        self.colocar()
        if not manada.visible():
            self.v.withdraw()

    def centro(self):
        return self.x + self.ancho / 2

    def colocar(self):
        izq, _, der, abajo = self.manada.area
        self.x = max(izq, min(self.x, der - self.ancho))
        self.v.geometry(f"{self.ancho}x{self.alto}+{int(self.x)}+{int(abajo - self.alto)}")

    def imagen(self, nombre):
        self.etiqueta.configure(image=self.fotos[nombre])

    def rodar(self, dt):
        """Física simple del estambre: rueda, frena y rebota en los bordes."""
        if abs(self.vx) < 4:
            self.vx = 0
            return False
        self.x += self.vx * dt
        self.vx *= 0.94 ** (dt * 30)
        izq, _, der, _ = self.manada.area
        if self.x <= izq or self.x >= der - self.ancho:
            self.vx = -self.vx * 0.6
        self.colocar()
        self.fase += abs(self.vx) * dt
        self.imagen("estambre" if int(self.fase / 12) % 2 == 0 else "estambre2")
        return True

    # arrastrar y lanzar el estambre con el mouse
    def _presionar(self, e):
        self.arrastre = [(time.monotonic(), e.x_root)]
        self.vx = 0

    def _mover(self, e):
        if self.arrastre is None:
            return
        self.arrastre.append((time.monotonic(), e.x_root))
        self.arrastre = self.arrastre[-5:]
        self.x = e.x_root - self.ancho / 2
        self.colocar()
        self.tocado = time.monotonic()

    def _soltar(self, e):
        if self.arrastre and len(self.arrastre) >= 2:
            (t0, x0), (t1, x1) = self.arrastre[0], self.arrastre[-1]
            self.vx = max(-1500, min(1500, (x1 - x0) / max(0.016, t1 - t0)))
        self.arrastre = None
        self.tocado = time.monotonic()
        self.manada.despertar()

    def destruir(self):
        try:
            self.v.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- un gato

class MichiEscritorio:
    def __init__(self, manada, config, principal=False):
        self.manada = manada
        self.raiz = manada.raiz
        self.sprites = manada.sprites
        self.principal = principal
        self.vivo = True
        self.ventana = None
        self.globo = None
        self.cache = {}
        self.estado_asistente = None
        self.arrastrando = None
        self.clic_pendiente = None
        self.dir = random.choice((1, -1))
        self.anim = "sentado"
        self.cuadro = 0
        self.ultimo_cuadro = 0
        self.hasta = 0
        self.objetivo = None
        self.meta = None          # {"tipo": "comida"|"premio"|"estambre"|"amigo", ...}
        self.rapido = False
        self.ultimo_tick = time.monotonic()
        self.ultimo_hambre = time.monotonic() - random.uniform(0, 600)
        self.aplicar_config(config)
        izq, _, der, _ = manada.area
        self.x = float(random.randint(izq + 40, max(izq + 41, der - self.ancho - 40)))
        self._crear_ventana()
        self.elegir_accion()
        self.raiz.after(random.randint(100, 400), self._tick)

    @property
    def id(self):
        return self.cfg.get("id", "principal")

    # ---------- configuración
    def aplicar_config(self, config):
        self.cfg = dict(michi_arte.MICHI_POR_DEFECTO)
        self.cfg.update(config or {})
        self.colores = michi_arte.paleta(self.cfg)
        self.escala = max(1, round(int(self.cfg.get("tamano", 3)) * factor_pantalla(self.raiz)))
        self.ancho = self.sprites["ancho"] * self.escala
        self.alto = self.sprites["alto"] * self.escala
        self.cache.clear()
        if self.ventana:
            self.ventana.geometry(f"{self.ancho}x{self.alto}")
            self._pintar()
            self.actualizar_visibilidad()

    def _imagen(self, anim, i, espejo):
        clave = (anim, i, espejo)
        if clave not in self.cache:
            cuadro = self.sprites["animaciones"][anim]["cuadros"][i]
            self.cache[clave] = a_foto(michi_arte.dibujar(cuadro, self.colores, self.cfg.get("accesorio", "ninguno"),
                                                          self.escala, espejo))
        return self.cache[clave]

    # ---------- ventana
    def _crear_ventana(self):
        v = ventana_transparente(self.raiz)
        self.etiqueta = tk.Label(v, bg=CLAVE, bd=0, highlightthickness=0, cursor="hand2")
        self.etiqueta.pack()
        self.etiqueta.bind("<ButtonPress-1>", self._presionar)
        self.etiqueta.bind("<B1-Motion>", self._mover)
        self.etiqueta.bind("<ButtonRelease-1>", self._soltar)
        self.etiqueta.bind("<Double-Button-1>", self._doble_clic)
        self.etiqueta.bind("<Button-3>", lambda e: self.manada.al_menu(e.x_root, e.y_root))
        self.ventana = v
        self._colocar()
        self._pintar()
        self.actualizar_visibilidad()

    def _colocar(self):
        izq, _, der, abajo = self.manada.area
        self.x = max(izq, min(self.x, der - self.ancho))
        y = abajo - self.alto + self.escala  # la fila de contorno de las patas queda justo sobre la barra
        self.ventana.geometry(f"{self.ancho}x{self.alto}+{int(self.x)}+{int(y)}")
        if self.globo:
            self._colocar_globo()

    def _pintar(self):
        anim = self.sprites["animaciones"][self.anim]
        self.cuadro %= len(anim["cuadros"])
        self.etiqueta.configure(image=self._imagen(self.anim, self.cuadro, self.dir < 0))

    def visible(self):
        return self.manada.visible() and self.cfg.get("en_barra_windows", True)

    def actualizar_visibilidad(self):
        if not self.ventana:
            return
        if self.visible():
            self.ventana.deiconify()
            self.ventana.attributes("-topmost", True)
        else:
            self.ventana.withdraw()
            self._cerrar_globo()

    def centro(self):
        return self.x + self.ancho / 2

    # ---------- comportamiento
    def _poner(self, anim, dur=None):
        self.anim, self.cuadro, self.ultimo_cuadro = anim, 0, time.monotonic()
        self.hasta = time.monotonic() + dur if dur else 0
        self._pintar()

    def ocupado(self):
        return bool(self.estado_asistente or self.arrastrando)

    def ir_a(self, x_destino, rapido=False):
        izq, _, der, _ = self.manada.area
        self.objetivo = max(izq, min(x_destino, der - self.ancho))
        self.dir = 1 if self.objetivo > self.x else -1
        self.rapido = rapido
        self._poner("caminar")

    def elegir_accion(self):
        if self.estado_asistente:
            return
        self.meta, self.rapido = None, False
        pesos = dict(PESOS.get(self.cfg.get("actividad"), PESOS["normal"]))
        if len(self.manada.gatos) < 2:
            pesos.pop("amigo", None)
        accion = random.choices(list(pesos), weights=list(pesos.values()))[0]
        if accion == "caminar":
            izq, _, der, _ = self.manada.area
            destino = random.uniform(izq + 10, der - self.ancho - 10)
            if abs(destino - self.x) < self.ancho:
                destino = self.x + (self.ancho * 2 if destino < self.x else -self.ancho * 2)
            self.ir_a(destino)
        elif accion == "amigo":
            amigo = random.choice([g for g in self.manada.gatos if g is not self])
            self.meta = {"tipo": "amigo", "gato": amigo}
            lado = -1 if amigo.x > self.x else 1
            self.ir_a(amigo.x + lado * amigo.ancho * 0.7, rapido=random.random() < 0.5)
        else:
            self.objetivo = None
            a, b = DURACION.get(accion, (0, 0))
            self._poner(accion, random.uniform(a, b) if b else None)

    def poner_estado(self, estado):
        """estado del asistente: escuchando, reunion, procesando o None."""
        if estado == self.estado_asistente:
            return
        self.estado_asistente = estado
        if estado:
            self.objetivo, self.meta = None, None
            self._poner(ESTADOS[estado])
        else:
            self.elegir_accion()

    def reaccion(self, texto=None, feliz=True, segundos=5):
        if not self.estado_asistente:
            self.objetivo, self.meta = None, None
            self._poner("festejar" if feliz else "sentado", None if feliz else 4)
        if texto and self.visible():
            self.mostrar_globo(texto, segundos)

    def alerta(self):
        """Llegó la hora de algo: para las orejas un ratito."""
        if not self.estado_asistente:
            self.objetivo, self.meta = None, None
            self._poner("escuchar", 8)

    def interesarse(self, obj):
        """El manada le ofrece comida, premio o estambre."""
        if self.ocupado() or (self.meta and self.meta.get("tipo") in ("comida", "premio")):
            return
        self.meta = {"tipo": obj.tipo, "obj": obj}
        self._acercarse(obj, rapido=True)  # a la comida se va corriendo

    def _acercarse(self, obj, rapido=False):
        # se para al lado del objeto, mirándolo
        if obj.centro() >= self.centro():
            destino = obj.x - self.ancho * 0.72
        else:
            destino = obj.x + obj.ancho - self.ancho * 0.28
        self.ir_a(destino, rapido)

    def _llego(self):
        """Terminó de caminar: ¿a qué iba?"""
        meta = self.meta
        if not meta:
            return self.elegir_accion()
        tipo = meta["tipo"]
        if tipo == "amigo":
            amigo = meta["gato"]
            self.dir = 1 if amigo.centro() > self.centro() else -1
            self._poner(random.choice(["jugar", "mimos", "sentado"]), 3)
            if not amigo.ocupado() and not amigo.meta and random.random() < 0.7:
                amigo.dir = -self.dir
                amigo._poner(random.choice(["jugar", "festejar", "mimos"]), 3)
            self.meta = None
            return
        obj = meta["obj"]
        if obj not in self.manada.objetos:
            return self.elegir_accion()
        self.dir = 1 if obj.centro() >= self.centro() else -1
        if tipo == "comida":
            if obj.porciones <= 0:
                return self.elegir_accion()
            obj.porciones -= 1
            obj.comiendo.add(self)
            meta["hasta"] = time.monotonic() + 6
            self._poner("comer")
        elif tipo == "premio":
            meta["hasta"] = time.monotonic() + 2.5
            self._poner("comer")
        elif tipo == "estambre":
            if abs(obj.centro() - (self.x + (self.ancho if self.dir > 0 else 0))) < self.ancho * 0.6:
                obj.vx = self.dir * random.uniform(220, 480) * factor_pantalla(self.raiz)
                obj.tocado = time.monotonic()
                self.manada.cuidar(self, "jugar")
                self.manada.despertar()
            meta["hasta"] = time.monotonic() + 0.6
            self._poner("jugar")

    def _seguir_meta(self, ahora):
        """Mientras come o juega."""
        meta = self.meta
        if not meta or "hasta" not in meta or ahora < meta["hasta"]:
            return
        tipo, obj = meta["tipo"], meta.get("obj")
        if tipo == "comida":
            if obj:
                obj.comiendo.discard(self)
            self.manada.cuidar(self, "comida")
            self.meta = None
            self._poner("mimos", 3)
        elif tipo == "premio":
            self.manada.quitar(obj)
            self.manada.cuidar(self, "premio")
            self.meta = None
            self._poner("festejar")
        elif tipo == "estambre":
            if obj in self.manada.objetos and ahora - obj.tocado < 60 and random.random() < 0.85:
                del meta["hasta"]
                self._acercarse(obj, rapido=True)
            else:
                self.meta = None
                self._poner("sentado", 4)

    def _tick(self):
        if not self.vivo:
            return
        ahora = time.monotonic()
        dt = min(0.25, ahora - self.ultimo_tick)
        self.ultimo_tick = ahora
        espera = 1000
        try:
            if self.visible() and not self.arrastrando:
                anim = self.sprites["animaciones"][self.anim]
                fps = anim["fps"] * (1.6 if self.rapido and self.anim == "caminar" else 1)
                if ahora - self.ultimo_cuadro >= 1 / fps:
                    self.ultimo_cuadro = ahora
                    self.cuadro += 1
                    if self.cuadro >= len(anim["cuadros"]):
                        if self.anim in UNA_VEZ and not self.estado_asistente and not self.meta:
                            self.elegir_accion()
                            anim = self.sprites["animaciones"][self.anim]
                        self.cuadro %= len(anim["cuadros"])
                    self._pintar()
                if self.anim == "caminar" and self.objetivo is not None:
                    # si va detrás del estambre, lo sigue aunque se mueva
                    if self.meta and self.meta["tipo"] == "estambre" and "hasta" not in self.meta:
                        obj = self.meta["obj"]
                        if obj in self.manada.objetos:
                            destino = obj.x - self.ancho * 0.72 if obj.centro() >= self.centro() else obj.x + obj.ancho - self.ancho * 0.28
                            izq, _, der, _ = self.manada.area
                            self.objetivo = max(izq, min(destino, der - self.ancho))
                            self.dir = 1 if self.objetivo > self.x else -1
                    velocidad = (11 * 2.4 if self.rapido else 11) * self.escala
                    self.x += self.dir * velocidad * dt
                    if (self.dir > 0 and self.x >= self.objetivo) or (self.dir < 0 and self.x <= self.objetivo):
                        self.x = self.objetivo
                        self.objetivo = None
                        self._llego()
                    self._colocar()
                    espera = 33
                else:
                    espera = int(1000 / fps)
                    if self.meta and "hasta" in self.meta:
                        espera = min(espera, 100)
                        self._seguir_meta(ahora)
                if self.hasta and ahora >= self.hasta and not self.estado_asistente and not self.meta:
                    self.elegir_accion()
        except Exception:
            log.exception("Error en el michi")
        self.raiz.after(espera, self._tick)

    # ---------- mouse: clic = mimos, doble clic = abrir notas, arrastrar = mover
    def _presionar(self, e):
        self.arrastrando = (e.x_root, self.x, False)

    def _mover(self, e):
        if not self.arrastrando:
            return
        inicio, x0, movido = self.arrastrando
        if abs(e.x_root - inicio) > 4 or movido:
            if not movido:
                self._poner("escuchar")
            self.arrastrando = (inicio, x0, True)
            self.x = x0 + (e.x_root - inicio)
            self._colocar()

    def _soltar(self, e):
        if not self.arrastrando:
            return
        movido = self.arrastrando[2]
        self.arrastrando = None
        if movido:
            self.objetivo, self.meta = None, None
            if not self.estado_asistente:
                self._poner("sentado", 6)
            else:
                self._poner(ESTADOS[self.estado_asistente])
        else:
            if self.clic_pendiente:
                self.raiz.after_cancel(self.clic_pendiente)
            self.clic_pendiente = self.raiz.after(280, self._mimos)

    def _doble_clic(self, e):
        if self.clic_pendiente:
            self.raiz.after_cancel(self.clic_pendiente)
            self.clic_pendiente = None
        self.manada.al_clic()

    def _mimos(self):
        self.clic_pendiente = None
        if self.estado_asistente:
            return
        self.objetivo, self.meta = None, None
        self._poner("mimos", 3)
        self.manada.cuidar(self, "mimos")

    # ---------- globo de diálogo
    def mostrar_globo(self, texto, segundos=5):
        self._cerrar_globo()
        g = tk.Toplevel(self.raiz)
        g.overrideredirect(True)
        g.attributes("-topmost", True)
        g.configure(bg="#3a3d42")
        marco = tk.Frame(g, bg="#1f2124")
        marco.pack(padx=1, pady=1)
        tk.Label(marco, text=self.cfg.get("nombre", "Michi"), bg="#1f2124", fg="#a9adb3",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(marco, text=texto[:280], bg="#1f2124", fg="#f2f2f2", font=("Segoe UI", 9),
                 wraplength=int(240 * factor_pantalla(self.raiz)), justify="left").pack(padx=10, pady=(0, 8))
        g.bind("<Button-1>", lambda e: self._cerrar_globo())
        self.globo = g
        g.update_idletasks()
        self._colocar_globo()
        g.after(int(segundos * 1000), lambda gg=g: self._cerrar_globo(gg))

    def _colocar_globo(self):
        g = self.globo
        if not g:
            return
        izq, _, der, abajo = self.manada.area
        w, h = g.winfo_reqwidth(), g.winfo_reqheight()
        x = int(self.x + self.ancho / 2 - w / 2)
        x = max(izq + 4, min(x, der - w - 4))
        y = int(abajo - self.alto - h + self.escala * 4)
        g.geometry(f"+{x}+{y}")

    def _cerrar_globo(self, cual=None):
        if self.globo and (cual is None or cual is self.globo):
            try:
                self.globo.destroy()
            except Exception:
                pass
            self.globo = None

    def destruir(self):
        self.vivo = False
        self._cerrar_globo()
        try:
            self.ventana.destroy()
        except Exception:
            pass
        self.ventana = None


# ---------------------------------------------------------------- todos los michis juntos

class Manada:
    MAXIMO = 8

    def __init__(self, raiz, configs, al_clic, al_menu):
        self.raiz = raiz
        self.al_clic = al_clic
        self.al_menu = al_menu
        self.sprites = michi_arte.cargar_sprites()
        self.area = area_de_trabajo(raiz)
        self.motivos_ocultar = set()
        self.gatos = []
        self.objetos = []
        self.ultima_revision = 0
        self.ultimo_tick = time.monotonic()
        self.tick_pendiente = None
        self.patita = None
        self.aplicar_configs(configs)
        self._crear_patita()
        self.despertar()

    # ---------- botón de patita sobre la barra de Windows (abre el menú del juego)
    def _crear_patita(self):
        escala = max(2, round(2 * factor_pantalla(self.raiz)))
        self.fotos_patita = {k: a_foto(dibujar_huella(escala, k == "encima")) for k in ("normal", "encima")}
        v = ventana_transparente(self.raiz)
        et = tk.Label(v, image=self.fotos_patita["normal"], bg=CLAVE, bd=0, highlightthickness=0, cursor="hand2")
        et.pack()
        et.bind("<Enter>", lambda e: et.configure(image=self.fotos_patita["encima"]))
        et.bind("<Leave>", lambda e: et.configure(image=self.fotos_patita["normal"]))
        # se abre al soltar el clic (así Windows no cierra el menú en el mismo clic)
        et.bind("<ButtonRelease-1>", lambda e: self._abrir_menu_patita())
        et.bind("<ButtonRelease-3>", lambda e: self._abrir_menu_patita())
        self.patita = v
        self.etiqueta_patita = et
        self.tam_patita = (len(HUELLA[0]) * escala, len(HUELLA) * escala)
        self._colocar_patita()
        self._visibilidad()

    def _abrir_menu_patita(self):
        try:
            _, _, der, abajo = self.area
            w, h = self.tam_patita
            x = self.patita.winfo_rootx() + w // 2
            y = self.patita.winfo_rooty()
            self.al_menu(x, y, True)
        except Exception:
            log.exception("No se pudo abrir el menú de la patita")

    def _colocar_patita(self):
        if not self.patita:
            return
        _, _, der, abajo = self.area
        w, h = self.tam_patita
        margen = int(6 * factor_pantalla(self.raiz))
        self.patita.geometry(f"{w}x{h}+{der - w - margen}+{abajo - h - margen // 2}")

    # ---------- compatibilidad con el asistente (habla con el michi principal)
    @property
    def principal(self):
        return self.gatos[0] if self.gatos else None

    def poner_estado(self, estado):
        if self.principal:
            self.principal.poner_estado(estado)

    def reaccion(self, texto=None, feliz=True, segundos=5):
        if self.principal:
            self.principal.reaccion(texto, feliz, segundos)

    def alerta(self):
        for g in self.gatos:
            if g is self.principal or random.random() < 0.5:
                g.alerta()

    def visible(self):
        return not self.motivos_ocultar

    def ocultar(self, motivo):
        self.motivos_ocultar.add(motivo)
        self._visibilidad()

    def mostrar(self, motivo):
        self.motivos_ocultar.discard(motivo)
        self._visibilidad()

    def _visibilidad(self):
        if self.patita:
            if self.visible() and self.gatos:
                self.patita.deiconify()
                self.patita.attributes("-topmost", True)
            else:
                self.patita.withdraw()
        for g in self.gatos:
            g.actualizar_visibilidad()
        for o in self.objetos:
            (o.v.deiconify if self.visible() else o.v.withdraw)()

    def aplicar_config(self, config):  # por compatibilidad: un solo michi
        self.aplicar_configs([config])

    def aplicar_configs(self, configs):
        configs = [c for c in (configs or []) if c.get("activo", True)][:self.MAXIMO]
        self.escala_objetos = max(1, round(int((configs[0] if configs else {}).get("tamano", 3))
                                           * factor_pantalla(self.raiz)))
        por_id = {g.id: g for g in self.gatos}
        nuevos = []
        for i, cfg in enumerate(configs):
            g = por_id.pop(cfg.get("id", "principal"), None)
            if g:
                g.aplicar_config(cfg)
            else:
                g = MichiEscritorio(self, cfg, principal=(i == 0))
            g.principal = i == 0
            nuevos.append(g)
        for g in por_id.values():  # los que ya no están
            g.destruir()
        estado_previo = self.principal.estado_asistente if self.principal else None
        self.gatos = nuevos
        if self.principal and estado_previo:
            self.principal.poner_estado(estado_previo)
        if self.patita:
            self._visibilidad()

    # ---------- juego
    def cuidar(self, gato, accion):
        try:
            michi_arte.cuidar(gato.id, accion)
        except Exception:
            log.exception("No se pudo guardar el estado del michi")

    def _x_para_objeto(self, x):
        izq, _, der, _ = self.area
        if x is None:
            x = random.uniform(izq + (der - izq) * 0.25, izq + (der - izq) * 0.75)
        return x

    def dar(self, tipo, x=None):
        """tipo: comida, premio o estambre. x: dónde ponerlo (por defecto, en el medio)."""
        if tipo == "estambre":
            for o in [o for o in self.objetos if o.tipo == "estambre"]:
                self.quitar(o)
        obj = Objeto(self, tipo, self._x_para_objeto(x))
        obj.x -= obj.ancho / 2
        obj.colocar()
        self.objetos.append(obj)
        estado = michi_arte.estado_michis([g.id for g in self.gatos])
        candidatos = [g for g in self.gatos if not g.ocupado()]
        if tipo == "premio":
            candidatos.sort(key=lambda g: abs(g.centro() - obj.centro()))
            candidatos = candidatos[:1]
        elif tipo == "comida":
            con_hambre = [g for g in candidatos if estado[g.id]["hambre"] > 15]
            candidatos = (con_hambre or candidatos)[:3]
        for g in candidatos:
            g.interesarse(obj)
        self.despertar()

    def quitar(self, obj):
        if obj in self.objetos:
            self.objetos.remove(obj)
        obj.destruir()
        for g in self.gatos:
            if g.meta and g.meta.get("obj") is obj:
                g.meta = None
                if not g.ocupado():
                    g.elegir_accion()

    def guardar_estambre(self):
        for o in [o for o in self.objetos if o.tipo == "estambre"]:
            self.quitar(o)

    def hay_estambre(self):
        return any(o.tipo == "estambre" for o in self.objetos)

    def despertar(self):
        """Programa el siguiente tick de la manada (más rápido si algo se mueve)."""
        if self.tick_pendiente:
            self.raiz.after_cancel(self.tick_pendiente)
        self.tick_pendiente = self.raiz.after(30, self._tick)

    def _tick(self):
        self.tick_pendiente = None
        ahora = time.monotonic()
        dt = min(0.1, ahora - self.ultimo_tick)
        self.ultimo_tick = ahora
        espera = 1000
        try:
            if ahora - self.ultima_revision > 2:
                self.ultima_revision = ahora
                nueva = area_de_trabajo(self.raiz)
                if nueva != self.area:
                    self.area = nueva
                    for g in self.gatos:
                        g._colocar()
                    for o in self.objetos:
                        o.colocar()
                    self._colocar_patita()
                propias = set()
                for g in self.gatos:
                    try:
                        propias.add(int(g.ventana.wm_frame(), 16))
                    except Exception:
                        pass
                if hay_pantalla_completa(propias):
                    self.ocultar("pantalla_completa")
                else:
                    self.mostrar("pantalla_completa")
                self._revisar_hambre()

            for o in list(self.objetos):
                o.comiendo = {g for g in o.comiendo if g.meta and g.meta.get("obj") is o}
                if o.tipo == "estambre":
                    if o.rodar(dt):
                        espera = 30
                    # los michis juguetones se animan a perseguirlo
                    if ahora - o.tocado < 45:
                        for g in self.gatos:
                            if not g.ocupado() and not g.meta and random.random() < 0.004 * (2 if g.cfg.get("actividad") == "jugueton" else 1):
                                g.interesarse(o)
                    elif ahora - o.tocado > 180:
                        self.quitar(o)
                elif o.tipo == "comida" and o.porciones <= 0 and not o.comiendo:
                    o.imagen("plato_vacio")
                    if not hasattr(o, "vacio_desde"):
                        o.vacio_desde = ahora
                    elif ahora - o.vacio_desde > 6:
                        self.quitar(o)
                elif ahora - o.creado > 120 and not o.comiendo:
                    self.quitar(o)
            if any(o.tipo == "estambre" for o in self.objetos):
                espera = min(espera, 100)
        except Exception:
            log.exception("Error en la manada")
        self.tick_pendiente = self.raiz.after(espera, self._tick)

    def _revisar_hambre(self):
        """De vez en cuando, un michi con hambre lo dice (máximo cada 25 minutos)."""
        if not self.visible() or not self.gatos:
            return
        ahora = time.monotonic()
        estado = michi_arte.estado_michis([g.id for g in self.gatos])
        for g in self.gatos:
            e = estado[g.id]
            if e["hambre"] >= 75 and ahora - g.ultimo_hambre > 25 * 60 and not g.ocupado() and not g.meta:
                g.ultimo_hambre = ahora
                g._poner("sentado", 6)
                g.mostrar_globo(random.choice(FRASES_HAMBRE) + "\n(clic derecho > Darles comida)", 6)
                break
