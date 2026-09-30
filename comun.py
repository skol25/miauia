# -*- coding: utf-8 -*-
"""Piezas compartidas: configuracion, rutas, fechas y el archivo de notas."""
import datetime
import difflib
import json
import logging
import os
import re
import unicodedata

import michi_arte

BASE = os.path.dirname(os.path.abspath(__file__))
USUARIO = michi_arte.carpeta_usuario()  # instalado: %APPDATA%\\Miauia · desarrollo: esta carpeta
DATOS = os.path.join(USUARIO, "datos")
REUNIONES = os.path.join(DATOS, "reuniones")
TEMPORAL = os.path.join(DATOS, "temporal")
NOTAS = os.path.join(DATOS, "notas.md")
PROYECTOS = os.path.join(DATOS, "proyectos.json")
AVISADOS = os.path.join(DATOS, "avisados.json")
CONFIG = os.path.join(USUARIO, "config.json")
REGISTRO = os.path.join(DATOS, "registro.log")

CONFIG_POR_DEFECTO = {
    "atajo_anotar": "ctrl+alt+n",
    "atajo_preguntar": "ctrl+alt+p",
    "atajo_reunion": "ctrl+alt+r",
    "idioma": "es",
    "whisper_rapido": "small",
    "whisper_reunion": "small",
    "modelo_rapido": "qwen3.5:4b",
    "modelo_reunion": "qwen3.5:9b",
    "ollama_url": "http://127.0.0.1:11434",
    "mantener_modelo_cargado": "1m",
    "contexto_reunion": 16384,
    "max_segundos_nota": 90,
    "grabar_audio_sistema_en_reunion": True,
    "leer_respuestas_en_voz": False,
    "guardar_audio_reuniones": False,
    "avisar_minutos_antes": 10,
    "resumen_diario": "08:00",
    "sonido_avisos": True,
    "voz_avisos": False,
}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

TIPOS_CON_CASILLA = {"tarea", "cita", "recordatorio", "compra"}
NOMBRE_TIPO = {
    "tarea": "Tarea", "cita": "Cita", "recordatorio": "Recordatorio",
    "compra": "Compra", "idea": "Idea", "dato": "Dato",
}

ENCABEZADO_NOTAS = (
    "# Mis notas\n\n"
    "Este archivo lo llena el asistente, pero puedes editarlo a mano cuando quieras.\n"
    "Las tareas con [ ] están pendientes y las que tienen [x] ya están hechas.\n\n"
)


def asegurar_carpetas():
    for carpeta in (USUARIO, DATOS, REUNIONES, TEMPORAL):
        os.makedirs(carpeta, exist_ok=True)
    if not os.path.exists(NOTAS):
        with open(NOTAS, "w", encoding="utf-8") as f:
            f.write(ENCABEZADO_NOTAS)


def configurar_registro(nombre):
    asegurar_carpetas()
    logging.basicConfig(
        filename=REGISTRO, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s [" + nombre + "] %(levelname)s %(message)s",
    )
    return logging.getLogger(nombre)


def cargar_config():
    from michi_arte import MICHI_POR_DEFECTO
    config = dict(CONFIG_POR_DEFECTO)
    guardado = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8-sig") as f:
                guardado = json.load(f)
            config.update(guardado)
        except Exception as e:  # config dañada: seguimos con valores por defecto
            logging.getLogger("config").error("config.json no se pudo leer: %s", e)
    else:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(dict(config, michi=MICHI_POR_DEFECTO), f, ensure_ascii=False, indent=2)
    # varios michis: el primero es el del asistente
    lista = guardado.get("michis") or [guardado.get("michi") or {}]
    michis = []
    for i, m in enumerate(lista):
        m = dict(MICHI_POR_DEFECTO, **(m or {}))
        m["id"] = m.get("id") or ("principal" if i == 0 else f"michi{i}")
        michis.append(m)
    config["michis"] = michis
    config["michi"] = michis[0]
    return config


def _limpiar_michi(michi, i):
    from michi_arte import MICHI_POR_DEFECTO
    limpio = {k: michi.get(k, v) for k, v in MICHI_POR_DEFECTO.items()}
    limpio["tamano"] = max(1, min(6, int(limpio["tamano"])))
    limpio["nombre"] = str(limpio["nombre"]).strip()[:24] or "Michi"
    limpio["id"] = re.sub(r"[^a-z0-9_]", "", str(michi.get("id") or "").lower())[:20] or (
        "principal" if i == 0 else f"michi{int(ahora().timestamp())}{i}")
    return limpio


def guardar_michis(lista):
    """Guarda la lista de michis (el primero es el del asistente) sin tocar lo demás."""
    datos = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8-sig") as f:
                datos = json.load(f)
        except Exception:
            datos = dict(CONFIG_POR_DEFECTO)
    limpios = [_limpiar_michi(m, i) for i, m in enumerate(lista[:8])] or [_limpiar_michi({}, 0)]
    ids = set()
    for i, m in enumerate(limpios):  # sin ids repetidos
        if m["id"] in ids:
            m["id"] = f"{m['id']}_{i}"
        ids.add(m["id"])
    datos["michis"] = limpios
    datos["michi"] = limpios[0]
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    return limpios


def guardar_michi(michi):
    """Compatibilidad: guarda solo el michi principal."""
    lista = cargar_config()["michis"]
    lista[0] = dict(lista[0], **michi)
    return guardar_michis(lista)[0]


def avisar_asistente(mensaje):
    """Manda un mensaje corto al asistente (el del ícono), si está abierto."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 47831), timeout=1) as s:
            s.sendall(mensaje.encode("utf-8"))
    except OSError:
        pass


# ---------------------------------------------------------------- fechas

def ahora():
    return datetime.datetime.now()


def fecha_larga(dt=None):
    dt = dt or ahora()
    return f"{DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%H:%M}"


def calendario_proximo(dt=None, dias=14):
    """Lista de fechas cercanas para que el modelo resuelva 'el jueves', 'mañana', etc."""
    dt = (dt or ahora()).date()
    lineas = []
    for i in range(-1, dias):
        d = dt + datetime.timedelta(days=i)
        etiqueta = {-1: " (ayer)", 0: " (hoy)", 1: " (mañana)"}.get(i, "")
        lineas.append(f"{DIAS[d.weekday()]} {d.isoformat()}{etiqueta}")
    return "\n".join(lineas)


def limpiar_fecha(valor):
    valor = (valor or "").strip()
    return valor if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) else ""


def limpiar_hora(valor):
    valor = (valor or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", valor)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


# ---------------------------------------------------------------- texto

def normalizar(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]+", " ", texto).strip()


PALABRAS_VACIAS = set(normalizar(
    "que cual cuales como cuando donde quien para por con sin sobre entre desde hasta "
    "una uno unos unas los las del al lo le les me mi mis tu tus su sus este esta estos "
    "estas ese esa eso tengo tenia tiene hay hacer dije dijo algo todo todos nada pero "
    "mas muy tambien ya aun asi era fue ser estar esta estan semana dime decir sabes"
).split())


def palabras_clave(texto):
    return [p[:6] for p in normalizar(texto).split() if len(p) > 2 and p not in PALABRAS_VACIAS]


# ---------------------------------------------------------------- notas

def leer_notas():
    asegurar_carpetas()
    with open(NOTAS, "r", encoding="utf-8") as f:
        return f.read()


def formatear_nota(tipo, texto, fecha="", hora="", origen="", momento=None, proyecto=""):
    tipo = tipo if tipo in NOMBRE_TIPO else "dato"
    momento = momento or ahora()
    partes = [f"**{NOMBRE_TIPO[tipo]}**", texto.strip().rstrip(".")]
    cuando = " ".join(x for x in (limpiar_fecha(fecha), limpiar_hora(hora)) if x)
    if cuando:
        partes.append(f"para: {cuando}")
    if proyecto:
        partes.append(f"proyecto: {proyecto}")
    if origen:
        partes.append(f"de: {origen}")
    partes.append(f"_anotado {momento:%Y-%m-%d %H:%M}_")
    casilla = "[ ] " if tipo in TIPOS_CON_CASILLA else ""
    return f"- {casilla}" + " · ".join(partes)


def agregar_nota(tipo, texto, fecha="", hora="", origen="", proyecto=""):
    proyecto = asegurar_proyecto(proyecto) if proyecto else ""
    linea = formatear_nota(tipo, texto, fecha, hora, origen, proyecto=proyecto)
    contenido = leer_notas()
    with open(NOTAS, "a", encoding="utf-8") as f:
        if contenido and not contenido.endswith("\n"):
            f.write("\n")
        f.write(linea + "\n")
    return linea


def _texto_de_linea(linea):
    """Saca solo la descripción de una línea de nota (sin tipo, fecha ni marca)."""
    partes = linea.split(" · ")
    return partes[1] if len(partes) > 1 else linea


def completar_tarea(descripcion):
    """Marca como hecha la tarea pendiente más parecida. Devuelve la línea o None."""
    lineas = leer_notas().split("\n")
    buscada = normalizar(descripcion)
    claves = set(palabras_clave(descripcion))
    mejor, mejor_puntaje = None, 0.0
    for i, linea in enumerate(lineas):
        if not linea.startswith("- [ ] "):
            continue
        texto = _texto_de_linea(linea)
        parecido = difflib.SequenceMatcher(None, buscada, normalizar(texto)).ratio()
        comunes = claves & set(palabras_clave(texto))
        cobertura = len(comunes) / len(claves) if claves else 0
        puntaje = max(parecido, cobertura)
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = i, puntaje
    if mejor is None or mejor_puntaje < 0.5:
        return None
    lineas[mejor] = lineas[mejor].replace("- [ ] ", "- [x] ", 1) + f" · _hecho {ahora():%Y-%m-%d}_"
    with open(NOTAS, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    return lineas[mejor]


# ---------------------------------------------------------------- contexto para preguntas

def _resumenes_de_reuniones():
    if not os.path.isdir(REUNIONES):
        return []
    trozos = []
    for nombre in sorted(os.listdir(REUNIONES)):
        if not nombre.endswith(".md"):
            continue
        with open(os.path.join(REUNIONES, nombre), "r", encoding="utf-8") as f:
            texto = f.read()
        resumen = texto.split("\n## Transcripción")[0].strip()
        trozos.append(f"[Reunión, archivo {nombre}]\n{resumen[:3500]}")
    return trozos


def contexto_para_pregunta(pregunta, limite=16000):
    """Arma el material que el modelo leerá para responder, sin pasarse del límite."""
    notas = [l for l in leer_notas().split("\n") if l.startswith("- ")]
    reuniones = _resumenes_de_reuniones()
    todo = "\n".join(notas) + "\n\n" + "\n\n".join(reuniones)
    if len(todo) <= limite:
        return todo.strip()

    claves = palabras_clave(pregunta)
    candidatos = []  # (puntaje, orden, texto)
    total = len(notas) + len(reuniones)
    for orden, trozo in enumerate(notas + reuniones):
        normal = normalizar(trozo)
        puntaje = sum(normal.count(c) for c in claves)
        if trozo.startswith("- [ ] "):
            puntaje += 0.5  # lo pendiente casi siempre importa
        puntaje += orden / max(total, 1)  # a igualdad, lo más reciente
        candidatos.append((puntaje, orden, trozo))
    candidatos.sort(reverse=True)
    elegidos, usado = [], 0
    for puntaje, orden, trozo in candidatos:
        if usado + len(trozo) + 2 > limite:
            continue
        elegidos.append((orden, trozo))
        usado += len(trozo) + 2
    elegidos.sort()
    return "\n".join(t for _, t in elegidos).strip()


# ---------------------------------------------------------------- lectura y edición (app de notas)

TIPO_POR_NOMBRE = {v.lower(): k for k, v in NOMBRE_TIPO.items()}


def parsear_linea(linea):
    """Convierte una línea de notas.md en un diccionario. Tolera líneas escritas a mano."""
    if not linea.startswith("- "):
        return None
    cuerpo = linea[2:]
    casilla = None
    if cuerpo.startswith("[ ] "):
        casilla, cuerpo = False, cuerpo[4:]
    elif cuerpo[:4].lower() == "[x] ":
        casilla, cuerpo = True, cuerpo[4:]
    nota = {"linea": linea, "hecho": bool(casilla), "casilla": casilla is not None,
            "tipo": "dato", "texto": "", "fecha": "", "hora": "", "origen": "",
            "anotado": "", "fecha_hecho": "", "proyecto": ""}
    partes = [p.strip() for p in cuerpo.split(" · ")]
    m = re.fullmatch(r"\*\*(.+?)\*\*", partes[0]) if partes else None
    if m and m.group(1).lower() in TIPO_POR_NOMBRE:
        nota["tipo"] = TIPO_POR_NOMBRE[m.group(1).lower()]
        partes = partes[1:]
    elif casilla is not None:
        nota["tipo"] = "tarea"
    texto = []
    for p in partes:
        if p.startswith("para: "):
            valor = p[6:].split()
            nota["fecha"] = limpiar_fecha(valor[0]) if valor else ""
            nota["hora"] = limpiar_hora(valor[1]) if len(valor) > 1 else ""
        elif p.startswith("proyecto: "):
            nota["proyecto"] = p[10:]
        elif p.startswith("de: "):
            nota["origen"] = p[4:]
        elif re.fullmatch(r"_anotado .+_", p):
            nota["anotado"] = p[9:-1]
        elif re.fullmatch(r"_hecho .+_", p):
            nota["fecha_hecho"] = p[7:-1]
        else:
            texto.append(p)
    nota["texto"] = " · ".join(texto).strip()
    return nota


def componer_linea(nota):
    tipo = nota.get("tipo") if nota.get("tipo") in NOMBRE_TIPO else "dato"
    partes = [f"**{NOMBRE_TIPO[tipo]}**", (nota.get("texto") or "").strip().replace("\n", " ")]
    cuando = " ".join(x for x in (limpiar_fecha(nota.get("fecha")), limpiar_hora(nota.get("hora"))) if x)
    if cuando:
        partes.append(f"para: {cuando}")
    if nota.get("proyecto"):
        partes.append(f"proyecto: {nota['proyecto']}")
    if nota.get("origen"):
        partes.append(f"de: {nota['origen']}")
    partes.append(f"_anotado {nota.get('anotado') or f'{ahora():%Y-%m-%d %H:%M}'}_")
    con_casilla = tipo in TIPOS_CON_CASILLA or nota.get("hecho")
    if nota.get("hecho"):
        partes.append(f"_hecho {nota.get('fecha_hecho') or f'{ahora():%Y-%m-%d}'}_")
    casilla = ("[x] " if nota.get("hecho") else "[ ] ") if con_casilla else ""
    return "- " + casilla + " · ".join(partes)


def listar_notas():
    notas = []
    for i, linea in enumerate(leer_notas().split("\n")):
        nota = parsear_linea(linea)
        if nota:
            nota["orden"] = i
            notas.append(nota)
    return notas


def reemplazar_linea(original, nueva):
    """Cambia (o borra, si nueva es None) una línea exacta. Devuelve True si la encontró."""
    lineas = leer_notas().split("\n")
    try:
        i = lineas.index(original)
    except ValueError:
        return False
    if nueva is None:
        del lineas[i]
    else:
        lineas[i] = nueva
    with open(NOTAS, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    return True


def listar_reuniones():
    if not os.path.isdir(REUNIONES):
        return []
    lista = []
    for nombre in sorted(os.listdir(REUNIONES), reverse=True):
        if not nombre.endswith(".md"):
            continue
        with open(os.path.join(REUNIONES, nombre), "r", encoding="utf-8") as f:
            texto = f.read()
        titulo = texto.split("\n", 1)[0].lstrip("# ").strip() or nombre
        m = re.search(r"^Fecha: (.+?)(?: · |$)", texto, re.M)
        mp = re.search(r"^Proyecto: (.+)$", texto, re.M)
        md = re.match(r"(\d{4}-\d{2}-\d{2})", nombre)
        resumen = ""
        if "## Resumen" in texto:
            resumen = texto.split("## Resumen", 1)[1].strip().split("\n## ", 1)[0].strip()
        lista.append({"archivo": nombre, "titulo": titulo, "fecha": m.group(1) if m else nombre[:10],
                      "dia": md.group(1) if md else "", "proyecto": mp.group(1).strip() if mp else "",
                      "resumen": resumen[:220], "contenido": texto})
    return lista


# ---------------------------------------------------------------- proyectos

COLORES_PROYECTO = ["#529cca", "#9a6dd7", "#4dab9a", "#e08a3c", "#e5484d", "#d4a72c", "#ef7fb0", "#7c8ea3"]


def listar_proyectos():
    asegurar_carpetas()
    if not os.path.exists(PROYECTOS):
        return []
    try:
        with open(PROYECTOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_proyectos(lista):
    asegurar_carpetas()
    with open(PROYECTOS, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)


def buscar_proyecto(nombre):
    clave = normalizar(nombre)
    for p in listar_proyectos():
        if normalizar(p["nombre"]) == clave:
            return p
    return None


def asegurar_proyecto(nombre, descripcion=""):
    """Devuelve el nombre tal como está guardado; si no existe, lo crea."""
    nombre = (nombre or "").strip().strip("#").strip()[:40]
    if not nombre:
        return ""
    existente = buscar_proyecto(nombre)
    if existente:
        return existente["nombre"]
    lista = listar_proyectos()
    lista.append({"nombre": nombre, "color": COLORES_PROYECTO[len(lista) % len(COLORES_PROYECTO)],
                  "descripcion": descripcion})
    guardar_proyectos(lista)
    return nombre


def cambiar_proyecto_en_notas(viejo, nuevo):
    """Renombra (o quita, si nuevo es '') el proyecto en todas las notas."""
    lineas = leer_notas().split("\n")
    for i, linea in enumerate(lineas):
        nota = parsear_linea(linea)
        if nota and nota["proyecto"] == viejo:
            nota["proyecto"] = nuevo
            lineas[i] = componer_linea(nota)
    with open(NOTAS, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def proyectos_para_ia():
    lista = listar_proyectos()
    if not lista:
        return "(todavía no hay proyectos)"
    return "\n".join(f"- {p['nombre']}" + (f": {p['descripcion']}" if p.get("descripcion") else "") for p in lista)


# ---------------------------------------------------------------- avisos ya mostrados

def leer_avisados():
    try:
        with open(AVISADOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"hechos": {}, "pospuestos": {}}


def guardar_avisados(datos):
    limite = (ahora() - datetime.timedelta(days=30)).isoformat()
    datos["hechos"] = {k: v for k, v in datos.get("hechos", {}).items() if v >= limite}
    with open(AVISADOS, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
