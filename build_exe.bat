@echo off
setlocal
cd /d "%~dp0"
set "OUTPUT_DIR=%~1"
if not defined OUTPUT_DIR set "OUTPUT_DIR=dist"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DesktopStickyNotes --distpath "%OUTPUT_DIR%" main.py
if errorlevel 1 (
    echo Build failed. Check the error above and ensure dependencies are installed.
    echo If the EXE is running, exit it normally or choose another output folder:
    echo build_exe.bat dist\hci
    exit /b 1
)
echo Build complete: %OUTPUT_DIR%\DesktopStickyNotes.exe
endlocal
