@echo off
REM Remove Lumina Widget from Windows startup.
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lumina Widget.lnk"
if exist "%LNK%" (
  del "%LNK%"
  echo Removed startup shortcut.
) else (
  echo No startup shortcut found.
)
