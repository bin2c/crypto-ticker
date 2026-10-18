@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   行情条 - 打包成单文件 exe（免装 Python）
echo ============================================
echo.

set PY=G:\python3.13\python.exe
if not exist "%PY%" set PY=python

echo [1/4] 检查 PyInstaller...
"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo      没装，正在安装（只装这一次）...
  "%PY%" -m pip install --upgrade pip pyinstaller
  if errorlevel 1 (
    echo.
    echo   × 安装失败。多半是网络/代理问题，手动执行：
    echo       "%PY%" -m pip install pyinstaller
    pause
    exit /b 1
  )
) else (
  echo      已安装
)

echo.
echo [2/4] 清理旧的构建产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/4] 开始打包（第一次要 1-3 分钟）...
rem --add-data 把图表库塞进 exe；分号在 Windows 上是分隔符
"%PY%" -m PyInstaller ^
  --noconfirm --clean --onefile --noconsole ^
  --name "行情条" ^
  --icon "assets\行情条.ico" ^
  --add-data "lightweight-charts.js;." ^
  --add-data "assets\行情条.ico;assets" ^
  ticker.py
if errorlevel 1 (
  echo.
  echo   × 打包失败，看上面最后几行报错
  pause
  exit /b 1
)

echo.
echo [3.5/4] 把 exe 复制一份到仓库根目录（开始菜单快捷方式指向这里）...
copy /y "dist\行情条.exe" "行情条.exe" >nul
if errorlevel 1 echo   ! 复制失败，可能行情条.exe 正在运行，先退出它再打一次

echo.
echo [4/4] 收尾：把示例配置和启动器放进 dist
copy /y "config.example.json" "dist\config.example.json" >nul
copy /y "启动.vbs" "dist\启动.vbs" >nul 2>nul

echo.
echo ============================================
echo   完成！产物在： dist\行情条.exe
echo   发给别人时：把 dist\行情条.exe 单独发过去就行
echo   （它自带图表库，不需要 Python，也不需要联网安装任何东西）
echo.
echo   第一次运行会在 exe 旁边自动生成 config.json / ticker.log
echo ============================================
pause
