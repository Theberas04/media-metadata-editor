@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Virtuele omgeving
python -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate

echo [2/4] Afhankelijkheden
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :error

echo [3/4] Logo en icoon
python tools\make_branding.py
if errorlevel 1 goto :error

echo [4/4] Applicatie bouwen
pyinstaller --noconfirm --clean --windowed --onedir ^
  --name "Media Metadata Editor" ^
  --icon "branding\app.ico" ^
  --add-data "branding;branding" ^
  --collect-binaries imageio_ffmpeg ^
  --collect-submodules imageio_ffmpeg ^
  --hidden-import PyQt5.QtMultimedia ^
  --hidden-import PyQt5.QtMultimediaWidgets ^
  main.py
if errorlevel 1 goto :error

copy /Y "version.txt" "dist\Media Metadata Editor\version.txt" >nul

echo.
echo Klaar: dist\Media Metadata Editor\Media Metadata Editor.exe
echo Lever de hele map "dist\Media Metadata Editor" mee.
exit /b 0

:error
echo.
echo Build mislukt. Zie de foutmelding hierboven.
exit /b 1