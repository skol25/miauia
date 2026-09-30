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
                _aplicar_a(pend[n - 1], "completar")
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


def _aplicar_a(nota, tipo, fecha="", hora=""):
    if tipo == "borrar":
        return comun.reemplazar_linea(nota["linea"], None)
    nueva = dict(nota)
    if tipo == "completar":
        nueva.update(hecho=True, fecha_hecho="")
    elif tipo == "reabrir":
        nueva.update(hecho=False, fecha_hecho="")
    elif tipo == "reprogramar":
        nueva.update(fecha=comun.limpiar_fecha(fecha) or nota["fecha"], hora=comun.limpiar_hora(hora) or nota["hora"])
    return comun.reemplazar_linea(nota["linea"], comun.componer_linea(nueva))


def _conversacion():
    try:
        with open(CONVERSACION, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if time.time() - datos.get("t", 0) < 30 * 60:  # la charla "se olvida" tras 30 minutos
            return datos.get("turnos", [])
    except Exception:
        pass
    return []


def _recordar(pregunta, respuesta):
    turnos = (_conversacion() + [{"p": pregunta, "r": respuesta}])[-3:]
    with open(CONVERSACION, "w", encoding="utf-8") as f:
        json.dump({"t": time.time(), "turnos": turnos}, f, ensure_ascii=False)


ESQUEMA_PREGUNTA = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string"},
        "acciones": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["completar", "reabrir", "reprogramar", "borrar"]},
                "numeros": {"type": "array", "items": {"type": "integer"}},
                "fecha": {"type": "string"},
                "hora": {"type": "string"},
            },
            "required": ["tipo", "numeros", "fecha", "hora"],
        }},
    },
    "required": ["respuesta", "acciones"],
}


def modo_pregunta(pregunta):
    asegurar_ollama()
    pend = _pendientes()
    todas = comun.listar_notas()
    hechas = sorted([n for n in todas if n["hecho"]], key=lambda n: -n["orden"])[:12]
    otras = [n["linea"] for n in todas if not n["casilla"]]
    extra = comun.contexto_para_pregunta(pregunta, limite=9000, solo_extra=True)
    charla = "\n".join(f"Pregunta: {t['p']}\nRespuesta: {t['r']}" for t in _conversacion())
    sistema = (
        f"Eres Miauia, el asistente personal de {QUIEN}. Respondes en español, breve y directo, usando SOLO "
        "la información que te doy. La lista TAREAS PENDIENTES es la verdad: si tiene elementos, hay "
        "pendientes (menciónalos, empezando por los atrasados y los de hoy). Cuando hables de fechas, di el día.\n"
        "Además de responder, puedes ACTUAR sobre las tareas si te lo piden claramente:\n"
        "- completar: marcar como hechas / quitar de pendientes / 'ya lo hice'.\n"
        "- reabrir: volver a poner como pendiente algo de HECHAS (usa su número H).\n"
        "- reprogramar: cambiar la fecha (AAAA-MM-DD) o la hora (HH:MM).\n"
        "- borrar: SOLO si dice borrar o eliminar.\n"
        "En 'numeros' pon los números [N] de la lista (para reabrir, los números de HECHAS). "
        "Si solo es una pregunta, 'acciones' va vacía. Si la petición es ambigua, no actúes y pregunta. "
        "En 'respuesta' cuenta lo que hiciste o responde la pregunta."
    )
    usuario = (
        f"Ahora es {comun.fecha_larga()}.\nCalendario:\n{comun.calendario_proximo()}\n\n"
        f"=== TAREAS PENDIENTES ({len(pend)}) ===\n{_texto_pendientes(pend) or '(ninguna)'}\n\n"
        f"=== HECHAS HACE POCO ===\n" + ("\n".join(f"[H{100 + i}] {n['texto']}" for i, n in enumerate(hechas, 1)) or "(ninguna)")
        + f"\n\n=== NOTAS, IDEAS Y DATOS ===\n" + ("\n".join(otras[-40:]) or "(ninguna)")
        + (f"\n\n=== REUNIONES Y APUNTES ===\n{extra}" if extra else "")
        + (f"\n\n=== CONVERSACIÓN RECIENTE ===\n{charla}" if charla else "")
        + f"\n\nMensaje: {pregunta}"
    )
    try:
        datos = leer_json(conversar(CFG["modelo_rapido"], sistema, usuario, formato=ESQUEMA_PREGUNTA))
    except Exception:
        log.exception("La respuesta no vino en el formato esperado; pregunto sin acciones")
        datos = {"respuesta": conversar(CFG["modelo_rapido"], sistema.split("Además de responder")[0], usuario), "acciones": []}

    hechos = []
    for acc in datos.get("acciones") or []:
        tipo = acc.get("tipo")
        for num in acc.get("numeros") or []:
            if tipo == "reabrir" and 101 <= num <= 100 + len(hechas):
                nota = hechas[num - 101]
            elif 1 <= num <= len(pend):
                nota = pend[num - 1]
            else:
                continue
            if _aplicar_a(nota, tipo, acc.get("fecha", ""), acc.get("hora", "")):
                hechos.append((tipo, nota["texto"]))
    respuesta = (datos.get("respuesta") or "").strip()
    if hechos:
        verbo = {"completar": "Marqué como hecha", "reabrir": "Volví a pendientes", "reprogramar": "Cambié la fecha de",
                 "borrar": "Borré"}
        resumen = "\n".join(f"✓ {verbo[t]}: {txt}" for t, txt in hechos)
        respuesta = f"{respuesta}\n\n{resumen}" if respuesta else resumen
    _recordar(pregunta, respuesta)
    return {"ok": True, "titulo": "Respuesta", "pregunta": pregunta, "mensaje": respuesta, "cambios": len(hechos)}


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
    a = p.parse_args()

    if a.preparar:
        preparar()
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
                resultado = modo_pregunta(texto)
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
