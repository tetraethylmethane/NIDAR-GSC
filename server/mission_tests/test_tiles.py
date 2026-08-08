"""Offline map tiles — rule 8.4.

The client is hard-wired to /map/{z}/{x}/{y}.png because rule 8.4 forbids
internet connectivity during the mission. If those files are absent the
operator gets a blank map: no boundary, no survivors, no aircraft. These tests
cover the tile cache tooling, which is the only thing preventing that.

The one that matters is test_a_non_png_response_is_never_written. The inherited
getter wrote `r.content` to a .png without looking at it, so a 404 page or a
truncated body landed on disk as a plausible tile -- and since the resume check
was `os.path.isfile`, it was skipped forever after. The cache would look
complete, report no errors, and render grey squares on mission day.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)

from utils import slippy_map_getter as smg  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 1024      # what ArcGIS actually returns


def test_a_non_image_response_is_never_written():
    """The defect this file exists for."""
    assert smg.is_valid_image(PNG)
    assert not smg.is_valid_image(b"<html>404 Not Found</html>")
    assert not smg.is_valid_image(b'{"error":"rate limited"}')
    assert not smg.is_valid_image(b"")
    assert not smg.is_valid_image(b"\x89PNG\r\n\x1a\n")   # header only, truncated


def test_a_jpeg_body_is_accepted_from_a_dot_png_url():
    """ArcGIS World_Imagery answers a `.png` request with a JPEG.

    Checking for a PNG signature specifically is the obvious way to write the
    validator and it rejects every real tile, caching nothing at all -- a
    worse failure than the corrupt-tile bug, because it is total and silent.
    The extension says nothing about the payload; only the bytes do.
    """
    assert smg.is_valid_image(JPEG)


def test_a_truncated_image_is_rejected():
    """A body that starts correctly and stops early still renders as a broken
    tile. Real tiles at these zooms are 10-40 kB."""
    assert not smg.is_valid_image(b"\xff\xd8\xff\xe0" + b"\x00" * 8)


def test_verify_deletes_corrupt_tiles_so_a_rerun_refetches(tmp_path, monkeypatch):
    """A cache that is 3% corrupt is indistinguishable from a healthy one until
    mission day, unless something looks."""
    monkeypatch.setattr(smg, "MAP_DIR", str(tmp_path))
    d = tmp_path / "16" / "100"
    d.mkdir(parents=True)
    (d / "200.png").write_bytes(PNG)
    (d / "201.png").write_bytes(b"<html>rate limited</html>")

    assert smg.verify() == 1                       # non-zero: cache was bad
    assert (d / "200.png").exists()
    assert not (d / "201.png").exists()            # removed, so it refetches
    assert smg.verify() == 0                       # clean the second time


def test_verify_reports_a_missing_cache_rather_than_passing(tmp_path, monkeypatch):
    """No cache at all must not look like success. This is the failure mode
    that produced a blank map."""
    monkeypatch.setattr(smg, "MAP_DIR", str(tmp_path / "nope"))
    assert smg.verify() == 1


def test_verify_fails_on_an_empty_cache_directory(tmp_path, monkeypatch):
    """The directory gets created by the download itself, so "it exists" proves
    nothing. An empty cache is the blank-map failure with a tick next to it."""
    monkeypatch.setattr(smg, "MAP_DIR", str(tmp_path))
    (tmp_path / "16" / "100").mkdir(parents=True)
    assert smg.verify() == 1


def _osm_reference(lat, lon, zoom):
    """The OSM slippy-tile formula, written out independently.

    Deliberately not sharing code with convert_to_slippy: a test that calls the
    implementation it is checking proves only that the function is
    deterministic.
    """
    import math

    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return int(x), int(y)


@pytest.mark.parametrize("lat,lon,zoom", [
    (0.0, 0.0, 1),
    (0.0, -180.0, 1),
    (13.0, 80.0, 16),        # the NIDAR test coordinates
    (28.42, 77.53, 18),
    (-33.87, 151.21, 14),    # southern hemisphere, eastern longitude
])
def test_slippy_conversion_matches_the_osm_reference(lat, lon, zoom):
    assert smg.convert_to_slippy(lat, lon, zoom) == _osm_reference(lat, lon, zoom)


def test_tile_x_and_y_are_not_transposed():
    """A transposed axis yields tiles that download fine and render as the
    wrong place on Earth, which is worse than failing."""
    bbox = smg.bbox_from_center(13.0, 80.0, 5.0)
    x0, x1, y0, y1 = smg.tile_range(bbox, 16)
    # x increases eastward, y increases SOUTHWARD.
    assert x0 == smg.convert_to_slippy(13.0, bbox[1], 16)[0]
    assert x1 == smg.convert_to_slippy(13.0, bbox[3], 16)[0]
    assert y0 == smg.convert_to_slippy(bbox[2], 80.0, 16)[1]   # north -> low y
    assert y1 == smg.convert_to_slippy(bbox[0], 80.0, 16)[1]   # south -> high y
    assert y0 < y1


def test_box_is_square_on_the_ground_not_in_degrees():
    """Longitude degrees shrink with latitude. Without the cos(lat) term the
    cached box is too narrow east-west, which is how you arrive at the venue
    with tiles that stop 2 km short of the search area."""
    south, west, north, east = smg.bbox_from_center(13.0, 80.0, 10.0)
    km_ns = (north - south) * 110.574
    km_ew = (east - west) * 111.320 * 0.974          # cos(13 deg)
    assert km_ns == pytest.approx(20.0, rel=0.01)
    assert km_ew == pytest.approx(20.0, rel=0.01)


def test_counts_grow_fourfold_per_zoom_level():
    """The estimate exists so nobody starts an 18,000-tile download by accident.
    Each zoom level quadruples; zoom 18 alone is most of any range."""
    bbox = smg.bbox_from_center(13.0, 80.0, 10.0)
    counts = smg.count_tiles(bbox, range(12, 19))
    assert counts[18] > 0.7 * sum(counts.values())
    for z in range(13, 19):
        assert counts[z] > 2.5 * counts[z - 1]


def test_download_never_writes_a_bad_body(tmp_path, monkeypatch):
    """End to end against a stubbed tile server that serves an error page.

    Nothing must land on disk, and the run must report failure -- previously it
    reported success and cached the error page.
    """
    monkeypatch.setattr(smg, "MAP_DIR", str(tmp_path))
    monkeypatch.setattr(smg, "SLEEP_S", 0)

    class _Resp:
        status_code = 200
        content = b"<html>Service Unavailable</html>"

    class _Session:
        def get(self, *a, **k):
            return _Resp()

    fake = type(sys)("requests")
    fake.Session = _Session
    fake.RequestException = Exception
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    got, skipped, failed = smg.download_tiles(
        smg.bbox_from_center(13.0, 80.0, 0.3), [14], retries=1)

    assert got == 0 and failed > 0
    written = [f for _r, _d, fs in os.walk(tmp_path) for f in fs]
    assert written == [], f"an error page was cached as a tile: {written}"
