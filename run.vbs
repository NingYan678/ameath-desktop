Option Explicit

' Launch the development desktop pet without creating a visible cmd.exe window.
Dim shell, root, command
Set shell = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & root & "\run.bat" & Chr(34) & " --background"
shell.Run command, 0, False
