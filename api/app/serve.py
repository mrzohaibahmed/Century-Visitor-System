"""
Production API server (what the Windows service runs):

    python -m app.serve [--host 127.0.0.1] [--port 8000] [--workers 1]

- Only with CG_ENVIRONMENT=production: a service can never come up with
  development settings (API docs on, plain-HTTP cookies, local database).
  All production checks in Settings run first (database login + TLS, photo
  folder, secure cookies) and a wrong setting stops the start with a clear
  message.
- No auto-reload, no debug. The interactive API docs stay off (CG_API_DOCS).
- Listens on 127.0.0.1 only: the HTTPS reverse proxy (Caddy) on the same
  server is the only way in. Gate PCs never reach this port.
- Logs are JSON lines on stderr; the service wrapper (WinSW) writes them to
  files and rotates them.

Development still uses:  uvicorn app.main:create_app --factory --reload
"""
import argparse
import sys

import uvicorn
from pydantic import ValidationError

from app.core.config import Settings, configuration_problems


def uvicorn_options(settings: Settings, host: str, port: int, workers: int) -> dict:
    return {
        "app": "app.main:create_app", "factory": True, "host": host, "port": port, "workers": workers,
        "reload": False,
        "log_config": None,          # the application's JSON logging (app.core.logging) is used as is
        "access_log": False,         # the request middleware logs each request, without query strings
        "server_header": False,
        "proxy_headers": False,      # client IPs come from X-Forwarded-For of trusted proxies only (core/net.py)
        "timeout_graceful_shutdown": 20,
        "log_level": settings.log_level.lower(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.serve", description="Century Gate VMS API (production)")
    parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1, loopback only)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 9), metavar="1-8")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError as e:
        print(f"ERROR: configuration is not valid: {configuration_problems(e)}", file=sys.stderr)
        return 2
    if settings.environment != "production":
        print("ERROR: app.serve is the production server and needs CG_ENVIRONMENT=production. "
              "For development use: uvicorn app.main:create_app --factory --reload", file=sys.stderr)
        return 2
    uvicorn.run(**uvicorn_options(settings, args.host, args.port, args.workers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
