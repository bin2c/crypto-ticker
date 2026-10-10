@echo off
rem 无控制台窗口启动行情小窗
cd /d "%~dp0"
start "" pythonw.exe ticker.py %*
