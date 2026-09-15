"""Runs the server with settings from the environment:  python -m app"""

import uvicorn

from app.main import load_settings


def main() -> None:
    settings = load_settings()
    # One process: the background feed refresher must not run in several workers.
    uvicorn.run(
        "app.main:create_app", factory=True, host=settings.host, port=settings.port,
        proxy_headers=True, forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
