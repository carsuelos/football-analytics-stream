# /// script
# requires-python = ">=3.13"
# dependencies = ["certifi"]
# ///
"""Download Karun Singh's published 12x8 expected-threat (xT) grid into data/xt/.

The grid comes from "Introducing Expected Threat (xT)" by Karun Singh,
https://karun.in/blog/expected-threat.html. It is published without a licence,
so it is downloaded at setup like the StatsBomb data and never committed.

The file is a JSON list of 8 rows (across the pitch) of 12 values (along it,
towards the opponent goal). It is checked for that shape before it is saved.
"""

import argparse
import json
import math
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

URL = "https://karun.in/blog/data/open_xt_12x8_v1.json"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "xt" / "open_xt_12x8_v1.json"
ROWS, COLS = 8, 12
# Standalone Python builds (e.g. uv-managed) may not see the OS trust store.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def check_shape(grid: object) -> None:
    """Raise ValueError unless grid is ROWS lists of COLS finite numbers >= 0."""
    if not isinstance(grid, list) or len(grid) != ROWS:
        raise ValueError(f"expected {ROWS} rows")
    for row in grid:
        if not isinstance(row, list) or len(row) != COLS:
            raise ValueError(f"expected {COLS} values per row")
        for v in row:
            if not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
                raise ValueError(f"not a non-negative number: {v!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the published 12x8 xT grid.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true", help="Re-download if present.")
    args = parser.parse_args(argv)

    out: Path = args.out
    if out.exists() and not args.force:
        print(f"xT grid already present -> {out}")
        return 0
    with urllib.request.urlopen(URL, timeout=60, context=SSL_CONTEXT) as resp:
        body = resp.read()
    try:
        check_shape(json.loads(body))
    except ValueError as e:
        print(f"Unexpected xT grid from {URL}: {e}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(out)
    print(f"xT grid (Karun Singh, karun.in) downloaded -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
