"""``python -m flab2bp.web`` -- the same entry point as ``flab2bp-web``."""

from __future__ import annotations

from flab2bp.web.server import main

if __name__ == "__main__":
    raise SystemExit(main())
