$ErrorActionPreference = 'Stop'
$Carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Carpeta

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Fallo($texto) { Write-Host ""; Write-Host "ERROR: $texto" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- Python
Paso "Buscando Python (3.11, 3.12 o 3.13)"
$PyExe = $null
foreach ($v in '3.12', '3.11', '3.13') {
    try {
        $ruta = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ruta) { $PyExe = $ruta.Trim(); break }
    } catch {}
}
if (-not $PyExe) {
    $posible = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (Test-Path $posible) { $PyExe = $posible }
}
if (-not $PyExe) {
    Paso "No encontré Python. Instalando Python 3.12 con winget..."
    try {
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    } catch {
        Fallo "No pude instalar Python. Descárgalo de https://www.python.org/downloads/ (versión 3.12) y vuelve a ejecutar este instalador."
    }
    $PyExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $PyExe)) { Fallo "Python se instaló pero no lo encuentro. Cierra esta ventana y vuelve a ejecutar el instalador." }
}
Write-Host "Usando: $PyExe"

# ---------------------------------------------------------------- entorno propio
Paso "Preparando el entorno del asistente (solo la primera vez tarda)"
$VPy = Join-Path $Carpeta '.venv\Scripts\python.exe'
$VPyw = Join-Path $Carpeta '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $VPy)) {
    & $PyExe -m venv (Join-Path $Carpeta '.venv')
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo crear el entorno de Python." }
}
& $VPy -m pip install --upgrade pip --quiet
& $VPy -m pip install -r (Join-Path $Carpeta 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fallo "No se pudieron instalar las librerías. Revisa tu conexión y vuelve a intentar." }

# ---------------------------------------------------------------- Ollama y modelos
Paso "Revisando Ollama y los modelos"
$Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $Ollama) { $Ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if (-not (Test-Path $Ollama)) { Fallo "No encontré Ollama. Instálalo desde https://ollama.com/download/windows y vuelve a ejecutar este instalador." }

$config = Get-Content (Join-Path $Carpeta 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$lista = ''
try { $lista = (& $Ollama list 2>$null) -join "`n" } catch {}
if ($LASTEXITCODE -ne 0 -or -not $lista) {
    Start-Process $Ollama -ArgumentList 'serve' -WindowStyle Hidden
    Start-Sleep -Seconds 4
    $lista = (& $Ollama list) -join "`n"
}
foreach ($modelo in @($config.modelo_rapido, $config.modelo_reunion)) {
    if ($lista -match [regex]::Escape($modelo)) {
        Write-Host "OK  $modelo ya está instalado"
    } else {
        Write-Host "Descargando $modelo ..."
        & $Ollama pull $modelo
    }
}

# ---------------------------------------------------------------- Whisper
Paso "Descargando el modelo de voz a texto (Whisper), solo la primera vez"
& $VPy (Join-Path $Carpeta 'trabajador.py') --preparar
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo descargar Whisper. Revisa tu conexión y vuelve a intentar." }

# ---------------------------------------------------------------- accesos directos
Paso "Creando accesos directos (escritorio e inicio de Windows)"
$W = New-Object -ComObject WScript.Shell
function Acceso($ruta, $script, $descripcion, $icono) {
    $s = $W.CreateShortcut($ruta)
    $s.TargetPath = $VPyw
    $s.Arguments = '"' + (Join-Path $Carpeta $script) + '"'
    $s.WorkingDirectory = $Carpeta
    $s.Description = $descripcion
    $s.IconLocation = "$env:SystemRoot\System32\imageres.dll,$icono"
    $s.Save()
}
$Escritorio = [Environment]::GetFolderPath('Desktop')
Acceso (Join-Path ([Environment]::GetFolderPath('Startup')) 'Asistente.lnk') 'asistente.py' 'Asistente de notas y reuniones' 109
Acceso (Join-Path $Escritorio 'Asistente.lnk') 'asistente.py' 'Asistente de notas y reuniones' 109
Acceso (Join-Path $Escritorio 'Mis notas.lnk') 'notas_app.py' 'Ver y editar tus notas' 102

# ---------------------------------------------------------------- listo
Paso "Abriendo el asistente"
# si ya había una versión anterior abierta, la cerramos para que arranque la nueva
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*asistente.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800
Start-Process $VPyw -ArgumentList ('"' + (Join-Path $Carpeta 'asistente.py') + '"') -WorkingDirectory $Carpeta
Write-Host ""
Write-Host "Listo. Busca el ícono gris con un micrófono junto al reloj de Windows" -ForegroundColor Green
Write-Host "(si no lo ves, haz clic en la flechita ^ de la barra de tareas)." -ForegroundColor Green
Write-Host ""
Write-Host "Para ver tus notas: doble clic en el ícono o en 'Mis notas' del escritorio."
Write-Host "  Ctrl+Alt+N  anotar      Ctrl+Alt+P  preguntar      Ctrl+Alt+R  grabar reunión"
