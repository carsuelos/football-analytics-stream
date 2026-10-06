# /// script
# requires-python = ">=3.13"
# dependencies = ["certifi"]
# ///
"""Download StatsBomb open data for one competition season into data/statsbomb/.

Mirrors the upstream layout (competitions.json, matches/, events/, lineups/) and
skips files that already exist unless --force is given.

Data source: https://github.com/statsbomb/open-data. The data is free for
non-commercial use under StatsBomb's terms, which require attribution;
see their repository's LICENSE before using it.
"""

import argparse
import json
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import certifi

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "statsbomb"
# Standalone Python builds (e.g. uv-managed) may not see the OS trust store.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def download(rel_path: str, out_dir: Path, force: bool) -> bool:
    """Download BASE_URL/rel_path to out_dir/rel_path. Returns True if fetched."""
    dest = out_dir / rel_path
    if dest.exists() and not force:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(f"{BASE_URL}/{rel_path}", timeout=60, context=SSL_CONTEXT) as resp:
        tmp.write_bytes(resp.read())
    tmp.replace(dest)
    return True


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download StatsBomb open data.")
    parser.add_argument("--competition", default="FIFA World Cup")
    parser.add_argument("--season", default="2022")
    parser.add_argument(
        "--match-id",
        type=int,
        action="append",
        help="Only fetch these matches (repeatable). Default: every match in the season.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true", help="Re-download existing files.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    out_dir: Path = args.out
    download("competitions.json", out_dir, args.force)
    seasons = [
        c
        for c in load(out_dir / "competitions.json")
        if c["competition_name"] == args.competition and c["season_name"] == args.season
    ]
    if not seasons:
        print(f"No StatsBomb open data for {args.competition!r} {args.season!r}.", file=sys.stderr)
        return 1
    comp_id, season_id = seasons[0]["competition_id"], seasons[0]["season_id"]

    matches_rel = f"matches/{comp_id}/{season_id}.json"
    download(matches_rel, out_dir, args.force)
    available = [m["match_id"] for m in load(out_dir / matches_rel)]

    match_ids: list[int] = args.match_id or available
    unknown = sorted(set(match_ids) - set(available))
    if unknown:
        print(f"Match ids not in this season: {unknown}", file=sys.stderr)
        return 1

    files = [f"{kind}/{mid}.json" for mid in match_ids for kind in ("events", "lineups")]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fetched = sum(pool.map(lambda rel: download(rel, out_dir, args.force), files))

    print(
        f"{args.competition} {args.season} (competition {comp_id}, season {season_id}): "
        f"{len(match_ids)} matches, {fetched} files downloaded, "
        f"{len(files) - fetched} already present -> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
