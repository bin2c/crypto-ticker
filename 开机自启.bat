@echo off
rem 把行情小窗加入 Windows 开机启动（在启动文件夹里建快捷方式）
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP%\行情小窗.lnk"
set "PYW="
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  if exist "G:\python3.13\pythonw.exe" set "PYW=G:\python3.13\pythonw.exe"
)
if not defined PYW (
  echo [x] 找不到 pythonw.exe，请先确认 Python 已加入 PATH。
  pause & exit /b 1
)
powershell -NoProfile -Command ^
  "$s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut('%LINK%'); $l.TargetPath='%PYW%'; $l.Arguments='ticker.py'; $l.WorkingDirectory='%~dp0'; $l.Description='加密货币行情小窗'; $l.Save()"
if exist "%LINK%" (
  echo [√] 已设置开机自启。删除下面这个文件即可取消：
  echo     %LINK%
) else (
  echo [x] 创建快捷方式失败。
)
pause
