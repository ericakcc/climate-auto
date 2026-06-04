"""Uvicorn launcher for the local web editor (binds to localhost by default)."""

import argparse
from pathlib import Path

import uvicorn

from climate_auto.web.app import DEFAULT_CONFIG_PATH, build_app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Build and serve the editor app.

    Args:
        host: Interface to bind. Defaults to localhost; the editor runs LLM
            calls and writes files, so exposing it on the network is opt-in.
        port: TCP port to listen on.
        config_path: Path to the settings YAML.
    """
    app = build_app(config_path=config_path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    """CLI entry point for ``climate-auto-web``."""
    parser = argparse.ArgumentParser(description="Climate Auto local report editor")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default 127.0.0.1; set to expose on LAN).",
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to listen on (default 8765)."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to settings YAML (default config/settings.yaml).",
    )
    args = parser.parse_args()
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    run_server(host=args.host, port=args.port, config_path=config_path)


if __name__ == "__main__":
    main()
