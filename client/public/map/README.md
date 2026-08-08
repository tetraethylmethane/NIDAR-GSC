# Offline map tiles

**If the map is blank, this directory is empty.** That is the whole story.

Rule 8.4 prohibits internet connectivity during mission execution, so the client
is hard-wired to `/map/{z}/{x}/{y}.png` — served from right here — and never
falls back to an online tile server. Without these files the operator sees a
grey rectangle with the boundary, the aircraft and the survivors drawn on
nothing.

Tiles are gitignored (`/client/public/map/*/*/*`). They are hundreds of
megabytes of binary that would be stale by the next competition anyway, so
**every machine that will run the ground station has to fetch them itself.**

## Fetching them

```bash
cd server
python utils/slippy_map_getter.py --center 13.0,80.0 --radius-km 10 \
    --zoom 10-18 --dry-run      # always look at the cost first
python utils/slippy_map_getter.py --center 13.0,80.0 --radius-km 10 \
    --zoom 10-16 --yes
python utils/slippy_map_getter.py --verify
```

`--verify` re-reads every cached tile and deletes any that are not actually
images, so a re-run refetches them. Run it after the final download and again
the morning of the competition. A cache that is 3 % corrupt looks exactly like a
healthy one until the moment it matters.

## Two things that will bite you

**Run it weeks ahead, over a generous region.** The organisers hand over the
mission KML during setup, and there is no network at the venue to fetch tiles
with once you know where you are. A 10 km radius around the venue is cheap
insurance; guessing a tight box and being 2 km off is the same as having no
tiles at all.

**Zoom 18 is most of the download.** Each level quadruples the tile count. Over
a 10 km radius, zoom 10–16 is about 1,700 tiles (~41 MB); adding 17 and 18 takes
it to about 24,700 tiles (~600 MB) and roughly 50 minutes. Zoom 16 is ~2.4 m per
pixel, which is enough to fly on. Take 17 and 18 only if you have the evening
free and the disk space.

## Layout

`{zoom}/{x}/{y}.png`, standard slippy-map / Web Mercator, the same scheme
OpenStreetMap and Leaflet use.

The files are named `.png` but contain **JPEG** data, because that is what the
ArcGIS World Imagery service returns for a `.png` request. This is fine —
browsers sniff the content type rather than trusting the extension — but it is
worth knowing before you write a checker that looks for a PNG signature and
concludes the entire cache is corrupt.
