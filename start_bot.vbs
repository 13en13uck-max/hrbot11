Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\liamb\Desktop\hrbot"
WshShell.Run """C:\Users\liamb\Desktop\hrbot\.venv\Scripts\python.exe"" ""C:\Users\liamb\Desktop\hrbot\main.py""", 0, False
Set WshShell = Nothing
