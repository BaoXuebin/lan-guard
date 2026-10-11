"""启动入口：python -m backend.run [--config path]

同时启动 HTTP（查看端，默认 8080）与 HTTPS（推流端，默认 8443，需证书）。
iOS 摄像头要求页面必须是 HTTPS，推流端请访问 https://<电脑IP>:<https_port>/push
"""
import argparse
import asyncio
import os
from pathlib import Path

import uvicorn

from .config import Config


def main():
    parser = argparse.ArgumentParser(description="宝宝睡眠监控服务端")
    parser.add_argument("--config", default=str(Config().path), help="config.yaml 路径")
    args = parser.parse_args()
    os.environ["BM_CONFIG"] = args.config

    cfg = Config(Path(args.config))
    from .main import app  # BM_CONFIG 设置后再导入

    servers = []
    servers.append(uvicorn.Config(
        app, host=cfg["server"]["host"], port=int(cfg["server"]["port"]),
        log_level="info",
    ))

    https_port = int(cfg["server"].get("https_port", 8443) or 0)
    cert = Path(cfg["server"].get("ssl_certfile", ""))
    key = Path(cfg["server"].get("ssl_keyfile", ""))
    if https_port and cert.is_file() and key.is_file():
        servers.append(uvicorn.Config(
            app, host=cfg["server"]["host"], port=https_port,
            ssl_certfile=str(cert), ssl_keyfile=str(key),
            log_level="info",
        ))
    else:
        print("[run] 未找到 HTTPS 证书，跳过推流端（推流需 HTTPS，见 tools/make_certs.sh）")

    async def serve_all():
        await asyncio.gather(*(uvicorn.Server(s).serve() for s in servers))

    asyncio.run(serve_all())


if __name__ == "__main__":
    main()
