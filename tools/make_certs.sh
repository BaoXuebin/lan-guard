#!/usr/bin/env bash
# 生成本地 CA + 服务端证书（自签，供局域网 HTTPS 使用）
# 用法: bash tools/make_certs.sh <电脑局域网IP>   例: bash tools/make_certs.sh 192.168.0.103
# iPhone 使用前需一次性安装并信任 deploy/cert/ca.crt（见 docs/iphone-setup.md）
set -e
export MSYS_NO_PATHCONV=1  # Git Bash 下防止 /CN= 被当作路径转换

IP="${1:?用法: bash tools/make_certs.sh <局域网IP>}"
DIR="$(cd "$(dirname "$0")/../deploy/cert" && pwd)"
mkdir -p "$DIR"
cd "$DIR"

echo "==> 生成 CA（ca.key 务必保管好，绝不能提交或泄露）"
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout ca.key -out ca.crt -subj "/CN=baby-monitor-local-ca"

echo "==> 生成服务端证书（SAN: IP $IP, localhost）"
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=baby-monitor"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 3650 \
  -extfile <(printf "subjectAltName=IP:%s,IP:127.0.0.1,DNS:localhost" "$IP") \
  -out server.crt
rm -f server.csr ca.srl

echo "==> 完成: $DIR"
ls -la "$DIR"
echo ""
echo "下一步: 把 ca.crt 传到 iPhone 安装并信任（docs/iphone-setup.md）"
