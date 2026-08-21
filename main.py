#!/usr/bin/env python3
# Author: Michael Dennis (https://github.com/mdennis281)
# Created: 09-26-2019
# Project Repository: https://github.com/mdennis281/Python-Cloudflare-DNS-External-IP-Synchronizer
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Entry point for running straight from a checkout (cron, Task Scheduler, ...).

Installed copies get the ``cf-dns-sync`` command instead; both land in the
same place.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfdns.cli import main  # noqa: E402  (needs the path above)

if __name__ == "__main__":
    raise SystemExit(main())
