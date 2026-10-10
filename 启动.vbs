' 无窗口（不弹控制台）启动行情小窗，双击即可
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw.exe ticker.py", 0, False
