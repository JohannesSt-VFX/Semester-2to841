@echo off
REM ===========================================================================
REM  Build Lumina Widget as a standalone Windows 11 app  ->  dist\Lumina.exe
REM
REM  Produces a single windowed .exe (no console window) that you can
REM  double-click, pin to the taskbar, or drop into shell:startup.
REM
REM  Usage:  just run  build_exe.bat   from this folder.
REM ===========================================================================
setlocal

echo [1/4] Installing dependencies...
python -m pip install --upgrade pip                 || goto :err
python -m pip install -r requirements.txt           || goto :err
python -m pip install pyinstaller                    || goto :err

echo [2/4] Generating app icon...
python make_icon.py                                  || goto :err

echo [3/4] Building Lumina.exe (windowed, single file)...
pyinstaller --noconfirm --clean ^
    --name Lumina ^
    --onefile ^
    --windowed ^
    --icon lumina.ico ^
    --add-data "lumina.ico;." ^
    --hidden-import wmi ^
    --hidden-import win32com ^
    --hidden-import win32com.client ^
    main.py                                          || goto :err

echo [4/4] Done.  Your app is here:  dist\Lumina.exe
echo Double-click it, or run  install_startup.bat  to launch it at login.
goto :eof

:err
echo.
echo Build failed. Make sure Python 3.11+ is installed and on PATH.
exit /b 1
