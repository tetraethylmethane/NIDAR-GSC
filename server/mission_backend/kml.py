"""KML mission-boundary parser — SYS-38.

The organisers provide the mission boundary as a KML file, handed over *during*
the 5-minute setup window. It must parse and render with no operator editing,
inside the 30 s allowance in the setup budget.

TWO TRAPS THIS MODULE EXISTS TO AVOID
-------------------------------------
1. **KML coordinates are `longitude,latitude[,altitude]` — longitude FIRST.**
   Every other geospatial API in this project takes (lat, lon). Getting this
   backwards puts the mission area in the wrong hemisphere and is the single
   most common KML bug. This module returns explicit (lat, lon) tuples.

2. **Real KML exports are not hand-written KML.** They carry XML namespaces,
   nest Placemarks inside Folders and Documents, and may wrap geometry in
   `<MultiGeometry>`. Google Earth also emits `<gx:...>` extensions. A parser
   tested only against a hand-made file will fail on the day.

Deliberately dependency-free — stdlib only, so it cannot fail on a machine with
no network to install anything.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


class KMLError(ValueError):
    """Raised when a KML file cannot yield a usable mission boundary."""


@dataclass
class Boundary:
    """A mission boundary polygon, in (lat, lon) degrees."""

    name: str
    points: list[tuple[float, float]] = field(default_factory=list)

    @property
    def closed(self) -> list[tuple[float, float]]:
        """Points with the first vertex repeated at the end."""
        if self.points and self.points[0] != self.points[-1]:
            return [*self.points, self.points[0]]
        return list(self.points)

    def bounds(self) -> tuple[float, float, float, float]:
        """(min_lat, min_lon, max_lat, max_lon) — used to pre-cache map tiles."""
        lats = [p[0] for p in self.points]
        lons = [p[1] for p in self.points]
        return min(lats), min(lons), max(lats), max(lons)

    def area_hectares(self) -> float:
        """Planar shoelace area, adequate at 10 ha scale.

        Latitude is scaled by cos(mean lat) so the result is not stretched in
        longitude. Good to well under 1 % over a few hundred metres, which is
        all this is used for -- sanity-checking that the organisers' polygon is
        the ~10 ha the brief promises.
        """
        import math

        if len(self.points) < 3:
            return 0.0
        mean_lat = sum(p[0] for p in self.points) / len(self.points)
        m_per_deg_lat = 111_132.0
        m_per_deg_lon = 111_320.0 * math.cos(math.radians(mean_lat))
        pts = [(p[1] * m_per_deg_lon, p[0] * m_per_deg_lat) for p in self.closed]
        s = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0 / 10_000.0


def _strip_ns(tag: str) -> str:
    """'{http://www.opengis.net/kml/2.2}Polygon' -> 'polygon'."""
    return tag.rpartition("}")[2].lower()


def _parse_coordinates(text: str) -> list[tuple[float, float]]:
    """Parse a KML <coordinates> block into (lat, lon) tuples.

    KML gives 'lon,lat[,alt]' tuples separated by any whitespace. Altitude is
    discarded: the mission boundary is a ground polygon, and any altitude in the
    file is the organisers' artefact, not a constraint on us.
    """
    points: list[tuple[float, float]] = []
    for tok in text.replace("\n", " ").replace("\t", " ").split():
        parts = tok.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if not (-90.0 <= lat <= 90.0):
            raise KMLError(
                f"latitude {lat} out of range — coordinates may be lat,lon "
                f"instead of the lon,lat KML requires"
            )
        if not (-180.0 <= lon <= 180.0):
            raise KMLError(f"longitude {lon} out of range")
        points.append((lat, lon))          # note the swap: KML is lon-first
    return points


def parse_boundary(source: str | bytes) -> Boundary:
    """Extract the mission boundary from KML text, bytes, or a file path.

    Returns the polygon with the largest area, which is the mission boundary in
    every export we have seen -- organisers commonly include smaller markers,
    launch points or annotation shapes in the same file.
    """
    if isinstance(source, bytes):
        text = source.decode("utf-8", errors="replace")
    elif "<" in source:
        text = source
    else:
        with open(source, encoding="utf-8") as fh:
            text = fh.read()

    # Google Earth emits gx: and atom: prefixes that may be undeclared in
    # fragments; strip prefixes we cannot resolve rather than fail on them.
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        cleaned = re.sub(r"<(/?)(?:gx|atom):", r"<\1", text)
        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError:
            raise KMLError(f"not well-formed XML: {exc}") from exc

    candidates: list[Boundary] = []
    for placemark in root.iter():
        if _strip_ns(placemark.tag) != "placemark":
            continue
        name = "boundary"
        for child in placemark:
            if _strip_ns(child.tag) == "name" and (child.text or "").strip():
                name = child.text.strip()
                break
        # Any coordinates under this placemark, including inside MultiGeometry,
        # Polygon/outerBoundaryIs/LinearRing, or a bare LineString.
        for node in placemark.iter():
            if _strip_ns(node.tag) != "coordinates" or not (node.text or "").strip():
                continue
            pts = _parse_coordinates(node.text)
            if len(pts) >= 3:
                candidates.append(Boundary(name=name, points=pts))

    if not candidates:
        # Some minimal exports omit Placemark entirely.
        for node in root.iter():
            if _strip_ns(node.tag) == "coordinates" and (node.text or "").strip():
                pts = _parse_coordinates(node.text)
                if len(pts) >= 3:
                    candidates.append(Boundary(name="boundary", points=pts))

    if not candidates:
        raise KMLError("no polygon with 3 or more coordinates found")

    return max(candidates, key=lambda b: b.area_hectares())


def check_against_brief(b: Boundary, max_ha: float = 10.0) -> list[str]:
    """Sanity-check the delivered boundary. Returns human-readable warnings.

    Displayed on the GCS rather than blocking: if the organisers hand us
    something unexpected during a 5-minute window, the operator needs to SEE
    that, not have the load silently rejected.
    """
    warnings: list[str] = []
    ha = b.area_hectares()
    if ha > max_ha * 1.05:
        warnings.append(f"area {ha:.2f} ha exceeds the {max_ha:.0f} ha brief")
    if ha < 0.5:
        warnings.append(f"area {ha:.2f} ha is implausibly small — check the file")
    if len(b.points) < 3:
        warnings.append("fewer than 3 vertices")
    min_lat, min_lon, max_lat, max_lon = b.bounds()
    if max_lat - min_lat > 0.1 or max_lon - min_lon > 0.1:
        warnings.append("boundary spans >0.1 deg — suspiciously large")
    return warnings
