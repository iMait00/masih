@echo off
REM ===========================================================
REM  Builds masih.exe - one file, no console, nothing to install.
REM  Messages are English on purpose: cmd.exe mangles UTF-8 in
REM  batch files on many systems. The app itself is Arabic.
REM  Run this only when you change the source.
REM ===========================================================
setlocal
title Masih - build
cd /d "%~dp0"

echo.
echo   ============================================
echo      Masih - building masih.exe
echo   ============================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY goto nopy

echo   [1/5] Python found.

echo   [2/5] Installing build dependencies...
%PY% -m pip install --quiet --upgrade pip
%PY% -m pip install --quiet fpdf2 uharfbuzz pypdf pyinstaller pdfplumber pillow pywebview pythonnet
if errorlevel 1 goto nodeps

echo   [3/5] Running tests...
%PY% -m unittest discover -s tests -q
if errorlevel 1 goto testfail
where node >nul 2>&1 && (
  node --test tests/quran-engine.test.mjs >nul 2>&1
  if errorlevel 1 goto testfail
) || echo         Node not found - skipping the Qur'an engine tests.

echo   [4/5] Generating the icon...
%PY% tools\make_icon.py >nul
if errorlevel 1 echo         Icon step failed - continuing with the previous icon.

echo   [5/5] Building the executable (about two minutes)...
%PY% -m PyInstaller masih.spec --noconfirm --distpath _dist --workpath _build >nul 2>&1
if not exist "_dist\masih.exe" goto buildfail

REM A running copy locks the file; replace it only when free.
if exist "masih.exe" del /q "masih.exe" 2>nul
if exist "masih.exe" goto locked
move /y "_dist\masih.exe" "masih.exe" >nul
rmdir /s /q _dist 2>nul
rmdir /s /q _build 2>nul

echo.
echo   ============================================
echo    Done.  masih.exe
echo.
echo    Double-click it. The app window opens.
echo    No install, no console, no separate files.
echo   ============================================
goto done

:nopy
echo   [!] Python is not installed. It is needed only to build.
echo       Download it and tick "Add python.exe to PATH".
start "" "https://www.python.org/downloads/"
goto done

:nodeps
echo   [!] Could not install the build dependencies.
echo       Try manually:  %PY% -m pip install fpdf2 uharfbuzz pypdf pyinstaller pywebview
goto done

:testfail
echo.
echo   [!] Tests failed - build stopped on purpose.
echo       A failing test here usually means Arabic shaping or the
echo       Qur'an checker is broken. Fix it before shipping.
echo       See the failures:  %PY% -m unittest discover -s tests -v
goto done

:locked
echo.
echo   [!] masih.exe is running and cannot be replaced.
echo       Close the app window, then run this again.
goto done

:buildfail
echo.
echo   [!] The build did not produce _dist\masih.exe.
echo       Run without silencing to see why:
echo       %PY% -m PyInstaller masih.spec --noconfirm
goto done

:done
echo.
pause
