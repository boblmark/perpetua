@echo off
REM Perpetua Windows 一键安装
REM 以管理员身份运行

echo === Perpetua Windows 一键安装 ===
echo.

echo [1/5] 创建数据目录...
mkdir C:\Perpetua\data 2>nul
mkdir C:\Perpetua\bin 2>nul

echo [2/5] 复制程序...
copy perpetua-mcp.exe C:\Perpetua\bin\

echo [3/5] 生成 MCP Token...
powershell -Command "$t=[Convert]::ToBase64String((1..32 | ForEach {[byte](Get-Random -Max 256)})); Set-Content -Path C:\Perpetua\data\.token -Value $t"
echo Token 已生成：C:\Perpetua\data\.token

echo [4/5] 注册 Windows 服务...
sc create PerpetuaMCP binPath= "C:\Perpetua\bin\perpetua-mcp.exe" start= auto
sc description PerpetuaMCP "Perpetua MCP Server by ViralLoop"

echo [5/5] 启动服务...
sc start PerpetuaMCP

echo.
echo === 安装完成 ===
echo MCP 地址：http://127.0.0.1:8734/mcp
echo 数据目录：C:\Perpetua\data
echo.
echo 后续手动步骤：
echo 1. YouTube OAuth: 将 .oauth.json 放到 C:\Perpetua\data\youtube\
echo 2. TypeSafe API Key: 将 key 写入 C:\Perpetua\data\jev\.api_key
pause
