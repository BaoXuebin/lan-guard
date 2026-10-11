@echo off
rem 一键启动：MediaMTX + 监控服务（需先完成 config.yaml / .env 配置）
cd /d "%~dp0\.."

start "MediaMTX" /min tools\bin\mediamtx\mediamtx.exe deploy\mediamtx.yml
start "baby-monitor" /min .venv\Scripts\python.exe -m backend.run

echo 已启动：
echo   网页监控:  http://127.0.0.1:8080  （手机用电脑局域网IP访问）
echo   停止方式:  运行 stop-windows.bat
