' Launch Lumina Widget with no console window (uses pythonw).
' Double-click this file to run the app straight from source — no build needed.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
' 0 = hidden window, False = don't wait for exit
sh.Run "pythonw """ & here & "\main.py""", 0, False
