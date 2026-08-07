"""Tests for the KML mission-boundary parser (SYS-38).

These are written against the failure modes that actually happen on the day, not
against a hand-made happy path.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission_backend.kml import Boundary, KMLError, check_against_brief, parse_boundary  # noqa: E402


# A ~10 ha rectangle near Chennai. 400 m x 250 m.
# At this latitude 1 deg lat ~ 111132 m, 1 deg lon ~ 110950 m.
LAT0, LON0 = 13.0000, 80.0000
DLAT = 250.0 / 111_132.0
DLON = 400.0 / (111_320.0 * math.cos(math.radians(LAT0)))

PLAIN = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Mission Area</name><Polygon><outerBoundaryIs><LinearRing>
    <coordinates>
      {LON0},{LAT0},0 {LON0+DLON},{LAT0},0 {LON0+DLON},{LAT0+DLAT},0
      {LON0},{LAT0+DLAT},0 {LON0},{LAT0},0
    </coordinates>
  </LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""


def test_parses_namespaced_kml():
    b = parse_boundary(PLAIN)
    assert b.name == "Mission Area"
    assert len(b.points) >= 4


def test_longitude_comes_first_in_kml():
    """The trap this module exists for.

    KML is lon,lat. If the parser returned them in file order the first point
    would be (80.0, 13.0) -- a latitude of 80 degrees, in the Arctic Ocean.
    """
    b = parse_boundary(PLAIN)
    lat, lon = b.points[0]
    assert lat == pytest.approx(LAT0), "latitude and longitude are swapped"
    assert lon == pytest.approx(LON0)
    assert 8 < lat < 37, "not in India — coordinates are probably transposed"


def test_area_is_about_ten_hectares():
    b = parse_boundary(PLAIN)
    assert b.area_hectares() == pytest.approx(10.0, rel=0.02)


def test_rejects_transposed_coordinates():
    """A lat,lon file (rather than lon,lat) must fail loudly, not silently."""
    bad = PLAIN.replace(f"{LON0},{LAT0},0", "13.0,200.0,0")
    with pytest.raises(KMLError):
        parse_boundary(bad)


def test_handles_multigeometry_and_folders():
    kml = f"""<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder>
      <Placemark><name>Area</name><MultiGeometry><Polygon><outerBoundaryIs>
      <LinearRing><coordinates>
        {LON0},{LAT0} {LON0+DLON},{LAT0} {LON0+DLON},{LAT0+DLAT} {LON0},{LAT0+DLAT}
      </coordinates></LinearRing></outerBoundaryIs></Polygon></MultiGeometry></Placemark>
    </Folder></Document></kml>"""
    b = parse_boundary(kml)
    assert len(b.points) == 4
    assert b.area_hectares() == pytest.approx(10.0, rel=0.02)


def test_picks_the_largest_polygon():
    """Exports often include launch markers or annotations alongside the area."""
    small = f"""{LON0},{LAT0} {LON0+DLON/10},{LAT0} {LON0+DLON/10},{LAT0+DLAT/10} {LON0},{LAT0+DLAT/10}"""
    kml = f"""<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>Launch Pad</name><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>{small}</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>
      <Placemark><name>Mission Area</name><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>{LON0},{LAT0} {LON0+DLON},{LAT0} {LON0+DLON},{LAT0+DLAT} {LON0},{LAT0+DLAT}</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>
    </Document></kml>"""
    assert parse_boundary(kml).name == "Mission Area"


def test_tolerates_gx_extension_prefixes():
    """Google Earth emits gx: prefixes that may be undeclared in fragments."""
    kml = PLAIN.replace("<Document>", "<Document><gx:CascadingStyle/>")
    b = parse_boundary(kml)
    assert b.area_hectares() == pytest.approx(10.0, rel=0.02)


def test_no_polygon_raises():
    with pytest.raises(KMLError):
        parse_boundary('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')


def test_malformed_xml_raises_kmlerror_not_parseerror():
    with pytest.raises(KMLError):
        parse_boundary("<kml><Document>")


def test_bounds_usable_for_tile_precache():
    b = parse_boundary(PLAIN)
    min_lat, min_lon, max_lat, max_lon = b.bounds()
    assert min_lat < max_lat and min_lon < max_lon
    assert min_lat == pytest.approx(LAT0)


def test_brief_check_flags_oversized_area():
    big = Boundary("x", [(13.0, 80.0), (13.0, 80.02), (13.02, 80.02), (13.02, 80.0)])
    assert any("exceeds" in w for w in check_against_brief(big))


def test_brief_check_passes_a_ten_hectare_area():
    assert check_against_brief(parse_boundary(PLAIN)) == []


def test_closed_ring_is_idempotent():
    b = parse_boundary(PLAIN)
    assert b.closed[0] == b.closed[-1]
    assert Boundary("x", b.closed).closed[0] == b.closed[-1]
