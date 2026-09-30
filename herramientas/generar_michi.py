# -*- coding: utf-8 -*-
"""Dibuja al michi en pixel art y guarda todas las animaciones en michi.json.

Cada cuadro es una cuadrícula de 32x28 con letras que luego se pintan con los
colores que elijas en la app:
  .  transparente        o  contorno
  M  pelaje principal    m  sombra del pelaje     H  brillo del pelaje
  S  mancha de la cara   B  mancha del pecho      F  patitas      b  sombra de manchas
  E  ojos                P  pupila                W  brillo blanco
  N  nariz / orejas      Z  "zzz" y puntitos      R  punto rojo (escuchando)
  K  audífonos           k  sombra de audífonos
  Q  orejas y punta de la cola (puntas del siamés, negro del calicó)
  G  mancha grande (calicó)   T  rayas (atigrado)   U  raya dentro de una mancha
Los accesorios (collar, lazo) se guardan aparte para ponerlos o quitarlos.
"""
import json
import os
import sys

W, H = 32, 28

# ---------------------------------------------------------------- piezas

CABEZA = [  # 12 x 11, mirando al frente
    ".M........M.",
    ".MM......MM.",
    ".MNM....MNM.",
    "MMNMHHHHMNMM",
    "MMMMMMMMMMMM",
    "MMEEMMMMEEMM",
    "MMEPMSSMEPMM",
    "MMSSSNNSSSMM",
    "MSSSoSSoSSSM",
    ".SSSSooSSSS.",
    "..SSSSSSSS..",
]

CABEZA_DORMIDA = [
    ".M........M.",
    ".MM......MM.",
    ".MNM....MNM.",
    "MMNMHHHHMNMM",
    "MMMMMMMMMMMM",
    "MMMMMMMMMMMM",
    "MMooMSSMooMM",
    "MMSSSNNSSSMM",
    "MSSSSooSSSSM",
    ".SSSSSSSSSS.",
    "..SSSSSSSS..",
]

CABEZA_PARPADEO = [f for f in CABEZA_DORMIDA]

CABEZA_ALERTA = [  # orejas más altas, ojos grandes
    "M..........M",
    "MM........MM",
    "MNM......MNM",
    "MNMM....MMNM",
    "MMNMHHHHMNMM",
    "MMMMMMMMMMMM",
    "MMEWMMMMEWMM",
    "MMEPMSSMEPMM",
    "MMSSSNNSSSMM",
    "MSSSSooSSSSM",
    ".SSSSSSSSSS.",
    "..SSSSSSSS..",
]

CABEZA_ARRIBA = [  # mirando hacia arriba (pensando)
    ".M........M.",
    ".MM......MM.",
    ".MNM....MNM.",
    "MMNMHHHHMNMM",
    "MMMMMMMMMMMM",
    "MMPEMMMMPEMM",
    "MMEEMSSMEEMM",
    "MMSSSNNSSSMM",
    "MSSSSooSSSSM",
    ".SSSSSSSSSS.",
    "..SSSSSSSS..",
]

CABEZA_FELIZ = [  # ojitos ^ ^
    ".M........M.",
    ".MM......MM.",
    ".MNM....MNM.",
    "MMNMHHHHMNMM",
    "MMMMMMMMMMMM",
    "MMMoMMMMoMMM",
    "MMoMoSSoMoMM",
    "MMSSSNNSSSMM",
    "MSSSSooSSSSM",
    ".SSSooooSSS.",
    "..SSSSSSSS..",
]


class Capa(dict):
    def pon(self, x, y, c):
        if 0 <= x < W and 0 <= y < H and c != ".":
            self[(x, y)] = c

    def sello(self, filas, ox, oy):
        for y, fila in enumerate(filas):
            for x, c in enumerate(fila):
                self.pon(ox + x, oy + y, c)

    def rect(self, x0, y0, x1, y1, c, redondo=True):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                esquina = (x in (x0, x1)) and (y in (y0, y1))
                if redondo and esquina:
                    continue
                self.pon(x, y, c)

    def elipse(self, cx, cy, rx, ry, c):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1:
                    self.pon(x, y, c)

    def trazo(self, puntos, c, grueso=2):
        for (x, y) in puntos:
            for dx in range(grueso):
                for dy in range(grueso):
                    self.pon(x + dx, y + dy, c)

    def colorear(self, filtro, c):
        for k in list(self):
            if filtro(*k):
                self[k] = c


def componer(*capas):
    """Une capas en orden; cada capa lleva su propio contorno."""
    cuadro = {}
    for capa in capas:
        if not capa:
            continue
        borde = set()
        for (x, y) in capa:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                v = (x + dx, y + dy)
                if v not in capa and 0 <= v[0] < W and 0 <= v[1] < H:
                    borde.add(v)
        for v in borde:
            cuadro[v] = "o"
        cuadro.update(capa)
    return cuadro


def a_filas(cuadro, dy=0):
    filas = [["."] * W for _ in range(H)]
    for (x, y), c in cuadro.items():
        if 0 <= y + dy < H:
            filas[y + dy][x] = c
    return ["".join(f) for f in filas]


# ---------------------------------------------------------------- manchas y rayas

def marcar(capa, zona, letra, solo=("M", "H")):
    """Cambia a `letra` los píxeles de `capa` dentro de `zona` (función x, y) que sean de `solo`."""
    for (x, y), c in list(capa.items()):
        if c in solo and zona(x, y):
            capa[(x, y)] = letra
    return capa


def rayas_y_mancha(capa, mancha, rayas):
    """mancha: función zona; rayas: conjunto de (x, y)."""
    for (x, y), c in list(capa.items()):
        if c not in ("M", "H"):
            continue
        en_mancha, en_raya = mancha(x, y), (x, y) in rayas
        if en_mancha and en_raya:
            capa[(x, y)] = "U"
        elif en_mancha:
            capa[(x, y)] = "G"
        elif en_raya:
            capa[(x, y)] = "T"
    return capa


def marcar_cola(capa, puntos):
    """La punta de la cola (último tercio) en Q y anillos de rayas en T."""
    n = len(puntos)
    for i, (x, y) in enumerate(puntos):
        letra = "Q" if i >= n - max(2, n // 3) else ("T" if i % 2 else None)
        if not letra:
            continue
        for dx in (0, 1):
            for dy in (0, 1):
                if capa.get((x + dx, y + dy)) in ("M", "H"):
                    capa[(x + dx, y + dy)] = letra
    return capa


# ---------------------------------------------------------------- poses de pie (caminar)

def cola_arriba(v=0):
    c = Capa()
    variantes = [
        [(6, 16), (5, 15), (4, 14), (3, 13), (3, 12), (3, 11), (4, 10), (5, 9)],
        [(6, 16), (5, 15), (4, 14), (3, 13), (2, 12), (2, 11), (2, 10), (3, 9)],
        [(6, 16), (5, 15), (4, 14), (4, 13), (4, 12), (4, 11), (5, 10), (6, 9)],
    ]
    c.trazo(variantes[v % 3], "M")
    punta = variantes[v % 3][-1]
    c.pon(punta[0], punta[1], "H")
    return marcar_cola(c, variantes[v % 3])


def patas(desfases, dy=0):
    """desfases: (trasera_lejos, trasera_cerca, delantera_lejos, delantera_cerca) -> (dx, levantada)."""
    lejos, cerca = Capa(), Capa()
    bases = [(8, lejos), (10, cerca), (18, lejos), (20, cerca)]
    for (x, capa), (dx, arriba) in zip(bases, desfases):
        fondo = 26 - arriba
        for y in range(20 + dy, fondo + 1):
            capa.pon(x + (dx if y >= 23 else 0), y, "M" if capa is cerca else "m")
            capa.pon(x + 1 + (dx if y >= 23 else 0), y, "M" if capa is cerca else "m")
        capa.pon(x + dx, fondo, "F")
        capa.pon(x + 1 + dx, fondo, "F")
        if fondo - 1 >= 23:
            capa.pon(x + dx, fondo - 1, "F")
            capa.pon(x + 1 + dx, fondo - 1, "F")
    return lejos, cerca


def cuerpo_de_pie(dy=0):
    c = Capa()
    c.rect(6, 14 + dy, 21, 21 + dy, "M")
    for x in range(8, 19):
        c.pon(x, 14 + dy, "H")
    for x in range(15, 21):  # pancita
        c.pon(x, 21 + dy, "b")
        c.pon(x, 20 + dy, "B")
    for y in range(16 + dy, 21 + dy):  # pecho
        for x in range(18, 22):
            c.pon(x, y, "B")
    rayas = {(x, y + dy) for x in (9, 12, 15) for y in range(14, 18)} | {(x + 1, 14 + dy) for x in (9, 12, 15)}
    return rayas_y_mancha(c, lambda x, y: (8 <= x <= 13 and 15 + dy <= y <= 18 + dy) or
                          (15 <= x <= 16 and 18 + dy <= y <= 19 + dy), rayas)


def cabeza(filas, ox, oy):
    """Pone la cabeza y marca orejas (Q), mancha del calicó (G) y rayas de la frente (T)."""
    c = Capa()
    c.sello(filas, ox, oy)
    llena = next(i for i, f in enumerate(filas) if sum(ch != "." for ch in f) >= 10)
    marcar(c, lambda x, y: y - oy < llena, "Q", solo=("M",))
    rayas = {(ox + x, oy + llena + 1) for x in (3, 5, 6, 8)} | {(ox, oy + llena + 3), (ox + 11, oy + llena + 3)}
    return rayas_y_mancha(c, lambda x, y: x - ox <= 4 and llena <= y - oy <= llena + 3, rayas)


def gato_de_pie(desfases, cola=0, dy=0, cara=CABEZA, dy_cabeza=0, dx_cabeza=0, extras=()):
    lejos, cerca = patas(desfases, dy)
    return componer(cola_arriba(cola), lejos, cuerpo_de_pie(dy), cerca,
                    cabeza(cara, 18 + dx_cabeza, 5 + dy + dy_cabeza), *extras)


CORAZON = [".C.C.", "CCCCC", "CCCCC", ".CCC.", "..C.."]


def corazones(cuadro, fase):
    """Corazoncitos que suben (mimos)."""
    posiciones = [[(24, 9)], [(25, 5), (4, 10)], [(26, 1), (3, 6), (22, 8)]][fase % 3]
    for ox, oy in posiciones:
        for y, fila in enumerate(CORAZON):
            for x, c in enumerate(fila):
                if c != "." and 0 <= ox + x < W and 0 <= oy + y < H:
                    cuadro[(ox + x, oy + y)] = c
    return cuadro


# ---------------------------------------------------------------- sentado

def cuerpo_sentado(dy=0):
    c = Capa()
    c.elipse(15.5, 20.5 + dy, 7, 6.5, "M")
    for y in range(15 + dy, 27):
        for x in range(12, 20):
            if (x, y) in c:
                c[(x, y)] = "B"
    for x in range(10, 21):
        if (x, 14 + dy) in c:
            c[(x, 14 + dy)] = "H"
    rayas = {(x, y + dy) for y in (17, 20, 23) for x in (9, 10, 11, 20, 21, 22)}
    return rayas_y_mancha(c, lambda x, y: x <= 12 and 15 + dy <= y <= 21 + dy, rayas)


def patas_sentado(levanta=False):
    c = Capa()
    for x in (12, 13):
        c.pon(x, 24, "B"); c.pon(x, 25, "F"); c.pon(x, 26, "F")
    if not levanta:
        for x in (17, 18):
            c.pon(x, 24, "B"); c.pon(x, 25, "F"); c.pon(x, 26, "F")
    return c


def cola_suelo(v=0):
    c = Capa()
    if v == 0:
        pts = [(21, 25), (23, 25), (25, 25), (26, 24), (27, 23), (27, 22)]
    else:
        pts = [(21, 25), (23, 25), (25, 25), (26, 25), (27, 24), (28, 23)]
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        n = max(abs(x1 - x0), abs(y1 - y0))
        for t in range(n + 1):
            c.trazo([(x0 + (x1 - x0) * t // max(n, 1), y0 + (y1 - y0) * t // max(n, 1))], "M")
    x, y = pts[-1]
    c.pon(x, y, "H")
    return marcar_cola(c, pts)


def pata_en_cara():
    c = Capa()
    c.rect(16, 12, 18, 17, "F", redondo=True)
    return c


def gato_sentado(cara=CABEZA, cola=0, dy=0, levanta=False, extras=()):
    capas = [cola_suelo(cola), cuerpo_sentado(dy), patas_sentado(levanta), cabeza(cara, 10, 4 + dy)]
    capas += list(extras)
    return componer(*capas)


# ---------------------------------------------------------------- dormido (bolita)

def gato_dormido(respira=0):
    cuerpo = Capa()
    cuerpo.elipse(15, 21 + respira * 0.5, 10.5, 5.8 - respira * 0.5, "M")
    for x in range(8, 22):
        y = min(k[1] for k in cuerpo if k[0] == x)
        cuerpo[(x, y)] = "H"
    rayas_y_mancha(cuerpo, lambda x, y: 8 <= x <= 14 and 16 <= y <= 20,
                   {(x, y) for x in (10, 14, 18) for y in range(15, 19)})
    cola = Capa()
    puntos_cola = [(5, 24), (7, 25), (9, 25), (11, 25), (13, 25), (15, 25), (17, 25)]
    cola.trazo(puntos_cola, "M")
    cola.pon(18, 25, "H"); cola.pon(18, 26, "H")
    marcar_cola(cola, puntos_cola)
    cara = Capa()
    cara.sello(CABEZA_DORMIDA, 18, 15 + respira)
    patitas = Capa()
    for x in (17, 18, 19, 20):
        patitas.pon(x, 26, "F")
    return componer(cuerpo, cola, patitas, cara)


def zzz(cuadro, paso):
    """Dibuja letras z que suben."""
    glifo = ["ZZZZZ", "...Z.", "..Z..", ".Z...", "ZZZZZ"]
    for ox, oy in [(21, 8), (26, 1)][:min(paso, 1) + 1]:
        for y, fila in enumerate(glifo):
            for x, c in enumerate(fila):
                if c != "." and ox + x < W:
                    cuadro[(ox + x, oy + y)] = c
    return cuadro


# ---------------------------------------------------------------- extras

def puntitos(cuadro, n):
    for i in range(n):
        x = 24 + i * 3
        for dx in (0, 1):
            for dy in (0, 1):
                cuadro[(x + dx, 3 + dy)] = "Z"
    return cuadro


def punto_rojo(cuadro, grande):
    cx, cy = 26, 5
    pix = [(0, 0), (1, 0), (0, 1), (1, 1)]
    if grande:
        pix += [(-1, 0), (-1, 1), (2, 0), (2, 1), (0, -1), (1, -1), (0, 2), (1, 2)]
    for dx, dy in pix:
        cuadro[(cx + dx, cy + dy)] = "R"
    return cuadro


def audifonos(dy=0):
    c = Capa()
    oy = 4 + dy
    for x in range(11, 21):
        c.pon(x, oy + 1, "K")
    c.pon(10, oy + 2, "K"); c.pon(21, oy + 2, "K")
    for y in range(oy + 4, oy + 8):
        c.pon(9, y, "K"); c.pon(10, y, "k")
        c.pon(21, y, "k"); c.pon(22, y, "K")
    return c


def brillitos(cuadro, fase):
    puntos = [[(4, 6), (27, 4)], [(3, 3), (28, 8), (6, 1)]][fase]
    for x, y in puntos:
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            cuadro[(x + dx, y + dy)] = "Z" if (dx, dy) != (0, 0) else "W"
    return cuadro


# ---------------------------------------------------------------- accesorios (se ubican según la cabeza)

def collar(ox, oy):
    """ox, oy: esquina de la cabeza."""
    pix = {(ox + x, oy + 11): "A" for x in range(2, 10)}
    pix[(ox + 5, oy + 12)] = "Y"
    pix[(ox + 6, oy + 12)] = "Y"
    return pix


def lazo(ox, oy):
    forma = ["AA.AA", "AAYAA", "A...A"]
    pix = {}
    for y, fila in enumerate(forma):
        for x, c in enumerate(fila):
            if c != ".":
                pix[(ox + 8 + x, oy - 1 + y)] = c
    return pix


def accesorios(ox, oy):
    return {"collar": collar(ox, oy), "lazo": lazo(ox, oy)}


def a_lista(pix):
    return [[x, y, c] for (x, y), c in sorted(pix.items()) if 0 <= x < W and 0 <= y < H]


# ---------------------------------------------------------------- animaciones

def cuadro(dic, cabeza_en):
    return {"filas": a_filas(dic),
            "acc": {k: a_lista(v) for k, v in accesorios(*cabeza_en).items()}}


def construir():
    A = {}
    # caminar: 4 cuadros
    pasos = [
        ((1, 0), (-1, 1), (-1, 1), (1, 0)),
        ((0, 0), (0, 0), (0, 0), (0, 0)),
        ((-1, 1), (1, 0), (1, 0), (-1, 1)),
        ((0, 0), (0, 0), (0, 0), (0, 0)),
    ]
    A["caminar"] = {"fps": 8, "cuadros": [
        cuadro(gato_de_pie(p, cola=i % 2, dy=(1 if i % 2 else 0)), (18, 5 + (1 if i % 2 else 0)))
        for i, p in enumerate(pasos)]}
    quieto = ((0, 0),) * 4
    A["parado"] = {"fps": 2, "cuadros": [
        cuadro(gato_de_pie(quieto, cola=0), (18, 5)),
        cuadro(gato_de_pie(quieto, cola=2), (18, 5)),
    ]}
    A["sentado"] = {"fps": 2, "cuadros": [
        cuadro(gato_sentado(cola=0), (10, 4)),
        cuadro(gato_sentado(cola=0), (10, 4)),
        cuadro(gato_sentado(cola=1), (10, 4)),
        cuadro(gato_sentado(cara=CABEZA_PARPADEO, cola=1), (10, 4)),
    ]}
    A["dormir"] = {"fps": 1, "cuadros": [
        cuadro(zzz(gato_dormido(0), 0), (18, 15)),
        cuadro(zzz(gato_dormido(1), 1), (18, 16)),
        cuadro(zzz(gato_dormido(0), 2), (18, 15)),
        cuadro(gato_dormido(1), (18, 16)),
    ]}
    alerta = gato_sentado(cara=CABEZA_ALERTA, dy=0)
    A["escuchar"] = {"fps": 3, "cuadros": [
        cuadro(punto_rojo(dict(gato_sentado(cara=CABEZA_ALERTA)), True), (10, 5)),
        cuadro(punto_rojo(dict(gato_sentado(cara=CABEZA_ALERTA)), False), (10, 5)),
    ]}
    A["pensar"] = {"fps": 3, "cuadros": [
        cuadro(puntitos(dict(gato_sentado(cara=CABEZA_ARRIBA)), n), (10, 4)) for n in (1, 2, 3, 0)]}
    A["audifonos"] = {"fps": 2, "cuadros": [
        cuadro(punto_rojo(gato_sentado(extras=[audifonos(0)]), False), (10, 4)),
        cuadro(gato_sentado(dy=1, extras=[audifonos(1)]), (10, 5)),
    ]}
    agachado = gato_de_pie(quieto, cola=0, dy=1)
    salto = gato_de_pie(((1, 2), (1, 2), (-1, 2), (-1, 2)), cola=1)
    A["festejar"] = {"fps": 8, "cuadros": [
        cuadro(agachado, (18, 6)),
        {"filas": a_filas(salto, dy=-3), "acc": {k: a_lista({(x, y - 3): c for (x, y), c in v.items()})
                                                 for k, v in accesorios(18, 5).items()}},
        {"filas": a_filas(brillitos(dict(gato_de_pie(((1, 2), (1, 2), (-1, 2), (-1, 2)), cola=1, cara=CABEZA_FELIZ)), 0), dy=-4),
         "acc": {k: a_lista({(x, y - 4): c for (x, y), c in v.items()}) for k, v in accesorios(18, 5).items()}},
        {"filas": a_filas(brillitos(dict(gato_de_pie(((1, 2), (1, 2), (-1, 2), (-1, 2)), cola=1, cara=CABEZA_FELIZ)), 1), dy=-3),
         "acc": {k: a_lista({(x, y - 3): c for (x, y), c in v.items()}) for k, v in accesorios(18, 5).items()}},
        cuadro(gato_de_pie(quieto, cola=0, cara=CABEZA_FELIZ, dy=1), (18, 6)),
        cuadro(gato_de_pie(quieto, cola=0, cara=CABEZA_FELIZ), (18, 5)),
    ]}
    A["lavarse"] = {"fps": 4, "cuadros": [
        cuadro(gato_sentado(), (10, 4)),
        cuadro(gato_sentado(cara=CABEZA_PARPADEO, levanta=True, extras=[pata_en_cara()]), (10, 4)),
        cuadro(gato_sentado(cara=CABEZA_PARPADEO, levanta=True, extras=[desplazar(pata_en_cara(), -1, 1)]), (10, 4)),
        cuadro(gato_sentado(cara=CABEZA_PARPADEO, levanta=True, extras=[pata_en_cara()]), (10, 4)),
        cuadro(gato_sentado(cara=CABEZA_PARPADEO, levanta=True, extras=[desplazar(pata_en_cara(), -1, 1)]), (10, 4)),
        cuadro(gato_sentado(), (10, 4)),
    ]}
    # comer: cabeza agachada hacia el plato (el plato va delante, a la derecha)
    A["comer"] = {"fps": 4, "cuadros": [
        cuadro(gato_de_pie(quieto, cola=c, cara=CABEZA_DORMIDA, dy=1, dy_cabeza=dyc, dx_cabeza=1), (19, 6 + dyc))
        for c, dyc in ((0, 6), (1, 7), (2, 6), (1, 7))]}
    # jugar: agachado dando zarpazos
    zarpazo = [((0, 0), (0, 0), (0, 0), (2, 4)), ((0, 0), (0, 0), (1, 3), (0, 0)),
               ((0, 0), (0, 0), (0, 0), (3, 5)), ((0, 0), (0, 0), (0, 0), (0, 0))]
    A["jugar"] = {"fps": 7, "cuadros": [
        cuadro(gato_de_pie(z, cola=i % 3, dy=1, dy_cabeza=1), (18, 7)) for i, z in enumerate(zarpazo)]}
    # mimos: sentado, ojitos felices y corazones
    A["mimos"] = {"fps": 3, "cuadros": [
        cuadro(corazones(dict(gato_sentado(cara=CABEZA_FELIZ, cola=i % 2)), i), (10, 4)) for i in range(3)]}
    return A


# ---------------------------------------------------------------- objetos (colores fijos)

OBJETOS = {
    "plato": [
        "................",
        "...cCccCcCccC...",
        "..cCccCcCcCcCc..",
        ".oooooooooooooo.",
        ".oaaaaaaaaaaaao.",
        "..oawwaaaaaaao..",
        "...oAAAAAAAAo...",
        "....oooooooo....",
    ],
    "plato_vacio": [
        "................",
        "................",
        "................",
        ".oooooooooooooo.",
        ".oaaaaaaaaaaaao.",
        "..oawwaaaaaaao..",
        "...oAAAAAAAAo...",
        "....oooooooo....",
    ],
    "pescado": [
        "..oooo...oo",
        ".offffo.ofo",
        "ofeffffoffo",
        "offfFFFffo.",
        ".oFFFFo.ofo",
        "..oooo...oo",
    ],
    "estambre": [
        "..ooooo..",
        ".oyyYyyo.",
        "oyYyyyYyo",
        "oyyYyYyyo",
        "oYyyYyyYo",
        "oyyYyYyyo",
        "oyYyyyYyo",
        ".oyyYyyo.",
        "..ooooo..",
    ],
    "estambre2": [
        "..ooooo..",
        ".oYyyyYo.",
        "oyyYyYyyo",
        "oYyyYyyYo",
        "oyYyyyYyo",
        "oYyyYyyYo",
        "oyyYyYyyo",
        ".oYyyyYo.",
        "..ooooo..",
    ],
}


def desplazar(capa, dx, dy):
    nueva = Capa()
    for (x, y), c in capa.items():
        nueva.pon(x + dx, y + dy, c)
    return nueva


if __name__ == "__main__":
    datos = {"ancho": W, "alto": H, "suelo": 26, "animaciones": construir(),
             "objetos": {k: {"filas": v} for k, v in OBJETOS.items()}}
    destino = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "michi.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    print("Guardado", destino, sum(len(a["cuadros"]) for a in datos["animaciones"].values()), "cuadros")
