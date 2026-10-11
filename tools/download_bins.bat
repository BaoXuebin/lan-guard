@echo off
rem 下载 MediaMTX 与 ffmpeg（Windows x64）到 tools/bin/
rem github.com 直连不通时自动走 gh-proxy.com 镜像
cd /d "%~dp0"
mkdir bin 2>nul

set PROXY=
curl -s -o nul --max-time 8 https://github.com || set PROXY=https://gh-proxy.com/
echo 使用镜像: %PROXY% (空表示直连)

if not exist bin\mediamtx\mediamtx.exe (
  curl -L -o mediamtx.zip "%PROXY%https://github.com/bluenviron/mediamtx/releases/download/v1.11.3/mediamtx_v1.11.3_windows_amd64.zip"
  unzip -o -q mediamtx.zip -d bin/mediamtx || tar -xf mediamtx.zip -C bin/mediamtx
  del mediamtx.zip
)

if not exist bin\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe (
  curl -L -o ffmpeg.zip "%PROXY%https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
  unzip -o -q ffmpeg.zip -d bin/ || tar -xf ffmpeg.zip -C bin/
  del ffmpeg.zip
)

echo 完成。mediamtx 与 ffmpeg 已就绪。
