"""uvicorn 启动入口：`python -m bhzd_py.main`。

host/port 来自配置（BHZD_HOST/BHZD_PORT），不在此处写死，保证部署只改环境。
"""

from __future__ import annotations

import uvicorn

from .config import get_config


def main() -> None:
    """按配置启动开发服务器。"""
    config = get_config()
    uvicorn.run("bhzd_py.app:app", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
