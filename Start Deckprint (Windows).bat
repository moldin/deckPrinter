@echo off
rem Double-click to start Deckprint. The first run sets things up (needs internet).
setlocal
cd /d "%~dp0"
title Deckprint

rem Python 3.9+ from python.org. "py" is the Python launcher; plain "python" may only be a
rem Microsoft Store shortcut, so check that it really runs.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo Python 3 is not installed.
  echo Install it from https://www.python.org/downloads/ - tick "Add python.exe to PATH" in the installer -
  echo and then double-click this file again.
  goto end
)

if not exist ".venv\Scripts\python.exe" (
  echo First start: setting up Deckprint ^(takes a minute^)...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not set up Deckprint ^(python -m venv failed^).
    goto end
  )
)

fc /b requirements.txt ".venv\installed.txt" >nul 2>nul
if errorlevel 1 (
  echo Installing the libraries Deckprint needs...
  ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo Could not install the libraries Deckprint needs. Check your internet connection and try again.
    goto end
  )
  copy /y requirements.txt ".venv\installed.txt" >nul
)

".venv\Scripts\python.exe" -m webapp.server

:end
echo.
pause
