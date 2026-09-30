# 🐾 Miauia

Tu asistente de notas, reuniones y recordatorios **con michis en la barra de Windows**.
Todo funciona dentro de tu PC, sin internet y sin pagar nada.

- **Anota por voz** (`Ctrl + Alt + N`), **pregúntale a tus notas** (`Ctrl + Alt + P`) y **graba reuniones** (`Ctrl + Alt + R`) con resumen, decisiones y tareas.
- **Calendario, proyectos y avisos** a la hora de cada cita.
- **Michis pixel art** (esmoquin, calicó, siamés, atigrado…) que pasean por tu barra de tareas. Les puedes dar comida, premios y jugar con un estambre.

## Instalar

1. Descarga **`Miauia-Setup-X.Y.Z.exe`** desde [Releases](https://github.com/skol25/miauia/releases/latest).
2. Ábrelo y sigue los pasos (no pide permisos de administrador).
3. Al final se abre una ventanita que descarga la IA: **Ollama** y los modelos (entre 3,5 y 9 GB, una sola vez).

> Windows puede mostrar "Windows protegió su PC" porque el instalador no está firmado.
> Toca **Más información → Ejecutar de todas formas**.

**Requisitos:** Windows 10 u 11 de 64 bits, 8 GB de RAM (16 GB recomendado) y unos 12 GB libres.

## Actualizaciones

Miauia revisa sola si hay una versión nueva y te lo avisa. Toca **Actualizar** y listo:
tus notas y michis no se tocan (viven en `%APPDATA%\Miauia`).

## Desinstalar

Configuración de Windows → Aplicaciones → **Miauia** → Desinstalar.
Te pregunta si quieres borrar también tus notas. Ollama queda instalado por si lo usas con otros programas.

---

### Para desarrolladores

- `herramientas/construir.py --version 1.2.0 --repo usuario/miauia` crea el instalador en `dist/` (necesita NSIS).
- Al subir una etiqueta `v1.2.0` a GitHub, la acción **Publicar versión** construye el instalador y lo publica en Releases.
- `herramientas/generar_michi.py` redibuja los michis (`michi.json`); `herramientas/generar_iconos.py` los íconos.
