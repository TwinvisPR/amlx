@echo off
REM ============================================================================
REM  Apple Music Library Exporter - one-click launcher for Windows
REM
REM  Double-click this file (or run it in a terminal). It will:
REM    1. use Python if you already have it, otherwise
REM    2. download a small PORTABLE Python (~11 MB, no install, no admin rights)
REM       into a local ".python" folder next to this script, then
REM    3. run the exporter. Any arguments you pass are forwarded, e.g.:
REM         run.bat --out my_export
REM         run.bat --cdn-fallback
REM
REM  The portable Python is the official "embeddable" build from python.org.
REM  Nothing is installed system-wide; delete the ".python" folder to remove it.
REM ============================================================================
setlocal enableextensions
cd /d "%~dp0"

REM --- 1) Use an existing Python if one is on PATH -----------------------------
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 extract.py %*
    goto :done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python extract.py %*
    goto :done
)

REM --- 2) Reuse a portable Python we downloaded earlier ------------------------
set "PYDIR=%~dp0.python"
set "PYEXE=%PYDIR%\python.exe"
if exist "%PYEXE%" (
    "%PYEXE%" extract.py %*
    goto :done
)

REM --- 3) Bootstrap a portable Python ------------------------------------------
set "PYVER=3.12.7"
set "ZIP=python-%PYVER%-embed-amd64.zip"
set "URL=https://www.python.org/ftp/python/%PYVER%/%ZIP%"

echo No Python found. Downloading a portable copy (~11 MB, no install)...
where curl >nul 2>nul
if not %errorlevel%==0 (
    echo ERROR: curl.exe was not found. Please install Python from
    echo   https://www.python.org/downloads/  ^(tick "Add to PATH"^) and re-run.
    goto :fail
)
curl.exe -L --fail -o "%TEMP%\%ZIP%" "%URL%"
if not %errorlevel%==0 (
    echo ERROR: download failed. Check your internet connection.
    goto :fail
)
if not exist "%PYDIR%" mkdir "%PYDIR%"
tar.exe -xf "%TEMP%\%ZIP%" -C "%PYDIR%"
if not %errorlevel%==0 (
    echo ERROR: could not extract the archive ^(tar.exe missing?^).
    goto :fail
)
del "%TEMP%\%ZIP%" >nul 2>nul

if not exist "%PYEXE%" (
    echo ERROR: portable Python did not unpack as expected.
    goto :fail
)
"%PYEXE%" extract.py %*
goto :done

:fail
echo.
echo Export did not run. See the message above.
pause
exit /b 1

:done
echo.
pause
