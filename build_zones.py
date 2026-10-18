#!/usr/bin/env python3
"""
Zonas tarifárias desenhadas a partir da zona de cada paragem (zone_id do GTFS).

Andante (Porto): o OTP da Porto Digital dá a zona de cada paragem do metro e da STCP. Cada paragem
fica com a sua célula de Voronoi, cortada a ZONE_REACH m (para não pintar serras sem paragens), e as
células da mesma zona juntam-se num polígono. Sai boards/zones/porto.geojson: polígonos com
`zone` e pontos de etiqueta (`label`). Precisa de shapely e scipy.
"""
import json, math, os, urllib.request
from collections import defaultdict

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import MultiPoint, Point, Polygon, mapping
from shapely.ops import unary_union

OTP = "https://otp.portodigital.pt/otp/gtfs/v1"
ZONE_REACH = 1200  # m à volta de cada paragem
OUT = os.path.join("boards", "zones")


def stops():
    q = json.dumps({"query": "{ stops { gtfsId zoneId lat lon } }"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(OTP, q, {"Content-Type": "application/json", "User-Agent": "brutemaps-data"}), timeout=60)
    # 1 = Metro, 2 = STCP (a CP, 3, não tem zonas no GTFS)
    return [s for s in json.load(r)["data"]["stops"] if s["zoneId"] and s["gtfsId"].split(":")[0] in ("1", "2")]


def main():
    ss = stops()
    lat0 = sum(s["lat"] for s in ss) / len(ss)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    def fwd(lat, lon): return (lon * kx, lat * ky)
    def back(x, y): return (round(x / kx, 5), round(y / ky, 5))  # (lon, lat)

    # paragens repetidas (plataformas) no mesmo sítio: uma só
    seen = {}
    for s in ss:
        seen.setdefault((round(s["lat"], 5), round(s["lon"], 5)), s)
    ss = list(seen.values())
    pts = np.array([fwd(s["lat"], s["lon"]) for s in ss])
    # pontos longe a toda a volta: todas as células ficam finitas
    cx, cy = pts.mean(axis=0)
    far = [(cx + 1e6 * math.cos(a), cy + 1e6 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    vor = Voronoi(np.vstack([pts, far]))

    cells = defaultdict(list)
    for i, s in enumerate(ss):
        region = vor.regions[vor.point_region[i]]
        if -1 in region or not region:
            continue
        cell = Polygon([vor.vertices[j] for j in region]).intersection(Point(pts[i]).buffer(ZONE_REACH, 16))
        if not cell.is_empty:
            cells[s["zoneId"]].append(cell)

    feats = []
    for zone, cs in sorted(cells.items()):
        shape = unary_union(cs).buffer(30).buffer(-30).simplify(25)
        # pedaços soltos pequenos (uma paragem com zona diferente no meio de outra): fora
        parts = [g for g in getattr(shape, "geoms", [shape]) if g.area > 150_000]
        if not parts:
            continue
        shape = unary_union(parts)
        geo = mapping(shape)
        def conv(c):
            return [[list(back(x, y)) for x, y in ring] for ring in c]
        if geo["type"] == "Polygon":
            coords = conv(geo["coordinates"])
        else:
            coords = [conv(p) for p in geo["coordinates"]]
        feats.append({"type": "Feature", "properties": {"zone": zone}, "geometry": {"type": geo["type"], "coordinates": coords}})
        # etiqueta no maior pedaço
        big = max(getattr(shape, "geoms", [shape]), key=lambda g: g.area)
        lp = big.representative_point()
        feats.append({"type": "Feature", "properties": {"zone": zone, "label": True}, "geometry": {"type": "Point", "coordinates": list(back(lp.x, lp.y))}})

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "porto.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "network": "Andante", "features": feats}, f, separators=(",", ":"))
    print(f"Andante: {len(cells)} zonas, {len(ss)} paragens")


if __name__ == "__main__":
    main()
