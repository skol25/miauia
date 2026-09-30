; Instalador de Miauia (NSIS). Se compila con herramientas/construir.py
Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Miauia"
!define PYW "$INSTDIR\.venv\Scripts\pythonw.exe"

Name "Miauia"
OutFile "${SALIDA}"
InstallDir "$LOCALAPPDATA\Programs\Miauia"
InstallDirRegKey HKCU "Software\Miauia" "Carpeta"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Miauia ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Miauia"
VIAddVersionKey "FileDescription" "Instalador de Miauia"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "Miauia"
VIAddVersionKey "LegalCopyright" "Miauia"

!define MUI_ICON "${RECURSOS}\miauia.ico"
!define MUI_UNICON "${RECURSOS}\miauia.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${RECURSOS}\instalador_lateral.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${RECURSOS}\instalador_lateral.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "${RECURSOS}\instalador_cabecera.bmp"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "¿Seguro que quieres cancelar la instalación de Miauia?"

!define MUI_WELCOMEPAGE_TITLE "Bienvenido a Miauia"
!define MUI_WELCOMEPAGE_TEXT "Miauia es tu asistente de notas, reuniones y recordatorios, con michis en la barra de Windows.$\r$\n$\r$\nTodo funciona dentro de tu PC, sin pagar nada.$\r$\n$\r$\nEl instalador prepara el programa (unos minutos). Al final se abre una ventana para descargar la IA (entre 3,5 y 9 GB, una sola vez)."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "¡Miauia está instalada!"
!define MUI_FINISHPAGE_TEXT "Falta un último paso: descargar la IA. Se abrirá una ventanita con tu michi que lo hace por ti."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir Miauia y terminar la configuración"
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirMiauia
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

!macro CerrarMiauia
  DetailPrint "Cerrando Miauia si está abierta..."
  nsExec::ExecToLog `powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -like '$INSTDIR\*' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
  Pop $0
  Sleep 800
!macroend

Section "Miauia (necesario)" SecApp
  SectionIn RO
  SetDetailsPrint both
  !insertmacro CerrarMiauia
  SetOutPath "$INSTDIR"
  File /r "${APPDIR}\*.*"

  DetailPrint "Preparando Python y las librerías (puede tardar unos minutos)..."
  nsExec::ExecToLog `powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\instalacion\preparar.ps1" -Carpeta "$INSTDIR"`
  Pop $0
  StrCmp $0 "0" preparado
    MessageBox MB_ICONSTOP "No se pudo preparar Miauia (código $0).$\r$\nRevisa tu conexión a internet y vuelve a ejecutar el instalador." /SD IDOK
    Abort
  preparado:

  ; accesos de la versión de prueba (carpeta Documentos\Asistente), para que no haya dos Miauias
  Delete "$DESKTOP\Asistente.lnk"
  Delete "$DESKTOP\Mis notas.lnk"
  Delete "$SMSTARTUP\Asistente.lnk"
  CreateShortcut "$SMPROGRAMS\Miauia.lnk" "${PYW}" '"$INSTDIR\notas_app.py"' "$INSTDIR\recursos\miauia.ico" 0 SW_SHOWNORMAL "" "Tus notas y michis"

  WriteUninstaller "$INSTDIR\Desinstalar Miauia.exe"
  WriteRegStr HKCU "Software\Miauia" "Carpeta" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "Miauia"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\recursos\miauia.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Miauia"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Desinstalar Miauia.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Desinstalar Miauia.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $1 $2 $3
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $1
SectionEnd

Section "Acceso directo en el escritorio" SecEscritorio
  CreateShortcut "$DESKTOP\Miauia.lnk" "${PYW}" '"$INSTDIR\notas_app.py"' "$INSTDIR\recursos\miauia.ico" 0 SW_SHOWNORMAL "" "Tus notas y michis"
  WriteRegDWORD HKCU "Software\Miauia" "Escritorio" 1
SectionEnd

Section "Michis al encender la PC" SecInicio
  CreateShortcut "$SMSTARTUP\Miauia.lnk" "${PYW}" '"$INSTDIR\asistente.py"' "$INSTDIR\recursos\miauia.ico" 0 SW_SHOWNORMAL "" "Michis y avisos de Miauia"
  WriteRegDWORD HKCU "Software\Miauia" "Inicio" 1
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "El programa, su Python propio y las librerías. Tus notas se guardan aparte y nunca se borran al actualizar."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecEscritorio} "Un ícono de huella en el escritorio para abrir tus notas."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecInicio} "Tus michis y los avisos arrancan solos al prender la PC. Casi no gasta nada mientras no los usas."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ; en una actualización silenciosa se respetan las opciones de la primera instalación
  IfSilent 0 fin
    ReadRegDWORD $0 HKCU "Software\Miauia" "Escritorio"
    StrCmp $0 "1" +2
      !insertmacro UnselectSection ${SecEscritorio}
    ReadRegDWORD $0 HKCU "Software\Miauia" "Inicio"
    StrCmp $0 "1" +2
      !insertmacro UnselectSection ${SecInicio}
  fin:
FunctionEnd

Function .onInstSuccess
  ; tras una actualización silenciosa, vuelven los michis
  IfSilent 0 +2
    Exec '"${PYW}" "$INSTDIR\asistente.py"'
FunctionEnd

Function AbrirMiauia
  Exec '"${PYW}" "$INSTDIR\notas_app.py"'
FunctionEnd

Section "Uninstall"
  !insertmacro CerrarMiauia
  Delete "$SMPROGRAMS\Miauia.lnk"
  Delete "$DESKTOP\Miauia.lnk"
  Delete "$SMSTARTUP\Miauia.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\Miauia"
  MessageBox MB_YESNO|MB_ICONQUESTION "¿Borrar también tus notas, reuniones y michis?$\r$\n(Si dices que no, siguen ahí si vuelves a instalar Miauia.)" /SD IDNO IDNO conservar
    RMDir /r "$APPDATA\Miauia"
  conservar:
  MessageBox MB_OK|MB_ICONINFORMATION "Listo. Ollama y los modelos de IA siguen instalados por si los usas con otros programas.$\r$\nSi quieres liberar ese espacio, desinstala Ollama desde Configuración de Windows." /SD IDOK
SectionEnd
