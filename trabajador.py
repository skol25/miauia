# -*- coding: utf-8 -*-
"""Proceso de trabajo: transcribe y usa la IA. Se abre solo cuando hace falta y
se cierra al terminar, así toda la memoria vuelve a Windows."""
import argparse
import difflib
import gc
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

import comun

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

log = comun.configurar_registro("trabajador")
CFG = comun.cargar_config()
QUIEN = (CFG.get("nombre_usuario") or "").strip() or "la persona"  # para los mensajes a la IA


# ---------------------------------------------------------------- voz a texto

def transcribir(ruta_audio, modelo, rapido):
    """Devuelve una lista de (inicio, fin, texto)."""
    from faster_whisper import WhisperModel  # se importa aquí: pesa bastante

    whisper = WhisperModel(modelo, device="cpu", compute_type="int8")
    segmentos, _info = whisper.transcribe(
        ruta_audio,
        language=CFG["idioma"] or None,
        beam_size=1 if rapido else 5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    resultado = [(s.start, s.end, s.text.strip()) for s in segmentos if s.text.strip()]
    del whisper
    gc.collect()
    return resultado


def quitar_eco(mios, otros):
    """Si usas parlantes, el micrófono también capta a los demás. Quitamos esas
    frases repetidas del micrófono cuando ya aparecen en el audio del sistema."""
    limpios = []
    for inicio, fin, texto in mios:
        repetido = False
        for o_ini, o_fin, o_texto in otros:
            if o_fin < inicio - 3 or o_ini > fin + 3:
                continue
            a, b = comun.normalizar(texto), comun.normalizar(o_texto)
            if difflib.SequenceMatcher(None, a, b).ratio() >= 0.55 or (len(a) > 12 and a in b):
                repetido = True
                break
        if not repetido:
            limpios.append((inicio, fin, texto))
    return limpios


def unir_transcripcion(mios, otros):
    filas = [(i, "Yo", t) for i, _, t in mios] + [(i, "Otros", t) for i, _, t in otros]
    filas.sort(key=lambda f: f[0])
    lineas = []
    for inicio, quien, texto in filas:
        s = int(inicio)
        lineas.append(f"[{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}] {quien}: {texto}")
    return "\n".join(lineas)


# ---------------------------------------------------------------- Ollama

def _ollama(ruta, datos=None, tiempo=10):
    url = CFG["ollama_url"].rstrip("/") + ruta
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    peticion = urllib.request.Request(url, data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=tiempo) as r:
        return json.loads(r.read().decode("utf-8"))


def asegurar_ollama():
    try:
        _ollama("/api/version")
        return
    except Exception:
        pass
    exe = shutil.which("ollama") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    if not os.path.exists(exe) and not shutil.which("ollama"):
        raise RuntimeError("No encuentro Ollama. Instálalo desde ollama.com/download/windows")
    banderas = 0x08000000 | 0x00000008 if os.name == "nt" else 0  # sin ventana, separado
    subprocess.Popen([exe, "serve"], creationflags=banderas,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.75)
        try:
            _ollama("/api/version")
            return
        except Exception:
            continue
    raise RuntimeError("Ollama no respondió. Ábrelo desde el menú Inicio y vuelve a intentar.")


def conversar(modelo, sistema, usuario, formato=None, contexto=8192, mantener=None):
    datos = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": usuario}],
        "stream": False,
        "think": False,
        "keep_alive": mantener if mantener is not None else CFG["mantener_modelo_cargado"],
        "options": {"temperature": 0.2, "num_ctx": contexto},
    }
    if formato:
        datos["format"] = formato
    try:
        respuesta = _ollama("/api/chat", datos, tiempo=3600)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "ignore")
        if "think" in detalle:  # modelos que no aceptan esa opción
            datos.pop("think")
            respuesta = _ollama("/api/chat", datos, tiempo=3600)
        elif "not found" in detalle:
            raise RuntimeError(f"Falta el modelo {modelo}. Ejecuta: ollama pull {modelo}")
        else:
            raise RuntimeError(f"Ollama devolvió un error: {detalle[:200]}")
    return respuesta["message"]["content"].strip()


def leer_json(texto):
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        texto = texto[texto.find("{"):]
    inicio, fin = texto.find("{"), texto.rfind("}")
    return json.loads(texto[inicio:fin + 1])


# ---------------------------------------------------------------- modos

ESQUEMA_NOTA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "accion": {"type": "string", "enum": ["agregar", "completar"]},
            "tipo": {"type": "string", "enum": ["tarea", "cita", "recordatorio", "compra", "idea", "dato"]},
            "texto": {"type": "string"},
            "fecha": {"type": "string"},
            "hora": {"type": "string"},
            "proyecto": {"type": "string"},
            "numero": {"type": "integer"},
        },
        "required": ["accion", "tipo", "texto", "fecha", "hora", "proyecto", "numero"],
    }}},
    "required": ["items"],
}


def modo_nota(texto, proyecto_fijo=""):
    sistema = (
        f"Eres el asistente personal de {QUIEN} y organizas lo que te dicta. "
        "Convierte el mensaje en una o varias notas. Reglas:\n"
        "- accion: 'completar' solo si dice que algo ya lo hizo o que lo marques como hecho; si no, 'agregar'.\n"
        "- numero: si accion es 'completar', el número [N] de la tarea pendiente de la lista; si no, 0.\n"
        "- tipo: tarea (algo que debe hacer), cita (reunión o evento con hora/día), recordatorio, "
        "compra, idea o dato (información para recordar, como un número o una clave de algo).\n"
        "- texto: corto y claro, en español, sin frases como 'anota que'. Mantén nombres, números y cifras exactos.\n"
        "- fecha: AAAA-MM-DD si menciona un día (usa el calendario), si no, cadena vacía.\n"
        "- hora: HH:MM en 24 horas si la menciona, si no, cadena vacía.\n"
        "- proyecto: el nombre EXACTO de uno de sus proyectos si la nota claramente tiene que ver con él "
        "(lo nombra, o menciona su cliente o su tema). Si dice 'proyecto X' o 'para X' y X no está en la "
        "lista, escribe X tal cual para crearlo. Si no está claro, cadena vacía.\n"
        "Responde solo con JSON."
    )
    usuario = (f"Ahora es {comun.fecha_larga()}.\nCalendario:\n{comun.calendario_proximo()}\n\n"
               f"Proyectos:\n{comun.proyectos_para_ia()}\n\n"
               f"Tareas pendientes:\n{_texto_pendientes(_pendientes()) or '(ninguna)'}\n\n"
               f"Mensaje: {texto}")
    try:
        asegurar_ollama()
        datos = leer_json(conversar(CFG["modelo_rapido"], sistema, usuario, formato=ESQUEMA_NOTA))
        items = datos.get("items") or []
    except Exception as e:
        log.exception("La IA no pudo ordenar la nota")
        linea = comun.agregar_nota("dato", texto, proyecto=proyecto_fijo)
        return {"ok": True, "titulo": "Nota guardada (sin ordenar)",
                "mensaje": f"{texto}\n\nLa IA no respondió: {e}", "linea": linea}

    guardadas, hechas, no_encontradas = [], [], []
    for item in items:
        contenido = (item.get("texto") or "").strip()
        if not contenido:
            continue
        if item.get("accion") == "completar":
            pend = _pendientes()
            n = item.get("numero") or 0
            if 1 <= n <= len(pend):
                _aplicar_a(dict(pend[n - 1]), "completar")
                hechas.append(pend[n - 1]["texto"])
            else:
                linea = comun.completar_tarea(contenido)
                (hechas if linea else no_encontradas).append(contenido)
        else:
            proyecto = proyecto_fijo or (item.get("proyecto") or "").strip()
            proyecto = comun.asegurar_proyecto(proyecto) if proyecto else ""
            comun.agregar_nota(item.get("tipo", "dato"), contenido, item.get("fecha"), item.get("hora"),
                               proyecto=proyecto)
            nombre = comun.NOMBRE_TIPO.get(item.get("tipo"), "Dato")
            cuando = " ".join(x for x in (comun.limpiar_fecha(item.get("fecha")),
                                          comun.limpiar_hora(item.get("hora"))) if x)
            guardadas.append(f"{nombre}: {contenido}" + (f" ({cuando})" if cuando else "")
                             + (f" · {proyecto}" if proyecto else ""))
    if not guardadas and not hechas and not no_encontradas:
        comun.agregar_nota("dato", texto, proyecto=proyecto_fijo)
        guardadas.append(f"Dato: {texto}")

    lineas = guardadas + [f"Hecho: {h}" for h in hechas]
    lineas += [f"No encontré la tarea: {n}" for n in no_encontradas]
    return {"ok": True, "titulo": "Nota guardada" if guardadas else "Listo", "mensaje": "\n".join(lineas)}


# ---------------------------------------------------------------- preguntar (y actuar sobre las tareas)

CONVERSACION = os.path.join(comun.DATOS, "conversacion.json")


def _pendientes():
    notas = [n for n in comun.listar_notas() if n["casilla"] and not n["hecho"]]
    return sorted(notas, key=lambda n: (n["fecha"] or "9999", n["hora"] or "99", n["orden"]))


def _cuando(n):
    if not n["fecha"]:
        return "sin fecha"
    import datetime
    d = datetime.date.fromisoformat(n["fecha"])
    hoy = comun.ahora().date()
    txt = f"{comun.DIAS[d.weekday()]} {d.day} de {comun.MESES[d.month - 1]}" + (f" a las {n['hora']}" if n["hora"] else "")
    if d < hoy:
        return f"vencía el {txt} (ATRASADA)"
    if d == hoy:
        return f"es HOY" + (f" a las {n['hora']}" if n["hora"] else "")
    return f"para el {txt}"


def _texto_pendientes(pend):
    filas = []
    for i, n in enumerate(pend, 1):
        extra = f" · proyecto {n['proyecto']}" if n["proyecto"] else ""
        filas.append(f"[{i}] {comun.NOMBRE_TIPO.get(n['tipo'], 'Tarea')}: {n['texto']} — {_cuando(n)}{extra}")
    return "\n".join(filas)


def _aplicar_a(nota, tipo, **cambios):
    """Cambia una nota y deja en nota['linea'] la línea nueva (para poder encadenar cambios)."""
    if tipo == "borrar":
        return comun.reemplazar_linea(nota["linea"], None)
    nueva = dict(nota)
    if tipo == "completar":
        if not nota["casilla"]:
            return False
        nueva.update(hecho=True, fecha_hecho="")
    elif tipo == "reabrir":
        nueva.update(hecho=False, fecha_hecho="")
    elif tipo == "quitar_fecha":
        if not nota["fecha"] and not nota["hora"]:
            return False
        nueva.update(fecha="", hora="")
    elif tipo == "reprogramar":
        fecha, hora = comun.limpiar_fecha(cambios.get("fecha")), comun.limpiar_hora(cambios.get("hora"))
        if not fecha and not hora:
            return False
        nueva.update(fecha=fecha or nota["fecha"], hora=hora or nota["hora"])
    elif tipo == "editar":
        texto = (cambios.get("texto") or "").strip()
        clase = cambios.get("clase")
        if texto:
            nueva["texto"] = texto
        if clase in comun.NOMBRE_TIPO and clase != nota["tipo"]:
            nueva["tipo"] = clase
        if nueva == nota:
            return False
    elif tipo == "mover":
        nueva["proyecto"] = cambios.get("proyecto", "")
    linea = comun.componer_linea(nueva)
    if not comun.reemplazar_linea(nota["linea"], linea):
        return False
    nota.update(nueva, linea=linea)
    return True


def _conversacion():
    try:
        with open(CONVERSACION, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if time.time() - datos.get("t", 0) < 30 * 60:  # la charla "se olvida" tras 30 minutos
            return datos.get("turnos", [])
    except Exception:
        pass
    return []


def _recordar(pregunta, respuesta, proyecto=""):
    turnos = (_conversacion() + [{"p": pregunta, "r": respuesta}])[-3:]
    with open(CONVERSACION, "w", encoding="utf-8") as f:
        json.dump({"t": time.time(), "turnos": turnos, "proyecto": proyecto}, f, ensure_ascii=False)


VISTAS_APP = ["hoy", "pendientes", "proximas", "calendario", "proyecto", "hechas", "todas", "reuniones",
              "cita", "recordatorio", "compra", "idea", "dato", "michi", "avisos"]
ACCIONES = ["agregar", "completar", "reabrir", "reprogramar", "quitar_fecha", "editar", "credencial", "a_boveda", "mover", "borrar",
            "crear_proyecto", "apunte", "abrir"]

ESQUEMA_PREGUNTA = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string"},
        "acciones": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ACCIONES},
                "numeros": {"type": "array", "items": {"type": "integer"}},
                "clase": {"type": "string", "enum": ["", "tarea", "cita", "recordatorio", "compra", "idea", "dato"]},
                "texto": {"type": "string"},
                "fecha": {"type": "string"},
                "hora": {"type": "string"},
                "proyecto": {"type": "string"},
                "vista": {"type": "string", "enum": [""] + VISTAS_APP},
                "usuario": {"type": "string"},
                "clave": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["tipo", "numeros", "clase", "texto", "fecha", "hora", "proyecto", "vista", "usuario", "clave", "url"],
        }},
    },
    "required": ["respuesta", "acciones"],
}

INSTRUCCIONES_ACCIONES = """Además de responder, MANEJAS la app de notas: si te piden hacer algo, hazlo con 'acciones'.
Acciones (usa solo los campos que hagan falta; los demás van vacíos):
- agregar: nota nueva. clase (tarea, cita, recordatorio, compra, idea o dato), texto, fecha AAAA-MM-DD, hora HH:MM, proyecto.
- completar: marcar como hechas / quitar de pendientes / "ya lo hice". numeros.
- reabrir: volver a poner como pendiente algo de HECHAS. numeros (los H).
- reprogramar: cambiar fecha y/o hora. numeros, fecha, hora.
- quitar_fecha: dejarla sin fecha ni hora (sigue pendiente). numeros.
- editar: cambiar lo que dice una nota o su clase. numeros (uno), texto nuevo, clase.
- mover: poner notas en un proyecto (se crea si no existe). numeros, proyecto. Para sacarlas de su proyecto: proyecto "ninguno".
- borrar: SOLO si dice borrar o eliminar. numeros.
- crear_proyecto: proyecto (nombre), texto (descripción, opcional).
- apunte: escribir en los apuntes libres de un proyecto (información, enlaces, pasos, contactos, accesos, lo que sea). proyecto, texto.
  Si dice "guarda en las notas/apuntes de <proyecto>" algo que no es una tarea, usa apunte y copia el texto EXACTO (usuarios, claves, correos y números tal cual).
- credencial: SOLO si pide expresamente guardarlo en "Credenciales", "la bóveda" o "cifrado". proyecto, texto (nombre corto), usuario, clave, url.
- a_boveda: SOLO si pide pasar una nota a Credenciales/bóveda. numeros, texto (nombre corto).
- abrir: mostrar una pantalla de la app. vista (hoy, pendientes, proximas, calendario, hechas, todas, reuniones, cita, recordatorio, compra, idea, dato, michi, avisos) o vista "proyecto" + proyecto.
'numeros' son los números entre corchetes de las listas: pendientes [1], [2]…; hechas [101]…; otras notas [201]…
Puedes hacer varias acciones a la vez (ej.: crear un proyecto y mover tareas a él).
Si enumera VARIAS tareas o cosas (con "también", "y", comas o una lista), crea UNA acción agregar POR CADA una, con su propio texto corto.
Si pide "tareas", usa agregar con clase tarea (no apunte). Si dice "ahí" o "en ese proyecto", usa el PROYECTO DEL QUE SE HABLA.
Si solo es una pregunta, 'acciones' va vacía. Si no está claro a qué notas se refiere, no actúes y pregunta.
Nunca inventes números. No puedes leer la pestaña Credenciales (sí los apuntes y las notas): si te piden algo guardado allí, di que está en esa pestaña.
IMPORTANTE: nada cambia si no pones la acción en 'acciones'.
En 'respuesta': si es una pregunta, respóndela (sin escribir los números [N]). Si son cambios, pon solo "Ok".

Ejemplos:
"anota que mañana a las 3 tengo dentista" → agregar, clase cita, texto "Dentista", fecha de mañana, hora 15:00.
"pasa la 2 y la 4 al proyecto Sputniq" → mover, numeros [2,4], proyecto "Sputniq".
"cambia lo de Carlos para el viernes" → reprogramar, numeros [el de Carlos], fecha del viernes.
"quítale la fecha a lo del banco" → quitar_fecha, numeros [el del banco].
"ábreme el calendario" → abrir, vista "calendario".
"guarda en los apuntes de TIODOL que el logo va en azul" → apunte, proyecto "TIODOL", texto "El logo va en azul".
"guarda en las notas de Motocard admin@x.com clave Abc123" → apunte, proyecto "Motocard", texto "admin@x.com clave Abc123".
"agrega a Tiodol: cambiar el botón de refrescar por una línea y también mover el monto debajo del débito" → DOS acciones agregar, clase tarea, proyecto "Tiodol": "Cambiar el botón de refrescar por una línea" y "Mover el monto debajo del débito"."""


def _numerar(nota, prefijo):
    extra = [_cuando(nota)] if nota["casilla"] and not nota["hecho"] else ([nota["fecha"]] if nota["fecha"] else [])
    if nota["proyecto"]:
        extra.append(f"proyecto {nota['proyecto']}")
    return f"[{prefijo}] {comun.NOMBRE_TIPO.get(nota['tipo'], 'Dato')}: {nota['texto']}" + (
        f" — {' · '.join(extra)}" if extra else "")


# ---------------------------------------------------------------- contraseñas: siempre a la bóveda cifrada

import re as _re
PALABRAS_SECRETAS = _re.compile(r"\b(contrase(n|ñ)a|password|passwd|clave|credencial(es)?|token|api ?key|secret|pin|pass)\b", _re.I)


def parece_secreto(texto):
    """Tiene una palabra como 'clave' o 'contraseña' Y algo con pinta de contraseña."""
    texto = texto or ""
    return bool(PALABRAS_SECRETAS.search(texto)) and bool(_trozos_secretos([texto + " x"]))


def _proyecto_boveda(nombre):
    return comun.asegurar_proyecto(nombre) if (nombre or "").strip() else comun.asegurar_proyecto("Personal")


def guardar_credencial(proyecto, nombre, usuario, clave, url, nota):
    import boveda
    boveda.guardar({"proyecto": proyecto, "nombre": nombre, "usuario": usuario, "clave": clave or "",
                    "url": url, "nota": nota})


def _trozos_secretos(secretos):
    """Palabras que parecen contraseñas o tokens dentro de lo que se guardó en la bóveda."""
    trozos = set()
    normales = {comun.normalizar(x["nombre"]) for x in comun.listar_proyectos()}
    for s in secretos:
        s = (s or "").strip()
        if not s:
            continue
        if " " not in s:
            trozos.add(s)
        for p in _re.split(r"[\s,;]+", s):
            p = p.strip(".:()\"'")
            if _re.fullmatch(r"\d{1,2}(:\d\d)?(am|pm)?|\d{4}-\d\d-\d\d|\d{1,2}/\d{1,2}(/\d{2,4})?", p, _re.I):
                continue  # horas y fechas
            if len(p) >= 4 and "@" not in p and not p.lower().startswith("http") and (
                    (_re.search(r"\d", p) and not _re.fullmatch(r"\d{1,2}(:\d\d)?|\d{4}-\d\d-\d\d", p)) or (len(p) >= 6 and ( _re.search(r"[^\w]", p) or (_re.search(r"[a-z]", p) and _re.search(r"[A-Z]", p[1:]))))) and comun.normalizar(p) not in normales:
                trozos.add(p)
    return sorted(trozos, key=len, reverse=True)


def tapar(texto, secretos):
    for t in _trozos_secretos(secretos):
        texto = texto.replace(t, "••••••")
    return texto


def _dice_que_hizo(texto):
    """¿La respuesta afirma en primera persona que cambió algo? (sin ser una pregunta)"""
    if "?" in texto:
        return False
    t = comun.normalizar(texto)
    return bool(_re.search(r"\b(he|ya|fue|fueron|ha sido|han sido|quedo|quedaron) ?(eliminad|borrad|quitad|marcad|movid|cambiad|"
                           r"actualizad|reprogramad|agregad|anotad|cread|guardad|puest|abiert|añadid|anadid)|\b(elimine|borre|"
                           r"quite|marque|movi|cambie|actualice|reprograme|agregue|anote|guarde|puse|cree|anadi)\b|^listo\b", t))


ORDEN = _re.compile(r"\b(agrega|agregale|agregar|anade|añade|anota|apunta|crea|crear|creame|pon|ponle|ponla|ponlas|coloca|"
                    r"mete|mueve|muevela|pasa|pasala|pasalas|cambia|cambiale|modifica|edita|borra|borrala|elimina|quita|"
                    r"quitale|quitala|quitalas|marca|marcala|reprograma|guarda|guardalo|abre|abreme|muestrame|registra|"
                    r"programa|recuerdame|completa|termina)\b", _re.I)


def _parece_orden(texto):
    return bool(ORDEN.search(comun.normalizar(texto)))


def _proyecto_mencionado(texto, ultimo=""):
    """El proyecto que nombra el mensaje (o el de la charla si dice 'ahí' / 'ese proyecto')."""
    t = " " + comun.normalizar(texto) + " "
    mejor = ""
    for p in comun.listar_proyectos():
        n = comun.normalizar(p["nombre"])
        if n and (f" {n} " in t or f" {n.replace(' ', '')} " in t) and len(n) > len(mejor):
            mejor = p["nombre"]
    if mejor:
        return mejor
    if ultimo and _re.search(r"\b(ahi|alli|ese proyecto|este proyecto|el mismo proyecto|ahi mismo)\b", t):
        return ultimo
    return ""


def _ultimo_proyecto():
    try:
        with open(CONVERSACION, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if time.time() - datos.get("t", 0) < 30 * 60:
            return datos.get("proyecto", "")
    except Exception:
        pass
    return ""


def _cuando_txt(fecha, hora):
    f, h = comun.limpiar_fecha(fecha), comun.limpiar_hora(hora)
    if not f and not h:
        return ""
    return _cuando({"fecha": f, "hora": h}) if f else f"a las {h}"


def _planear(datos, buscar, pregunta, ultimo):
    """Convierte lo que pidió la IA en una lista de pasos claros, revisados por el programa."""
    plan, ir = [], None
    proy_msg = _proyecto_mencionado(pregunta, ultimo)
    pide_tareas = bool(_re.search(r"\btareas?\b", comun.normalizar(pregunta))) and "apunte" not in comun.normalizar(pregunta)
    for acc in datos.get("acciones") or []:
        tipo = acc.get("tipo")
        texto = (acc.get("texto") or "").strip()
        proyecto = (acc.get("proyecto") or "").strip()
        if tipo in ("agregar", "apunte") and proy_msg:
            proyecto = proy_msg  # el proyecto que TÚ nombraste manda sobre el que adivina la IA
        if tipo == "apunte" and pide_tareas:
            tipo, acc = "agregar", dict(acc, clase="tarea")
        existente = comun.buscar_proyecto(proyecto) if proyecto else None
        nombre_p = existente["nombre"] if existente else proyecto
        en = f" en {nombre_p}" if nombre_p else ""
        nuevo = " (proyecto nuevo)" if proyecto and not existente else ""
        if tipo == "agregar" and texto:
            clase = acc.get("clase") or "tarea"
            cuando = _cuando_txt(acc.get("fecha"), acc.get("hora"))
            plan.append({"tipo": tipo, "clase": clase, "texto": texto, "fecha": acc.get("fecha", ""),
                         "hora": acc.get("hora", ""), "proyecto": nombre_p,
                         "desc": f"Anotar {comun.NOMBRE_TIPO.get(clase, 'Dato').lower()} «{texto}»{en}{nuevo}"
                                 + (f" — {cuando}" if cuando else "")})
        elif tipo == "crear_proyecto" and proyecto:
            if existente:
                continue
            plan.append({"tipo": tipo, "proyecto": proyecto, "texto": texto, "desc": f"Crear el proyecto {proyecto}"})
        elif tipo == "apunte" and texto and (proyecto or proy_msg):
            plan.append({"tipo": tipo, "proyecto": nombre_p, "texto": texto,
                         "desc": f"Escribir en los apuntes de {nombre_p}{nuevo}: «{texto}»"})
        elif tipo == "credencial" and (acc.get("clave") or acc.get("usuario")):
            plan.append({"tipo": tipo, "proyecto": nombre_p or "Personal", "nombre": texto or "Acceso",
                         "usuario": acc.get("usuario", ""), "clave": acc.get("clave", ""), "url": acc.get("url", ""),
                         "desc": f"Guardar el acceso «{texto or 'Acceso'}» en Credenciales de {nombre_p or 'Personal'}"})
        elif tipo == "abrir":
            v = acc.get("vista") or ""
            if v == "proyecto" or (not v and proyecto):
                p = comun.buscar_proyecto(proyecto or proy_msg)
                ir = f"p:{p['nombre']}" if p else ir
            elif v in VISTAS_APP:
                ir = v
        elif tipo in ("completar", "reabrir", "reprogramar", "quitar_fecha", "editar", "mover", "borrar", "a_boveda"):
            if tipo == "mover":
                quitar = comun.normalizar(proyecto) in ("ninguno", "sin proyecto")
                proyecto = "" if quitar else (proyecto or proy_msg)
                if not proyecto and not quitar:
                    continue
                existente = comun.buscar_proyecto(proyecto) if proyecto else None
                nombre_p = existente["nombre"] if existente else proyecto
            for num in dict.fromkeys(acc.get("numeros") or []):
                nota = buscar(num)
                if not nota:
                    continue
                t = nota["texto"]
                if tipo == "completar" and (not nota["casilla"] or nota["hecho"]):
                    continue
                if tipo == "reabrir" and not nota["hecho"]:
                    continue
                if tipo == "quitar_fecha" and not (nota["fecha"] or nota["hora"]):
                    continue
                if tipo == "reprogramar" and not (comun.limpiar_fecha(acc.get("fecha")) or comun.limpiar_hora(acc.get("hora"))):
                    continue
                if tipo == "editar" and not texto and acc.get("clase") in ("", None, nota["tipo"]):
                    continue
                if tipo == "mover" and nota["proyecto"] == nombre_p:
                    continue
                desc = {
                    "completar": f"Marcar como hecha «{t}»",
                    "reabrir": f"Volver a poner pendiente «{t}»",
                    "reprogramar": f"Cambiar la fecha de «{t}» → {_cuando_txt(acc.get('fecha') or nota['fecha'], acc.get('hora') or nota['hora'])}",
                    "quitar_fecha": f"Quitarle la fecha a «{t}»",
                    "editar": f"Cambiar «{t}» por «{texto or t}»",
                    "mover": f"Mover «{t}» → " + (f"{nombre_p}{' (proyecto nuevo)' if proyecto and not existente else ''}" if nombre_p else "sin proyecto"),
                    "borrar": f"Borrar «{t}»",
                    "a_boveda": f"Pasar «{t[:40]}…» a Credenciales",
                }[tipo]
                plan.append({"tipo": tipo, "linea": nota["linea"], "texto": texto, "clase": acc.get("clase") or "",
                             "fecha": acc.get("fecha", ""), "hora": acc.get("hora", ""), "proyecto": nombre_p,
                             "nombre": texto or "Acceso", "desc": desc})
                if tipo == "editar":
                    break
    return plan, ir


# ---------------------------------------------------------------- aplicar (y deshacer)

PLAN = os.path.join(comun.TEMPORAL, "plan_pendiente.json")
DESHACER = os.path.join(comun.TEMPORAL, "deshacer.json")


def _leer_archivo(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _foto(plan):
    """Guarda cómo estaba todo antes de cambiarlo, para poder deshacer."""
    rutas = [comun.NOTAS, comun.PROYECTOS, os.path.join(comun.DATOS, "boveda.json")]
    rutas += [comun.ruta_apuntes(p["proyecto"]) for p in plan if p["tipo"] == "apunte"]
    with open(DESHACER, "w", encoding="utf-8") as f:
        json.dump({"t": time.time(), "archivos": {r: _leer_archivo(r) for r in rutas}}, f, ensure_ascii=False)


def deshacer():
    try:
        with open(DESHACER, "r", encoding="utf-8") as f:
            foto = json.load(f)
    except Exception:
        return {"ok": False, "mensaje": "No hay nada que deshacer."}
    for ruta, contenido in foto["archivos"].items():
        if contenido is None:
            if os.path.exists(ruta):
                os.remove(ruta)
        else:
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
    os.remove(DESHACER)
    return {"ok": True, "mensaje": "Listo, dejé todo como estaba antes.", "cambios": 1}


def aplicar_plan(plan):
    _foto(plan)
    hechos, fallos, cambiadas = [], [], {}
    for paso in plan:
        tipo = paso["tipo"]
        try:
            if tipo == "agregar":
                comun.agregar_nota(paso["clase"], paso["texto"], paso["fecha"], paso["hora"], proyecto=paso["proyecto"])
                ok = True
            elif tipo == "crear_proyecto":
                comun.asegurar_proyecto(paso["proyecto"], paso.get("texto", ""))
                ok = True
            elif tipo == "apunte":
                nombre = comun.asegurar_proyecto(paso["proyecto"])
                previo = comun.leer_apuntes(nombre).rstrip()
                comun.guardar_apuntes(nombre, (previo + "\n" if previo else "") + f"- {paso['texto']}\n")
                ok = True
            elif tipo == "credencial":
                guardar_credencial(_proyecto_boveda(paso["proyecto"]), paso["nombre"], paso["usuario"], paso["clave"],
                                   paso["url"], "")
                ok = True
            else:
                linea = cambiadas.get(paso["linea"], paso["linea"])
                nota = next((n for n in comun.listar_notas() if n["linea"] == linea), None)
                if not nota:
                    ok = False
                elif tipo == "a_boveda":
                    guardar_credencial(_proyecto_boveda(nota["proyecto"]), paso["nombre"], "", "", "", nota["texto"])
                    ok = comun.reemplazar_linea(nota["linea"], None)
                else:
                    destino = comun.asegurar_proyecto(paso["proyecto"]) if tipo == "mover" and paso["proyecto"] else ""
                    ok = _aplicar_a(nota, tipo, fecha=paso["fecha"], hora=paso["hora"], texto=paso["texto"],
                                    clase=paso["clase"], proyecto=destino)
                    if ok:
                        cambiadas[paso["linea"]] = nota["linea"]
        except Exception:
            log.exception("No pude hacer el paso %s", paso.get("desc"))
            ok = False
        (hechos if ok else fallos).append(paso["desc"])
    lineas = [f"✓ {h}" for h in hechos] + [f"✗ No pude: {f}" for f in fallos]
    return {"ok": True, "mensaje": "\n".join(lineas), "cambios": len(hechos), "hechos": hechos, "fallos": fallos}


def aplicar_plan_guardado(indices):
    try:
        with open(PLAN, "r", encoding="utf-8") as f:
            plan = json.load(f)["plan"]
        os.remove(PLAN)
    except Exception:
        return {"ok": False, "mensaje": "Ese cambio ya no está disponible. Pídemelo de nuevo."}
    elegidos = [p for i, p in enumerate(plan) if i in set(indices)]
    if not elegidos:
        return {"ok": True, "mensaje": "No hice ningún cambio.", "cambios": 0}
    return aplicar_plan(elegidos)


# ---------------------------------------------------------------- preguntar / pedir

def _pensar(modelo, sistema, usuario):
    try:
        return leer_json(conversar(modelo, sistema, usuario, formato=ESQUEMA_PREGUNTA, contexto=12288))
    except Exception:
        log.exception("La respuesta de %s no vino en el formato esperado", modelo)
        return None


def modo_pregunta(pregunta, confirmar=False):
    asegurar_ollama()
    pend = _pendientes()
    todas = comun.listar_notas()
    hechas = sorted([n for n in todas if n["hecho"]], key=lambda n: -n["orden"])[:15]
    otras = [n for n in todas if not n["casilla"]][-60:]
    extra = comun.contexto_para_pregunta(pregunta, limite=8000, solo_extra=True)
    charla = "\n".join(f"Pregunta: {t['p']}\nRespuesta: {t['r']}" for t in _conversacion())
    ultimo = _ultimo_proyecto()
    proy_msg = _proyecto_mencionado(pregunta, ultimo)
    sistema = (
        f"Eres Miauia, el asistente personal de {QUIEN}. Respondes en español, breve y directo, usando SOLO "
        "la información que te doy. La lista TAREAS PENDIENTES es la verdad: si tiene elementos, hay "
        "pendientes (menciónalos, empezando por los atrasados y los de hoy). Cuando hables de fechas, di el día.\n\n"
        + INSTRUCCIONES_ACCIONES
    )
    usuario = (
        f"Ahora es {comun.fecha_larga()}.\nCalendario:\n{comun.calendario_proximo()}\n\n"
        f"=== PROYECTOS ===\n{comun.proyectos_para_ia()}\n\n"
        f"=== TAREAS PENDIENTES ({len(pend)}) ===\n"
        + ("\n".join(_numerar(n, i) for i, n in enumerate(pend, 1)) or "(ninguna)")
        + "\n\n=== HECHAS HACE POCO ===\n"
        + ("\n".join(_numerar(n, 100 + i) for i, n in enumerate(hechas, 1)) or "(ninguna)")
        + "\n\n=== OTRAS NOTAS (ideas y datos) ===\n"
        + ("\n".join(_numerar(n, 200 + i) for i, n in enumerate(otras, 1)) or "(ninguna)")
        + (f"\n\n=== REUNIONES Y APUNTES ===\n{extra}" if extra else "")
        + (f"\n\n=== CONVERSACIÓN RECIENTE ===\n{charla}" if charla else "")
        + (f"\n\nPROYECTO DEL QUE SE HABLA: {proy_msg} (si el mensaje pide anotar algo, va en este proyecto)" if proy_msg else "")
        + f"\n\nMensaje: {pregunta}"
    )

    def buscar(num):
        if 1 <= num <= len(pend):
            return pend[num - 1]
        if 101 <= num <= 100 + len(hechas):
            return hechas[num - 101]
        if 201 <= num <= 200 + len(otras):
            return otras[num - 201]
        return None

    orden = _parece_orden(pregunta)
    modelos = [CFG["modelo_rapido"]]
    if orden and CFG.get("modelo_reunion") and CFG["modelo_reunion"] != CFG["modelo_rapido"]:
        modelos.append(CFG["modelo_reunion"])  # si la rápida no entiende la orden, prueba la grande
    datos, plan, ir = None, [], None
    for modelo in modelos:
        intento = _pensar(modelo, sistema, usuario)
        if intento is None:
            continue
        datos = intento
        plan, ir = _planear(datos, buscar, pregunta, ultimo)
        log.info("IA %s · acciones: %s · plan: %s", modelo,
                 json.dumps(datos.get("acciones"), ensure_ascii=False)[:1500], [p["desc"] for p in plan])
        if plan or ir or not orden:
            break
    if datos is None:
        datos = {"respuesta": conversar(CFG["modelo_rapido"], sistema.split("Además de responder")[0], usuario)}

    respuesta = (datos.get("respuesta") or "").strip()
    resultado = {"ok": True, "titulo": "Respuesta", "pregunta": pregunta, "ir": ir, "cambios": 0}
    if plan:
        # el texto lo escribe el programa: así nunca dice que hizo algo distinto de lo que hace
        if confirmar:
            with open(PLAN, "w", encoding="utf-8") as f:
                json.dump({"t": time.time(), "plan": plan}, f, ensure_ascii=False)
            resultado.update(mensaje="Esto es lo que voy a hacer:", plan=[p["desc"] for p in plan])
            resumen = "Propuse: " + "; ".join(p["desc"] for p in plan)
        else:
            hecho = aplicar_plan(plan)
            resultado.update(mensaje=hecho["mensaje"], cambios=hecho["cambios"], deshacer=True)
            resumen = hecho["mensaje"]
    elif orden or _dice_que_hizo(respuesta):
        resultado["mensaje"] = ("No hice ningún cambio: no entendí bien qué querías que hiciera. "
                                "Prueba más directo, por ejemplo: «agrega en Tiodol la tarea revisar el botón de refrescar».")
        resumen = resultado["mensaje"]
    else:
        resultado["mensaje"] = respuesta or "No sé qué responder a eso."
        resumen = resultado["mensaje"]
    _recordar(pregunta, resumen, proy_msg or next((p["proyecto"] for p in plan if p.get("proyecto")), "") or ultimo)
    return resultado


ESQUEMA_REUNION = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "proyecto": {"type": "string"},
        "resumen": {"type": "string"},
        "decisiones": {"type": "array", "items": {"type": "string"}},
        "tareas": {"type": "array", "items": {
            "type": "object",
            "properties": {"tarea": {"type": "string"}, "responsable": {"type": "string"},
                           "fecha": {"type": "string"}},
            "required": ["tarea", "responsable", "fecha"],
        }},
        "pendientes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "proyecto", "resumen", "decisiones", "tareas", "pendientes"],
}


def _partir(texto, tamano):
    trozos, actual = [], []
    largo = 0
    for linea in texto.split("\n"):
        if largo + len(linea) > tamano and actual:
            trozos.append("\n".join(actual))
            actual, largo = [], 0
        actual.append(linea)
        largo += len(linea) + 1
    if actual:
        trozos.append("\n".join(actual))
    return trozos


def resumir_reunion(transcripcion):
    modelo = CFG["modelo_reunion"]
    contexto = int(CFG["contexto_reunion"])
    material = transcripcion
    limite = contexto * 2  # unos 2 caracteres por token deja margen de sobra
    if len(material) > limite:
        parciales = []
        trozos = _partir(material, limite)
        for n, trozo in enumerate(trozos, 1):
            parciales.append(conversar(
                modelo,
                "Eres un asistente que toma apuntes de reuniones en español.",
                f"Esta es la parte {n} de {len(trozos)} de una reunión. Anota en viñetas los temas, "
                f"las decisiones y las tareas (con responsable y fecha si se mencionan).\n\n{trozo}",
                contexto=contexto, mantener="5m"))
        material = "\n\n".join(f"Apuntes parte {i}:\n{p}" for i, p in enumerate(parciales, 1))

    sistema = (
        f"Eres el asistente de {QUIEN} y resumes reuniones en español sencillo. 'Yo' es {QUIEN}; "
        "'Otros' son las demás personas (usa sus nombres si se mencionan). Devuelve JSON con: "
        "titulo (máx. 8 palabras), proyecto (el nombre exacto de uno de sus proyectos si la reunión "
        "es claramente sobre él; si no, vacío), resumen (un párrafo), decisiones, tareas (tarea, "
        "responsable, fecha AAAA-MM-DD o vacía) y pendientes (temas que quedaron abiertos). No inventes nada."
    )
    usuario = (f"Fecha de la reunión: {comun.fecha_larga()}.\nCalendario:\n{comun.calendario_proximo()}\n\n"
               f"Proyectos:\n{comun.proyectos_para_ia()}\n\n"
               f"{material}")
    return leer_json(conversar(modelo, sistema, usuario, formato=ESQUEMA_REUNION, contexto=contexto))


def modo_reunion(audio_mic, audio_sistema, inicio_txt):
    rapido = False
    mios = transcribir(audio_mic, CFG["whisper_reunion"], rapido) if audio_mic else []
    otros = transcribir(audio_sistema, CFG["whisper_reunion"], rapido) if audio_sistema else []
    mios = quitar_eco(mios, otros)
    transcripcion = unir_transcripcion(mios, otros)
    if not transcripcion.strip():
        return {"ok": False, "titulo": "Reunión", "mensaje": "No se escuchó nada en la grabación."}

    fin = max([f for _, f, _ in mios + otros] or [0])
    momento = comun.ahora()
    nombre = f"{momento:%Y-%m-%d_%H%M}_reunion.md"
    ruta = os.path.join(comun.REUNIONES, nombre)

    try:
        asegurar_ollama()
        r = resumir_reunion(transcripcion)
        error_ia = None
    except Exception as e:
        log.exception("No se pudo resumir la reunión")
        r, error_ia = {}, str(e)

    titulo = (r.get("titulo") or "Reunión").strip()
    proyecto = comun.asegurar_proyecto(r.get("proyecto", "")) if (r.get("proyecto") or "").strip() else ""
    md = [f"# {titulo}", "",
          f"Fecha: {inicio_txt or comun.fecha_larga(momento)} · Duración aprox.: {max(1, round(fin / 60))} min"]
    md += [f"Proyecto: {proyecto}", ""] if proyecto else [""]
    if error_ia:
        md += ["> No se pudo hacer el resumen automático: " + error_ia, ""]
    else:
        md += ["## Resumen", "", r.get("resumen", "").strip(), ""]
        md += ["## Decisiones", ""] + ([f"- {d}" for d in r.get("decisiones") or []] or ["- (ninguna)"]) + [""]
        filas_tareas = []
        for t in r.get("tareas") or []:
            extra = []
            if (t.get("responsable") or "").strip():
                extra.append(f"responsable: {t['responsable'].strip()}")
            if comun.limpiar_fecha(t.get("fecha")):
                extra.append(f"fecha: {t['fecha']}")
            filas_tareas.append(f"- [ ] {(t.get('tarea') or '').strip()}" + (f" ({', '.join(extra)})" if extra else ""))
        md += ["## Tareas", ""] + (filas_tareas or ["- (ninguna)"]) + [""]
        md += ["## Temas pendientes", ""] + ([f"- {p}" for p in r.get("pendientes") or []] or ["- (ninguno)"]) + [""]
    md += ["## Transcripción", "", transcripcion, ""]
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    for t in r.get("tareas", []) if not error_ia else []:
        texto = (t.get("tarea") or "").strip()
        responsable = (t.get("responsable") or "").strip()
        if texto:
            if responsable and responsable.lower() not in ("yo", "andrés", "andres"):
                texto += f" (responsable: {responsable})"
            comun.agregar_nota("tarea", texto, t.get("fecha"), "", origen=titulo, proyecto=proyecto)
    comun.agregar_nota("dato", f"Reunión «{titulo}», resumen en reuniones/{nombre}", proyecto=proyecto)

    n = len(r.get("tareas", [])) if not error_ia else 0
    mensaje = f"«{titulo}»: {n} tarea(s) anotadas." if not error_ia else "Guardé la transcripción, pero sin resumen."
    return {"ok": True, "titulo": "Reunión lista", "mensaje": mensaje, "archivo": ruta}


# ---------------------------------------------------------------- entrada

def preparar():
    """Descarga Whisper la primera vez (lo usa el instalador)."""
    from faster_whisper import WhisperModel
    for modelo in {CFG["whisper_rapido"], CFG["whisper_reunion"]}:
        print(f"Preparando Whisper '{modelo}'...", flush=True)
        WhisperModel(modelo, device="cpu", compute_type="int8")
    print("Whisper listo.", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--modo", choices=["nota", "pregunta", "reunion"])
    p.add_argument("--audio")
    p.add_argument("--audio-sistema")
    p.add_argument("--texto")
    p.add_argument("--inicio")
    p.add_argument("--proyecto", default="")
    p.add_argument("--salida")
    p.add_argument("--preparar", action="store_true")
    p.add_argument("--confirmar", action="store_true")
    p.add_argument("--aplicar-plan")
    p.add_argument("--deshacer", action="store_true")
    a = p.parse_args()

    if a.preparar:
        preparar()
        return
    if a.aplicar_plan is not None or a.deshacer:
        r = deshacer() if a.deshacer else aplicar_plan_guardado(json.loads(a.aplicar_plan or "[]"))
        texto = json.dumps(r, ensure_ascii=False)
        if a.salida:
            with open(a.salida, "w", encoding="utf-8") as f:
                f.write(texto)
        else:
            print(texto)
        return

    audios = [x for x in (a.audio, a.audio_sistema) if x]
    try:
        if a.modo == "reunion":
            resultado = modo_reunion(a.audio, a.audio_sistema, a.inicio)
        else:
            texto = a.texto
            if not texto and a.audio:
                partes = transcribir(a.audio, CFG["whisper_rapido"], rapido=True)
                texto = " ".join(t for _, _, t in partes).strip()
            if not texto:
                resultado = {"ok": False, "titulo": "No te escuché",
                             "mensaje": "No se entendió nada. Revisa el micrófono y prueba de nuevo."}
            elif a.modo == "nota":
                resultado = modo_nota(texto, a.proyecto)
            else:
                resultado = modo_pregunta(texto, confirmar=a.confirmar)
        borrar = resultado.get("ok") and not (a.modo == "reunion" and CFG["guardar_audio_reuniones"])
    except Exception as e:
        log.error("Falló el modo %s: %s", a.modo, traceback.format_exc())
        resultado = {"ok": False, "titulo": "Algo falló", "mensaje": str(e)}
        borrar = False  # dejamos el audio por si quieres recuperarlo

    if borrar:
        for ruta in audios:
            try:
                os.remove(ruta)
            except OSError:
                pass

    salida = json.dumps(resultado, ensure_ascii=False)
    if a.salida:
        with open(a.salida, "w", encoding="utf-8") as f:
            f.write(salida)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(salida)


if __name__ == "__main__":
    main()
