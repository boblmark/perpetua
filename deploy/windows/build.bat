@echo off
REM Perpetua Windows 构建脚本
REM 在 Windows 上运行：build.bat
REM 需要：Python 3.10+, pip

echo === Perpetua Windows 构建 ===
echo.

echo [1/4] 检查 Python...
python --version || (echo 需要 Python 3.10+ && exit /b 1)

echo [2/4] 安装依赖...
pip install -r requirements.txt
pip install nuitka

echo [3/4] Nuitka 编译 MCP 服务器...
python -m nuitka --onefile --output-dir=build --output-filename=perpetua-mcp.exe --windows-console-mode=disable src/server.py

echo [4/4] 完成
dir build\perpetua-mcp.exe
echo.
echo 构建完成，运行 dist_installer.bat 制作安装包
