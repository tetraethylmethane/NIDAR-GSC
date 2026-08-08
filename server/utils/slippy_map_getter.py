"""Pre-cache satellite map tiles for offline use.

WHY THIS EXISTS
Rule 8.4 prohibits internet connectivity during mission execution, and the
client is hard-wired to /map/{z}/{x}/{y}.png for exactly that reason. If those
files are not on disk, the operator gets a BLANK MAP during a scored mission --
no boundary, no survivors, no aircraft. This script is the only thing standing
between us and that, and it is the only place in the repo permitted to touch
the internet. scripts/check-no-network.sh scans client/src, not here.

WHEN TO RUN IT
Weeks before the competition, over a GENEROUS region around the venue. The
mission area is not known until the organisers hand over the KML during setup,
and by then there is no network to fetch tiles with. Guessing a small box and
being 2 km off is the same as having no tiles at all. Err large: zoom 16 over
20 km square is a few thousand tiles and a couple of hundred megabytes.

    python utils/slippy_map_getter.py --center 13.0,80.0 --radius-km 10 \
        --zoom 10-18 --dry-run          # see the cost first
    python utils/slippy_map_getter.py --center 13.0,80.0 --radius-km 10 \
        --zoom 10-18 --yes

    python utils/slippy_map_getter.py --verify      # re-check what is on disk

WHAT CHANGED FROM THE INHERITED VERSION, AND WHY IT MATTERED
The original wrote `r.content` to a .png without ever looking at it. A 404
page, a rate-limit body or a truncated response therefore landed on disk as a
plausible-looking tile, and because the resume check was `os.path.isfile`, it
was then skipped forever. You would end up with a cache that appeared complete,
had never errored, and rendered as grey squares on mission day -- discovered at
the worst possible moment. Every tile is now checked for the PNG signature
before it is written, and --verify re-checks the ones already on disk.

It also asked three interactive questions, which meant it could not run from a
script, and defaulted to 38.14,-76.42 -- a field in Maryland, left over from the
AUVSI competition this codebase came from.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

# `requests` is imported inside download_tiles(), not here. --dry-run and
# --verify must work on the mission laptop, which is deliberately a minimal
# offline install; needing an HTTP library to check that offline tiles are
# intact would be a poor joke.

# Relative to server/. The client serves client/public/map at /map.
MAP_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "client", "public", "map"))
MAP_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
           "World_Imagery/MapServer/tile")
REQUEST_TIMEOUT = 10

# Magic numbers for the image formats a tile server may legitimately return.
#
# NOTE: ArcGIS World_Imagery answers a ".png" request with a JPEG. Checking for
# a PNG signature specifically -- which is the obvious way to write this --
# rejects every real tile and caches nothing at all, which is a worse failure
# than the one we are fixing because it is silent and total. The URL extension
# says nothing about the payload; only the bytes do. Leaflet does not care
# either, because browsers sniff content type rather than trusting the name.
IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG  <- what ArcGIS actually sends
    b"GIF87a",
    b"GIF89a",
    b"RIFF",                # WebP (RIFF....WEBP)
)
# Courtesy rate limit. This is a free public tile server and we are asking it
# for thousands of files; hammering it gets the whole team's IP blocked, which
# is unrecoverable if it happens the week before the competition.
SLEEP_S = 1 / 200


def convert_to_slippy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """WGS84 -> slippy tile x, y. Standard Web Mercator."""
    lat_rad = math.radians(lat)
    x = math.radians(lon)
    y = math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad))
    x = (1 + x / math.pi) / 2
    y = (1 - y / math.pi) / 2
    n = 2 ** zoom
    # Clamp: at the poles y goes out of range, and one bad index poisons a whole
    # zoom level with 404s.
    return max(0, min(n - 1, int(x * n))), max(0, min(n - 1, int(y * n)))


def tile_range(bbox: tuple[float, float, float, float], zoom: int):
    """bbox = (south, west, north, east) -> (x0, x1, y0, y1) inclusive."""
    south, west, north, east = bbox
    x0, y0 = convert_to_slippy(north, west, zoom)   # y grows southward
    x1, y1 = convert_to_slippy(south, east, zoom)
    return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)


def bbox_from_center(lat: float, lon: float, radius_km: float):
    """Square box of half-width radius_km. Longitude degrees shrink with
    latitude, so scaling by cos(lat) is what keeps it square on the ground."""
    dlat = radius_km / 110.574
    dlon = radius_km / (111.320 * max(0.01, math.cos(math.radians(lat))))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def is_valid_image(data: bytes) -> bool:
    """The check the original did not do.

    A tile server under load answers with an HTML error page, a JSON rate-limit
    body or a truncated response and HTTP 200 more often than you would like.
    Written straight to a .png it looks like a cached tile forever after,
    because the resume check only asks whether the file exists.

    Checks the magic number, not the extension -- see IMAGE_MAGIC. The 512-byte
    floor rejects truncated responses that happen to start correctly; a real
    satellite tile at these zooms is 10-40 kB.
    """
    return len(data) >= 512 and data.startswith(IMAGE_MAGIC)


def tile_path(zoom: int, x: int, y: int) -> str:
    return os.path.join(MAP_DIR, str(zoom), str(x), f"{y}.png")


def count_tiles(bbox, zooms) -> dict[int, int]:
    out = {}
    for z in zooms:
        x0, x1, y0, y1 = tile_range(bbox, z)
        out[z] = (x1 - x0 + 1) * (y1 - y0 + 1)
    return out


def download_tiles(bbox, zooms, retries=3, verbose=False) -> tuple[int, int, int]:
    """Returns (downloaded, skipped, failed)."""
    import requests  # noqa: PLC0415 - see the note at the top of the file

    session = requests.Session()
    downloaded = skipped = failed = 0
    failures: list[str] = []

    for z in zooms:
        x0, x1, y0, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            os.makedirs(os.path.join(MAP_DIR, str(z), str(x)), exist_ok=True)
            for y in range(y0, y1 + 1):
                path = tile_path(z, x, y)
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    skipped += 1
                    print(f"skip {z}/{x}/{y}" if verbose else ".", end="", flush=True)
                    continue

                url = f"{MAP_URL}/{z}/{y}/{x}.png"      # ArcGIS is /z/row/col
                data = None
                for attempt in range(retries):
                    try:
                        r = session.get(url, allow_redirects=False,
                                        timeout=REQUEST_TIMEOUT)
                        if r.status_code == 200 and is_valid_image(r.content):
                            data = r.content
                            break
                        # Back off on rate limits rather than burning retries.
                        time.sleep(0.5 * (attempt + 1))
                    except requests.RequestException:
                        time.sleep(0.5 * (attempt + 1))

                if data is None:
                    failed += 1
                    failures.append(f"{z}/{x}/{y}")
                    print(f"FAIL {z}/{x}/{y}" if verbose else "x", end="", flush=True)
                    continue

                # Write to a temp name and rename, so an interrupted run cannot
                # leave a half-written file that the resume check then trusts.
                tmp = path + ".part"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
                downloaded += 1
                print(f"get  {z}/{x}/{y}" if verbose else "*", end="", flush=True)
                time.sleep(SLEEP_S)
        print(f"\nzoom {z}: done", flush=True)

    if failures:
        print(f"\n{len(failures)} tiles failed. First 20:")
        for f in failures[:20]:
            print("  ", f)
        print("Re-run the same command; completed tiles are skipped.")
    return downloaded, skipped, failed


def verify() -> int:
    """Re-check every cached tile. Deletes corrupt ones so a re-run refetches.

    Worth running once after the final pre-competition download: a cache that
    is 3% corrupt looks identical to a healthy one until mission day.
    """
    if not os.path.isdir(MAP_DIR):
        print(f"No tile cache at {MAP_DIR} -- the map WILL be blank offline.")
        return 1
    total = bad = 0
    for root, _dirs, files in os.walk(MAP_DIR):
        for name in files:
            if not name.endswith(".png"):
                continue
            total += 1
            p = os.path.join(root, name)
            with open(p, "rb") as fh:
                head = fh.read(16)
            if not is_valid_image(head + b"\x00" * 512):
                bad += 1
                print("corrupt, removing:", os.path.relpath(p, MAP_DIR))
                os.remove(p)

    # An empty directory is not a healthy cache. It is the blank-map failure
    # with a tick next to it -- and the directory gets created by the download
    # itself, so "it exists" proves nothing at all.
    if total == 0:
        print(f"Tile cache at {MAP_DIR} is EMPTY -- the map WILL be blank "
              f"offline. Run this script with --center/--bbox first.")
        return 1

    print(f"{total} tiles checked, {bad} corrupt and removed.")
    if bad:
        print("Re-run the download command to refetch them.")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-cache offline map tiles (rule 8.4).",
        epilog="Run this WEEKS AHEAD. There is no network at the venue.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--center", metavar="LAT,LON",
                   help="centre of a square region, e.g. 13.0,80.0")
    g.add_argument("--bbox", metavar="S,W,N,E",
                   help="explicit bounding box in degrees")
    g.add_argument("--verify", action="store_true",
                   help="re-check tiles already on disk and delete corrupt ones")
    ap.add_argument("--radius-km", type=float, default=10.0,
                    help="half-width for --center (default 10 km -- err large)")
    ap.add_argument("--zoom", default="10-18", metavar="MIN-MAX",
                    help="zoom range, inclusive (default 10-18)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report tile counts and size, download nothing")
    ap.add_argument("--yes", action="store_true",
                    help="do not prompt before a large download")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verify:
        return verify()
    if not args.center and not args.bbox:
        ap.error("one of --center, --bbox or --verify is required. "
                 "There is no sensible default: the old one was a field in "
                 "Maryland.")

    lo, _, hi = args.zoom.partition("-")
    zooms = list(range(int(lo), int(hi or lo) + 1))
    if not zooms or zooms[0] < 0 or zooms[-1] > 19:
        ap.error("--zoom must lie within 0-19")

    if args.bbox:
        vals = [float(v) for v in args.bbox.split(",")]
        if len(vals) != 4:
            ap.error("--bbox needs four values: S,W,N,E")
        bbox = (min(vals[0], vals[2]), min(vals[1], vals[3]),
                max(vals[0], vals[2]), max(vals[1], vals[3]))
    else:
        lat, lon = (float(v) for v in args.center.split(","))
        bbox = bbox_from_center(lat, lon, args.radius_km)

    counts = count_tiles(bbox, zooms)
    total = sum(counts.values())
    # ~25 kB/tile measured on ArcGIS World_Imagery at these zooms.
    mb = total * 25 / 1024

    # Wall-clock is dominated by the request round trip, not by our own sleep.
    # ~120 ms/tile is what this actually achieves against ArcGIS on a domestic
    # connection. Quoting the sleep alone said "2 min" for a 40-minute job,
    # which is the sort of estimate that gets a download started at 11 pm.
    mins = total * (0.12 + SLEEP_S) / 60

    print(f"cache dir : {MAP_DIR}")
    print(f"bbox      : S{bbox[0]:.5f} W{bbox[1]:.5f} N{bbox[2]:.5f} E{bbox[3]:.5f}")
    for z in zooms:
        print(f"  zoom {z:>2} : {counts[z]:>8,} tiles")
    print(f"  TOTAL   : {total:>8,} tiles  (~{mb:,.0f} MB, roughly {mins:.0f} min)")

    if args.dry_run:
        return 0
    if total > 20000 and not args.yes:
        print("\nThat is a lot of tiles. Re-run with --yes if you meant it, "
              "or drop the top zoom level -- zoom 18 is usually most of it.")
        return 2

    os.makedirs(MAP_DIR, exist_ok=True)
    got, skip, fail = download_tiles(bbox, zooms, retries=args.retries,
                                     verbose=args.verbose)
    print(f"\ndownloaded {got}, already had {skip}, failed {fail}")
    if fail:
        print("INCOMPLETE -- re-run the same command before you rely on this.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
