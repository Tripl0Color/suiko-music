' Runs the bot silently in the background (no console window).
' Place a SHORTCUT to this file in shell:startup to auto-start with Windows.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' -- Automatically uses the folder where this .vbs file lives --
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)

' -- Run the .exe --
WshShell.CurrentDirectory = projectDir
WshShell.Run """" & projectDir & "\YTMusicBot.exe""", 0, False
