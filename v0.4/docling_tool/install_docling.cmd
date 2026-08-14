@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install_docling.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Docling installation completed.
) else (
  echo Docling installation failed. Review the messages above.
)
pause
exit /b %EXIT_CODE%
