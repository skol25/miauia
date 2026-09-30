# -*- coding: utf-8 -*-
"""Colores del michi y dibujo de sus cuadros con Pillow."""
import json
import os

# huella rosita de Miauia (20x19): se usa en la barra, el ícono y el instalador
HUELLA = [
    '......oo....oo......',
    '.....oLPo..oLPo.....',
    '....oLPPPooLPPPo....',
    '....oPPPPooPPPPo....',
    '..oooDPPDooDPPDooo..',
    '.oLPooDDo..oDDooLPo.',
    'oLPPPooo....oooLPPPo',
    'oPPPPo........oPPPPo',
    'oDPPDo........oDPPDo',
    '.oDDo...oooo...oDDo.',
    '..oo..ooLPPPoo..oo..',
    '.....oLPPPPPPPo.....',
    '....oLPPPPPPPPPo....',
    '...oLPPPPPPPPPPPo...',
    '...oPPPPPPPPPPPPo...',
    '...oPPPPPPPPPPPPo...',
    '...oDPPPDPPDPPPDo...',
    '....oDDDoDDoDDDo....',
    '.....ooo.oo.ooo.....',
]

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_SPRITES = os.path.join(BASE, "michi.json")


def instalado():
    """True cuando Miauia se instaló con el instalador (no la carpeta de desarrollo)."""
    return os.path.exists(os.path.join(BASE, "instalado.txt"))


def carpeta_usuario():
    """Dónde viven las notas y la configuración. Instalado: %APPDATA%\\Miauia (así las
    actualizaciones nunca tocan tus datos). En desarrollo: la misma carpeta del programa."""
    if instalado():
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Miauia")
    return BASE


# huella pequeñita para íconos de 16 y 32 px (hecha a mano para que no se vea borrosa)
HUELLA_16 = [
    "................",
    "....oo....oo....",
    "...oLPo..oLPo...",
    "...oPPo..oPPo...",
    ".oo.oo....oo.oo.",
    "oLPo........oLPo",
    "oPPo..oooo..oPPo",
    ".oo..oLPPPo..oo.",
    "....oLPPPPPo....",
    "...oLPPPPPPPo...",
    "...oPPPPPPPPo...",
    "...oPPPPPPPPo...",
    "...oDDDoDDDDo...",
    "....ooo.oooo....",
    "................",
    "................",
]
PALETAS_HUELLA = {
    "rosa": {"o": "#3a222e", "P": "#f7a8c4", "L": "#ffd6e4", "D": "#d67a9e"},
    "rosa_claro": {"o": "#3a222e", "P": "#ffc2d8", "L": "#ffffff", "D": "#ef93b5"},
    "rojo": {"o": "#3a1416", "P": "#ef5a5f", "L": "#ffb3b5", "D": "#b8363b"},
    "ambar": {"o": "#3a2a10", "P": "#f5b340", "L": "#ffe0a3", "D": "#c98a1c"},
}


def icono_huella(color="rosa", lado=64):
    """La huella de Miauia centrada en un cuadrado (para íconos)."""
    from PIL import Image
    filas = HUELLA_16 if lado in (16, 32) else HUELLA
    colores = PALETAS_HUELLA[color]
    base = Image.new("RGBA", (len(filas[0]), len(filas)), (0, 0, 0, 0))
    for y, fila in enumerate(filas):
        for x, c in enumerate(fila):
            if c != ".":
                base.putpixel((x, y), _rgb(colores[c]) + (255,))
    esc = max(1, min(lado // base.width, lado // base.height))
    grande = base.resize((base.width * esc, base.height * esc), Image.NEAREST)
    lienzo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    lienzo.alpha_composite(grande, ((lado - grande.width) // 2, (lado - grande.height) // 2))
    return lienzo

MICHI_POR_DEFECTO = {
    "activo": True,
    "nombre": "Michi",
    "patron": "esmoquin",       # esmoquin, calcetines, solido, calico, atigrado, siames
    "pelaje": "#2b2b31",
    "manchas": "#f4f1ea",
    "color_extra": "#26262b",   # calicó: manchas negras · atigrado: rayas · siamés: puntas
    "ojos": "#c5e063",
    "nariz": "#f09ab0",
    "accesorio": "collar",      # ninguno, collar, lazo
    "color_accesorio": "#e5484d",
    "tamano": 3,
    "en_barra_windows": True,
    "en_app": True,
    "actividad": "normal",      # tranquilo, normal, jugueton
}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mezclar(a, b, t):
    a, b = _rgb(a), _rgb(b)
    return _hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def luminosidad(h):
    r, g, b = _rgb(h)
    return 0.299 * r + 0.587 * g + 0.114 * b


def paleta(cfg):
    """Letra del sprite -> color. La misma lógica está en interfaz.html."""
    p = dict(MICHI_POR_DEFECTO)
    p.update(cfg or {})
    pelaje, manchas = p["pelaje"], p["manchas"]
    oscuro = luminosidad(pelaje) < 90
    contorno = mezclar(pelaje, "#08080c", 0.8 if not oscuro else 0.6)
    patron = p["patron"]
    extra = p.get("color_extra") or "#26262b"
    cara = manchas if patron in ("esmoquin", "calico", "atigrado") else pelaje
    pecho = manchas if patron in ("esmoquin", "calico", "atigrado", "siames") else pelaje
    patitas = manchas if patron in ("esmoquin", "calcetines", "calico", "atigrado") else pelaje
    G = T = U = Q = pelaje
    if patron == "calico":
        G = U = Q = extra
    elif patron == "atigrado":
        T = U = extra
    elif patron == "siames":
        Q = cara = patitas = extra
    return {
        "G": G, "T": T, "U": U, "Q": Q,
        "o": contorno,
        "M": pelaje,
        "m": mezclar(pelaje, "#000000", 0.28),
        "H": mezclar(pelaje, "#ffffff", 0.22 if oscuro else 0.35),
        "S": cara,
        "B": pecho,
        "F": patitas,
        "b": mezclar(pecho, "#000000", 0.18),
        "E": p["ojos"],
        "P": "#15151a",
        "W": "#ffffff",
        "N": p["nariz"],
        "Z": "#cfd4dc",
        "R": "#e5484d",
        "K": "#5b8def",
        "k": "#3c63b0",
        "C": "#ff5c8a",
        "A": p["color_accesorio"],
        "Y": "#f2c94c",
    }


def cargar_sprites():
    with open(RUTA_SPRITES, "r", encoding="utf-8") as f:
        return json.load(f)


def dibujar(cuadro, colores, accesorio="ninguno", escala=3, espejo=False, fondo=None):
    """Devuelve una imagen de Pillow del cuadro."""
    from PIL import Image
    alto = len(cuadro["filas"])
    ancho = len(cuadro["filas"][0])
    img = Image.new("RGBA", (ancho, alto), fondo or (0, 0, 0, 0))
    px = img.load()
    for y, fila in enumerate(cuadro["filas"]):
        for x, c in enumerate(fila):
            if c != ".":
                px[x, y] = _rgb(colores[c]) + (255,)
    for x, y, c in cuadro.get("acc", {}).get(accesorio, []):
        # el accesorio solo se dibuja donde hay gato o justo al lado (no flota en el aire)
        px[x, y] = _rgb(colores[c]) + (255,)
    if espejo:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img.resize((ancho * escala, alto * escala), Image.NEAREST)


# ---------------------------------------------------------------- objetos y cuidados

COLORES_OBJETOS = {
    "o": "#1a1a1f", "a": "#5b8def", "A": "#3c63b0", "w": "#a9c6ff", "c": "#b7773b", "C": "#8a5427",
    "f": "#9cc3de", "F": "#6b98bd", "e": "#15151a", "y": "#ef7fb0", "Y": "#c24f86",
}


def dibujar_objeto(sprites, nombre, escala=3, fondo=None):
    from PIL import Image
    filas = sprites["objetos"][nombre]["filas"]
    img = Image.new("RGBA", (len(filas[0]), len(filas)), fondo or (0, 0, 0, 0))
    px = img.load()
    for y, fila in enumerate(filas):
        for x, c in enumerate(fila):
            if c != ".":
                px[x, y] = _rgb(COLORES_OBJETOS[c]) + (255,)
    return img.resize((img.width * escala, img.height * escala), Image.NEAREST)


RUTA_ESTADO = os.path.join(carpeta_usuario(), "datos", "michis_estado.json")
HAMBRE_POR_HORA = 9      # de 0 (lleno) a 100 (con mucha hambre)
ALEGRIA_POR_HORA = -4    # la felicidad baja despacito si nadie juega con él
EFECTOS = {  # (hambre, felicidad)
    "comida": (-65, 8), "premio": (-12, 12), "jugar": (0, 4), "mimos": (0, 3),
}


def _leer_estado():
    try:
        with open(RUTA_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _al_dia(e, ahora):
    import time as _t
    horas = max(0.0, (ahora - e.get("t", ahora)) / 3600)
    return {"hambre": min(100.0, e.get("hambre", 30) + HAMBRE_POR_HORA * horas),
            "felicidad": max(0.0, min(100.0, e.get("felicidad", 70) + ALEGRIA_POR_HORA * horas)), "t": ahora}


def estado_michis(ids):
    import time as _t
    ahora = _t.time()
    datos = _leer_estado()
    return {i: {k: round(v) for k, v in _al_dia(datos.get(i, {"t": ahora}), ahora).items() if k != "t"} for i in ids}


def cuidar(michi_id, accion):
    import time as _t
    ahora = _t.time()
    datos = _leer_estado()
    e = _al_dia(datos.get(michi_id, {"t": ahora}), ahora)
    dh, df = EFECTOS.get(accion, (0, 0))
    e["hambre"] = max(0.0, min(100.0, e["hambre"] + dh))
    e["felicidad"] = max(0.0, min(100.0, e["felicidad"] + df))
    datos[michi_id] = e
    os.makedirs(os.path.dirname(RUTA_ESTADO), exist_ok=True)
    with open(RUTA_ESTADO, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    return {"hambre": round(e["hambre"]), "felicidad": round(e["felicidad"])}
