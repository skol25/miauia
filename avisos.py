# -*- coding: utf-8 -*-
"""Avisos: te recuerda tus citas y tareas cuando llega la hora (y un rato antes),
y te da un resumen del día por la mañana."""
import datetime
import logging
import os
import tkinter as tk

import comun
import michi_arte

log = logging.getLogger("avisos")

FONDO = "#1f2124"
TEXTO = "#f2f2f2"
SUAVE = "#a9adb3"
ACENTO = "#2f6fdf"


def _cuando(nota):
    try:
        return datetime.datetime.strptime(f"{nota['fecha']} {nota['hora']}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _clave(nota):
    return f"{nota['texto']}|{nota['fecha']} {nota['hora']}"


class Avisador:
    def __init__(self, raiz, cfg, factor=1.0, al_avisar=None, hablar=None):
        self.raiz = raiz
        self.cfg = cfg
        self.f = factor
        self.al_avisar = al_avisar  # para que el michi reaccione
        self.hablar = hablar
        self.abiertas = []
        self.raiz.after(6000, self.revisar)

    # ---------- revisión periódica
    def revisar(self):
        try:
            self._revisar()
        except Exception:
            log.exception("Error revisando avisos")
        self.raiz.after(30000, self.revisar)

    def _revisar(self):
        ahora = comun.ahora()
        datos = comun.leer_avisados()
        hechos, pospuestos = datos.setdefault("hechos", {}), datos.setdefault("pospuestos", {})
        cambios = False
        antes = int(self.cfg.get("avisar_minutos_antes") or 0)
        notas = [n for n in comun.listar_notas() if n["casilla"] and not n["hecho"]]

        for n in notas:
            t = _cuando(n)
            if not t:
                continue
            clave = _clave(n)
            if clave in pospuestos:
                continue
            if antes and t - datetime.timedelta(minutes=antes) <= ahora < t and clave + ":antes" not in hechos:
                faltan = max(1, round((t - ahora).total_seconds() / 60))
                self.mostrar(n, f"En {faltan} minuto{'s' if faltan != 1 else ''}" if faltan < 60 else "En 1 hora")
                hechos[clave + ":antes"] = ahora.isoformat()
                cambios = True
            elif t <= ahora < t + datetime.timedelta(hours=2) and clave + ":hora" not in hechos:
                tarde = ahora - t > datetime.timedelta(minutes=5)
                self.mostrar(n, "Se te pasó la hora" if tarde else "¡Es la hora!", urgente=True)
                hechos[clave + ":hora"] = ahora.isoformat()
                hechos[clave + ":antes"] = ahora.isoformat()
                cambios = True

        for clave, cuando in list(pospuestos.items()):
            if cuando <= ahora.isoformat():
                del pospuestos[clave]
                cambios = True
                nota = next((n for n in notas if _clave(n) == clave), None)
                if nota:
                    self.mostrar(nota, "Te lo recuerdo otra vez", urgente=True)

        hora_resumen = (self.cfg.get("resumen_diario") or "").strip()
        clave_dia = f"resumen:{ahora:%Y-%m-%d}"
        if hora_resumen and clave_dia not in hechos and f"{ahora:%H:%M}" >= hora_resumen:
            hechos[clave_dia] = ahora.isoformat()
            cambios = True
            hoy = f"{ahora:%Y-%m-%d}"
            del_dia = sorted([n for n in notas if n["fecha"] and n["fecha"] <= hoy],
                             key=lambda n: (n["fecha"] < hoy, n["hora"] or "99"))
            if del_dia:
                self.resumen(del_dia, hoy)

        if cambios:
            comun.guardar_avisados(datos)

    # ---------- ventanas
    def _base(self):
        v = tk.Toplevel(self.raiz)
        v.overrideredirect(True)
        v.attributes("-topmost", True)
        v.configure(bg="#3a3d42")
        v.withdraw()
        return v

    def _colocar(self, v):
        """Abajo a la derecha, apilando los avisos que ya estén abiertos."""
        v.update_idletasks()
        ancho = int(380 * self.f)
        alto = max(v.winfo_reqheight(), int(110 * self.f))
        _, _, der, abajo = self._area()
        ocupado = sum(w.winfo_height() + int(10 * self.f) for w in self.abiertas if w.winfo_exists())
        v.geometry(f"{ancho}x{alto}+{der - ancho - int(16 * self.f)}+{abajo - alto - int(16 * self.f) - ocupado}")
        self.abiertas.append(v)
        v.deiconify()

    def _area(self):
        try:
            from michi import area_de_trabajo
            return area_de_trabajo(self.raiz)
        except Exception:
            return 0, 0, self.raiz.winfo_screenwidth(), self.raiz.winfo_screenheight() - 48

    def _cerrar(self, v):
        if v in self.abiertas:
            self.abiertas.remove(v)
        try:
            v.destroy()
        except Exception:
            pass

    def _gato(self, padre, anim="escuchar"):
        try:
            from PIL import ImageTk, Image
            cfg = self.cfg.get("michi") or {}
            sprites = michi_arte.cargar_sprites()
            img = michi_arte.dibujar(sprites["animaciones"][anim]["cuadros"][0], michi_arte.paleta(cfg),
                                     cfg.get("accesorio", "ninguno"), max(2, round(2 * self.f)))
            fondo = Image.new("RGBA", img.size, FONDO)
            fondo.alpha_composite(img)
            foto = ImageTk.PhotoImage(fondo)
            etiqueta = tk.Label(padre, image=foto, bg=FONDO, bd=0)
            etiqueta.image = foto
            return etiqueta
        except Exception:
            log.exception("No se pudo dibujar el michi del aviso")
            return tk.Label(padre, text="⏰", bg=FONDO, fg=TEXTO, font=("Segoe UI Emoji", 20))

    def _boton(self, padre, texto, accion, color="#3a3d42"):
        return tk.Button(padre, text=texto, command=accion, bg=color, fg=TEXTO, relief="flat", bd=0,
                         activebackground="#4a4e54", activeforeground=TEXTO, padx=10, pady=3,
                         font=("Segoe UI", 9), cursor="hand2")

    def _sonar(self):
        if not self.cfg.get("sonido_avisos", True) or os.name != "nt":
            return
        try:
            import winsound
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass

    def mostrar(self, nota, encabezado, urgente=False):
        v = self._base()
        marco = tk.Frame(v, bg=FONDO)
        marco.pack(fill="both", expand=True, padx=1, pady=1)
        self._gato(marco).pack(side="left", padx=(10, 4), pady=10, anchor="n")
        cuerpo = tk.Frame(marco, bg=FONDO)
        cuerpo.pack(side="left", fill="both", expand=True, padx=(4, 12), pady=(10, 8))
        tk.Label(cuerpo, text=f"⏰ {encabezado}", bg=FONDO, fg="#f5a524" if urgente else SUAVE,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(cuerpo, text=nota["texto"], bg=FONDO, fg=TEXTO, font=("Segoe UI", 11),
                 wraplength=int(250 * self.f), justify="left", anchor="w").pack(fill="x", pady=(2, 0))
        meta = f"{comun.NOMBRE_TIPO.get(nota['tipo'], 'Tarea')} · {nota['hora']}"
        if nota.get("proyecto"):
            meta += f" · {nota['proyecto']}"
        tk.Label(cuerpo, text=meta, bg=FONDO, fg=SUAVE, font=("Segoe UI", 8), anchor="w").pack(fill="x")
        fila = tk.Frame(cuerpo, bg=FONDO)
        fila.pack(fill="x", side="bottom")

        def listo():
            linea = next((n["linea"] for n in comun.listar_notas() if _clave(n) == _clave(nota) and not n["hecho"]), None)
            if linea:
                nueva = dict(comun.parsear_linea(linea), hecho=True, fecha_hecho="")
                comun.reemplazar_linea(linea, comun.componer_linea(nueva))
            self._cerrar(v)

        def posponer():
            datos = comun.leer_avisados()
            datos.setdefault("pospuestos", {})[_clave(nota)] = (comun.ahora() + datetime.timedelta(minutes=10)).isoformat()
            comun.guardar_avisados(datos)
            self._cerrar(v)

        self._boton(fila, "Cerrar", lambda: self._cerrar(v)).pack(side="right")
        self._boton(fila, "Posponer 10 min", posponer).pack(side="right", padx=4)
        self._boton(fila, "Listo ✓", listo, color=ACENTO).pack(side="right")
        self._colocar(v)
        v.after(15 * 60 * 1000, lambda: self._cerrar(v))
        self._sonar()
        if self.al_avisar:
            self.al_avisar()
        if self.hablar and self.cfg.get("voz_avisos"):
            self.hablar(f"{encabezado}. {nota['texto']}")

    def resumen(self, notas, hoy):
        filas = []
        for n in notas[:6]:
            cuando = "atrasada" if n["fecha"] < hoy else (n["hora"] or "hoy")
            filas.append(f"•  {n['texto']}  ({cuando})")
        if len(notas) > 6:
            filas.append(f"… y {len(notas) - 6} más")
        v = self._base()
        marco = tk.Frame(v, bg=FONDO)
        marco.pack(fill="both", expand=True, padx=1, pady=1)
        self._gato(marco, "festejar").pack(side="left", padx=(10, 4), pady=10, anchor="n")
        cuerpo = tk.Frame(marco, bg=FONDO)
        cuerpo.pack(side="left", fill="both", expand=True, padx=(4, 12), pady=(10, 8))
        nombre = (self.cfg.get("michi") or {}).get("nombre", "Michi")
        tk.Label(cuerpo, text=f"¡Buenos días! Soy {nombre} 🐾", bg=FONDO, fg=SUAVE,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(cuerpo, text=f"Hoy tienes {len(notas)} {'cosa' if len(notas) == 1 else 'cosas'}:",
                 bg=FONDO, fg=TEXTO, font=("Segoe UI", 11), anchor="w").pack(fill="x", pady=(2, 4))
        tk.Label(cuerpo, text="\n".join(filas), bg=FONDO, fg=TEXTO, font=("Segoe UI", 9),
                 wraplength=int(260 * self.f), justify="left", anchor="w").pack(fill="x")
        self._boton(cuerpo, "Entendido", lambda: self._cerrar(v), color=ACENTO).pack(side="bottom", anchor="e")
        self._colocar(v)
        v.after(20 * 60 * 1000, lambda: self._cerrar(v))
        self._sonar()
        if self.al_avisar:
            self.al_avisar()

    def prueba(self):
        falsa = {"texto": "Así se verán tus avisos", "tipo": "cita", "hora": f"{comun.ahora():%H:%M}",
                 "proyecto": "", "fecha": f"{comun.ahora():%Y-%m-%d}", "linea": ""}
        self.mostrar(falsa, "Aviso de prueba")
