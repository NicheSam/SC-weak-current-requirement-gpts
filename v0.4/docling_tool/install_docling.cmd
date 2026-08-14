@echo off
setlocal
set "ROOT=%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.12 first.
  pause
  exit /b 1
)
py -3.12 -m venv "%ROOT%.venv"
if errorlevel 1 goto :failed
"%ROOT%.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%docling\requirements.in"
if errorlevel 1 goto :failed
echo.
echo Docling installation completed.
pause
exit /b 0

:failed
echo.
echo Docling installation failed. Review the messages above.
pause
exit /b 1
