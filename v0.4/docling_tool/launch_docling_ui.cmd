@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\pythonw.exe"
set "APP=%ROOT%docling\docling_web_ui.py"
if not exist "%PYTHON%" (
  echo Docling Python environment was not found.
  echo Run install_docling.cmd first.
  pause
  exit /b 1
)
start "Docling PDF Source Converter" "%PYTHON%" "%APP%"
endlocal
