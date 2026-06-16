@echo off
REM ===========================================================================
REM  Make Lumina Widget start automatically when you log in to Windows 11.
REM  Creates a shortcut in the current user's Startup folder.
REM
REM  Prefers the built exe (dist\Lumina.exe); falls back to run_lumina.vbs.
REM  Re-run after rebuilding.  Remove via:  uninstall_startup.bat
REM ===========================================================================
setlocal
set "HERE=%~dp0"
set "TARGET=%HERE%dist\Lumina.exe"
if not exist "%TARGET%" set "TARGET=%HERE%run_lumina.vbs"

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\Lumina Widget.lnk"

powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%HERE%';" ^
  "$s.IconLocation='%HERE%lumina.ico';" ^
  "$s.Save()"

if exist "%LNK%" (
  echo Installed: "%LNK%"
  echo Lumina will now start at login. Target: %TARGET%
) else (
  echo Failed to create startup shortcut.
)
