# Prepara el Python propio de Miauia y sus librerías (lo ejecuta el instalador).
param([Parameter(Mandatory = $true)][string]$Carpeta)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$uv = Join-Path $Carpeta 'instalacion\uv.exe'
$venv = Join-Path $Carpeta '.venv'
$py = Join-Path $venv 'Scripts\python.exe'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Carpeta 'python'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_CACHE_DIR = Join-Path $env:LOCALAPPDATA 'Miauia\cache'
$env:UV_LINK_MODE = 'copy'
$env:UV_NO_PROGRESS = '1'

function Ejecutar($descripcion, [scriptblock]$bloque, $codigo) {
    Write-Output $descripcion
    & $bloque 2>&1 | ForEach-Object { "   $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Output "ERROR: $descripcion (código $LASTEXITCODE)"
        exit $codigo
    }
}

Ejecutar 'Descargando Python 3.12 (solo la primera vez)...' { & $uv python install 3.12 } 11
Ejecutar 'Creando el entorno de Miauia...' { & $uv venv $venv --python 3.12 --allow-existing } 12
Ejecutar 'Instalando librerías (voz, ventanas, michis)...' { & $uv pip install --python $py -r (Join-Path $Carpeta 'requirements.txt') } 13
Ejecutar 'Comprobando que todo funcione...' { & $py -c "import tkinter, webview, faster_whisper, pystray, keyboard, pyaudiowpatch, PIL; print('Todo en orden')" } 14
exit 0
