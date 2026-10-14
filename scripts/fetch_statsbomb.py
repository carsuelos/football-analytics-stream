# /// script
# requires-python = ">=3.13"
# dependencies = ["certifi"]
# ///
"""Download StatsBomb open data for one competition season into data/statsbomb/.

Mirrors the upstream layout (competitions.json, matches/, events/, lineups/) and
skips files that already exist unless --force is given.

With --training, downloads the model's training data instead, into
data/training/statsbomb/: the events of every men's senior competition season
from TRAINING_SINCE on, except the season the model is tested on (--competition
and --season, the 2022 World Cup by default). About 2,550 matches and 7 GB.

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
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "statsbomb"
TRAINING_OUT = ROOT / "data" / "training" / "statsbomb"
# Older seasons are a handful of famous matches each, from a different game.
TRAINING_SINCE = 2003
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


def season_start(name: str) -> int:
    """The year a season starts: 2015 for "2015/2016", 2022 for "2022"."""
    return int(name[:4])


def training_seasons(
    competitions: list[dict[str, Any]], test_competition: str, test_season: str
) -> list[dict[str, Any]]:
    """Every men's senior season since TRAINING_SINCE, except the test season."""
    return [
        c
        for c in competitions
        if c["competition_gender"] == "male"
        and not c.get("competition_youth")
        and season_start(c["season_name"]) >= TRAINING_SINCE
        and not (c["competition_name"] == test_competition and c["season_name"] == test_season)
    ]


def fetch_training(args: argparse.Namespace) -> int:
    out_dir: Path = args.out or TRAINING_OUT
    download("competitions.json", out_dir, args.force)
    seasons = training_seasons(load(out_dir / "competitions.json"), args.competition, args.season)
    matches_rels = [f"matches/{c['competition_id']}/{c['season_id']}.json" for c in seasons]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda rel: download(rel, out_dir, args.force), matches_rels))
    match_ids = sorted({m["match_id"] for rel in matches_rels for m in load(out_dir / rel)})
    files = [f"events/{mid}.json" for mid in match_ids]
    print(
        f"Training data: {len(seasons)} seasons, {len(match_ids)} matches -> {out_dir}",
        flush=True,
    )
    done = fetched = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(lambda rel: download(rel, out_dir, args.force), files):
            done, fetched = done + 1, fetched + got
            if done % 200 == 0:
                print(f"  {done}/{len(files)}", flush=True)
    print(f"{fetched} files downloaded, {len(files) - fetched} already present")
    return 0


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
    parser.add_argument(
        "--training",
        action="store_true",
        help="Download the training data: every men's senior season since "
        f"{TRAINING_SINCE} except --competition --season (events only).",
    )
    parser.add_argument(
        "--out", type=Path, help=f"Default: {DEFAULT_OUT}, or {TRAINING_OUT} with --training."
    )
    parser.add_argument("--force", action="store_true", help="Re-download existing files.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    if args.training:
        return fetch_training(args)
    out_dir: Path = args.out or DEFAULT_OUT
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
