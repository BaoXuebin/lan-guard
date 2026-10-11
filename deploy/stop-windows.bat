@echo off
rem 停止 baby-monitor 与 MediaMTX（按窗口标题）
taskkill /FI "WindowTitle eq MediaMTX*" /T /F 2>nul
taskkill /FI "WindowTitle eq baby-monitor*" /T /F 2>nul
echo 已停止
