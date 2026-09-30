# Cómo publicar Miauia (guía para Andrés)

## La primera vez

1. Crea una cuenta en https://github.com si no tienes.
2. Instala **GitHub Desktop**: https://desktop.github.com
3. En GitHub Desktop: *File → Add local repository* → elige la carpeta `Documentos\Asistente`
   (si pregunta, toca *create a repository here*). Nombre: **miauia**.
4. Toca **Publish repository**. Puede ser público o privado.
   - Si es **privado**, las personas no podrán descargar ni actualizar. Para compartir Miauia, hazlo **público**.
   - Tus notas NO se suben: la carpeta `datos/` y `config.json` están excluidas (`.gitignore`).

## Publicar una versión (la primera y cada actualización)

1. Haz tus cambios y en GitHub Desktop toca **Commit** y luego **Push**.
2. Ve a la página del repositorio en github.com → **Releases → Draft a new release**.
3. En *Choose a tag* escribe la versión nueva con una **v** adelante, por ejemplo `v1.0.0`, `v1.0.1`, `v1.1.0`
   (siempre más alta que la anterior) → *Create new tag*.
4. Escribe qué cambió (eso lo verá la gente al actualizar) y toca **Publish release**.
5. En unos 3 minutos GitHub construye solo el instalador `Miauia-Setup-1.0.0.exe` y lo agrega al release
   (lo ves en la pestaña **Actions** mientras trabaja).

Listo: quien tenga Miauia instalada verá "✨ Nueva versión" y podrá actualizar con un clic.
El enlace para compartir es: https://github.com/skol25/miauia/releases/latest
