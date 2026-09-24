# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from cfdns.cloudflare import Cloudflare
from cfdns.config import ENV_FILENAME, TOKEN_ENV_VAR, Config, ConfigError, load
from cfdns.logfile import RotatingLogHandler
from cfdns.sync import sync

LOG_LEVELS = {1: logging.ERROR, 2: logging.INFO, 3: logging.DEBUG}


def setup_logging(cfg: Config, verbose: bool = False) -> None:
    if not cfg.log_enabled and not verbose:
        logging.basicConfig(handlers=[logging.NullHandler()], force=True)
        return

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if cfg.log_enabled:
        log_path = cfg.resolved_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingLogHandler(
                log_path,
                mode=cfg.log_rotate,
                max_size=cfg.log_max_size,
                backups=cfg.log_backups,
            )
        )

    logging.basicConfig(
        level=logging.DEBUG if verbose else LOG_LEVELS.get(cfg.log_level, logging.INFO),
        format="%(asctime)s\t%(levelname)s\t%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cf-dns-sync",
        description="Point Cloudflare DNS records at this machine's public IP.",
    )
    parser.add_argument("-c", "--config", help="path to config.ini")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log debug output to stdout"
    )
    args = parser.parse_args(argv)

    try:
        cfg = load(args.config)
    except ConfigError as err:
        print(f"config error: {err}", file=sys.stderr)
        return 2

    setup_logging(cfg, verbose=args.verbose)

    if cfg.token_source == "config.ini":
        logging.warning(
            "your API token is still in config.ini. Move it to %s as %s=... "
            "and delete the [CloudFlare-API] token line.",
            cfg.source.parent / ENV_FILENAME,
            TOKEN_ENV_VAR,
        )

    with Cloudflare(cfg.token) as api:
        failures = sync(cfg, api)

    if failures:
        logging.error("%d of %d records failed to sync", failures, len(cfg.records))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
