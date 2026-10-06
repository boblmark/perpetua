@echo off
REM Perpetua Windows 一键安装包制作
REM 把编译好的 exe + 配置打包成安装程序目录

set PKG=perpetua-windows-installer
if exist %PKG% rmdir /s /q %PKG%
mkdir %PKG%

echo [1/3] 复制程序...
copy build\perpetua-mcp.exe %PKG%\
copy ..\systemd\local_proxy.py %PKG%\ 2>nul

echo [2/3] 复制安装脚本...
copy install.bat %PKG%\

echo [3/3] 复制说明...
copy README_WINDOWS.md %PKG%\ 2>nul

echo 完成：%PKG%\
