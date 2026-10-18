#!/usr/bin/env python3
"""
Painéis de paragens a partir de GTFS que ainda não estão no Transitous.

Para cada rede gera, em boards/<rede>/:
  meta.json   linhas, destinos e os serviços ativos em cada dia dos próximos DAYS dias
  t/<x>_<y>.json  paragens de uma quadrícula de TILE graus, cada uma com as partidas
                  [linha, destino, segundos desde a meia-noite (pode passar das 24h),
                  conjunto de serviços (meta.sets: a partida existe se algum estiver ativo no dia)]
  s/<linha>_<sentido>.txt  traçado mais comum dessa linha nesse sentido (polyline, precisão 5)
e boards/index.json com o nome, a licença e o retângulo de cada rede.

A app lê isto quando o Transitous não tem a paragem. Corre todas as semanas (GitHub Actions).
"""
import csv, io, json, math, os, shutil, sys, urllib.request, zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta

DAYS = 21
TILE = 0.02
OUT = "boards"
UA = {"User-Agent": "curl/8 (brutemaps-data)"}  # o servidor da Busway recusa User-Agents de browser

MINHO = "https://minhoaccesspoint.eu/dataset"
NETWORKS = [
    # o CIM do Ave (gtfs_ave.zip) acabou a 31 dez 2025 e não há versão nova: fica de fora até haver
    dict(id="cim-cavado-1", name="CIM do Cávado", licence="CC-BY 4.0 (Minho Access Point)",
         url=f"{MINHO}/332cc43a-5567-4521-88aa-6a0fc8d11eaa/resource/b42515d8-f6c6-44dd-bba4-1756d675340a/download/gtfs_cav_9.4.2_20251120_l1.zip"),
    dict(id="cim-cavado-2", name="CIM do Cávado", licence="CC-BY 4.0 (Minho Access Point)",
         url=f"{MINHO}/332cc43a-5567-4521-88aa-6a0fc8d11eaa/resource/655b4bec-3a0b-45ee-9805-89c0d9cacaab/download/gtfs_cav_v9.4.1_20251120_l2.zip"),
    dict(id="guimabus", name="Guimabus", licence="CC-BY 4.0 (Minho Access Point)",
         url=f"{MINHO}/ee6d46e4-9f19-4f4a-ab93-1a3cd69df349/resource/08f1ee6c-2d3f-4fb3-a861-5d6fb347a6d4/download/gtfs_gui.zip"),
    dict(id="barcelos", name="Barcelos", licence="CC-BY 4.0 (Minho Access Point)",
         url=f"{MINHO}/1842a15c-1aec-4f65-8e29-e57c8b4cbd74/resource/6221b66c-f160-45be-810d-0fb16aa7ab6f/download/11_gtfs_bcl_v4.4.1_20251120-tuba.zip"),
    dict(id="famalicao", name="V. N. de Famalicão", licence="CC-BY 4.0 (Minho Access Point)",
         url=f"{MINHO}/fe6015e4-86c7-437a-8d31-10759fe21a1d/resource/f4c4f4c2-0397-41dc-98d3-6afd52bae32e/download/opengtfs_famalicao.zip"),
    dict(id="sit-coimbra", name="SIT Região de Coimbra", licence="dados abertos (Busway)",
         url="https://gtfs.itbusway.eu/GTFS_SIT_Metropolitano.zip"),
    dict(id="cira", name="Região de Aveiro (Busway)", licence="dados abertos (Busway)",
         url="https://gtfs.itbusway.eu/GTFS_CIRA.zip"),
    dict(id="tamega-sousa", name="Tâmega e Sousa", licence="dados abertos (CIM Tâmega e Sousa)",
         url="https://transportes.cimtamegaesousa.pt/Servico/services/consultas.svc/Feed/OpenGTFS"),
    dict(id="smtuc", name="SMTUC", licence="dados.gov.pt",
         dataset="https://dados.gov.pt/api/1/datasets/gtfs-estaticos-servicos-municipalizados-de-transportes-urbanos-de-coimbra/"),
]


def fetch(net):
    url = net.get("url")
    if not url:  # dados.gov.pt: o ficheiro muda de nome a cada versão; o mais recente
        d = json.load(urllib.request.urlopen(urllib.request.Request(net["dataset"], headers=UA), timeout=60))
        res = [r for r in d["resources"] if r["url"].endswith(".zip")]
        url = max(res, key=lambda r: r.get("last_modified") or r.get("created_at") or "")["url"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))


def rows(z, name):
    if name not in z.namelist():
        return
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def secs(t):
    h, m, s = (t.strip() or "0:0:0").split(":")
    return int(h) * 3600 + int(m) * 60 + int(float(s))


def encode(points):
    """Polyline do Google, precisão 5."""
    out, plat, plon = [], 0, 0
    for lat, lon in points:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def simplify(pts, tol=0.00004):
    """Douglas-Peucker (~4 m), iterativo."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (y1, x1), (y2, x2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        best, idx = 0, -1
        for i in range(a + 1, b):
            y, x = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def active_days(z, today):
    days = [today + timedelta(i) for i in range(-1, DAYS)]  # ontem: viagens que passam da meia-noite
    on = defaultdict(set)
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for c in rows(z, "calendar.txt"):
        s, e = c["start_date"].strip(), c["end_date"].strip()
        for d in days:
            k = d.strftime("%Y%m%d")
            if s <= k <= e and c[wd[d.weekday()]].strip() == "1":
                on[k].add(c["service_id"])
    for c in rows(z, "calendar_dates.txt"):
        k = c["date"].strip()
        if k in {d.strftime("%Y%m%d") for d in days}:
            (on[k].add if c["exception_type"].strip() == "1" else on[k].discard)(c["service_id"])
    return {d.strftime("%Y%m%d"): on[d.strftime("%Y%m%d")] for d in days}


def build(net, today):
    z = fetch(net)
    days = active_days(z, today)
    live = set().union(*days.values())
    if not live:
        print(f"  {net['id']}: sem serviço nos próximos {DAYS} dias — ignorada", file=sys.stderr)
        return None

    routes = {r["route_id"]: r for r in rows(z, "routes.txt")}
    trips = {t["trip_id"]: t for t in rows(z, "trips.txt") if t["service_id"] in live and t["route_id"] in routes}

    lines, line_ix = [], {}
    heads, head_ix = [], {}
    svcs, svc_ix = [], {}

    def ix(table, index, key, value=None):
        if key not in index:
            index[key] = len(table); table.append(value if value is not None else key)
        return index[key]

    def line_of(rid):
        r = routes[rid]
        name = (r.get("route_short_name") or r.get("route_long_name") or rid).strip()
        color = (r.get("route_color") or "").strip().upper()
        return ix(lines, line_ix, rid, [name, color if len(color) == 6 else "", (r.get("route_long_name") or "").strip()])

    # paragens de cada viagem, pela ordem; a última dá o destino quando falta trip_headsign
    by_trip = defaultdict(list)
    for st in rows(z, "stop_times.txt"):
        if st["trip_id"] in trips:
            t = st["departure_time"] or st["arrival_time"]
            if t:
                by_trip[st["trip_id"]].append((int(float(st["stop_sequence"])), st["stop_id"], secs(t), st.get("pickup_type", "").strip()))
    stops = {s["stop_id"]: s for s in rows(z, "stops.txt")}

    deps = defaultdict(list)
    shape_use = Counter()
    for tid, sts in by_trip.items():
        sts.sort()
        t = trips[tid]
        last = stops.get(sts[-1][1], {}).get("stop_name", "")
        head = (t.get("trip_headsign") or "").strip().rstrip("*") or last
        li, hi, si = line_of(t["route_id"]), ix(heads, head_ix, head), ix(svcs, svc_ix, t["service_id"])
        for _, sid, s, pick in sts[:-1]:  # na última paragem não se apanha
            if pick != "1":
                deps[sid].append([li, hi, s, si])
        if t.get("shape_id"):
            shape_use[(li, (t.get("direction_id") or "0").split(".")[0], t["shape_id"])] += 1

    # traçados: o mais usado de cada linha/sentido
    best = {}
    for (li, d, sh), n in shape_use.most_common():
        best.setdefault((li, d), sh)
    want = set(best.values())
    pts = defaultdict(list)
    for p in rows(z, "shapes.txt"):
        if p["shape_id"] in want:
            pts[p["shape_id"]].append((int(float(p["shape_pt_sequence"])), float(p["shape_pt_lat"]), float(p["shape_pt_lon"])))

    out = os.path.join(OUT, net["id"])
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "t")); os.makedirs(os.path.join(out, "s"))
    for (li, d), sh in best.items():
        p = [(a, b) for _, a, b in sorted(pts.get(sh, []))]
        if len(p) >= 2:
            with open(os.path.join(out, "s", f"{li}_{d}.txt"), "w") as f:
                f.write(encode(simplify(p)))

    sets, set_ix = [], {}
    tiles = defaultdict(list)
    lat0 = lon0 = 1e9; lat1 = lon1 = -1e9
    for sid, ds in deps.items():
        s = stops.get(sid)
        if not s or not s.get("stop_lat"):
            continue
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        # a mesma partida em vários serviços (dias úteis/aulas/férias…) fica uma só, com o conjunto
        merged = defaultdict(set)
        for li, hi, t, si in ds:
            merged[(li, hi, t)].add(si)
        ds = sorted(([li, hi, t, ix(sets, set_ix, tuple(sorted(v)), sorted(v))] for (li, hi, t), v in merged.items()), key=lambda d: d[2])
        lines_here = sorted({d[0] for d in ds})
        tiles[(math.floor(lat / TILE), math.floor(lon / TILE))].append(
            dict(n=s["stop_name"].strip(), p=[round(lat, 6), round(lon, 6)], l=lines_here, d=ds))
        lat0, lat1, lon0, lon1 = min(lat0, lat), max(lat1, lat), min(lon0, lon), max(lon1, lon)
    for (x, y), ss in tiles.items():
        with open(os.path.join(out, "t", f"{x}_{y}.json"), "w") as f:
            json.dump(ss, f, ensure_ascii=False, separators=(",", ":"))

    meta = dict(id=net["id"], name=net["name"], agencies=sorted({(a.get("agency_name") or "").strip() for a in rows(z, "agency.txt")} - {""}),
                tile=TILE, lines=lines, heads=heads, sets=sets,
                days={k: sorted(svc_ix[s] for s in v if s in svc_ix) for k, v in days.items()})
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  {net['id']}: {len(lines)} linhas, {sum(len(v) for v in tiles.values())} paragens, {len(tiles)} quadrículas, {len(best)} traçados", file=sys.stderr)
    return dict(id=net["id"], name=net["name"], licence=net["licence"], bbox=[round(lat0, 4), round(lon0, 4), round(lat1, 4), round(lon1, 4)])


def main():
    today = date.today()
    only = set(sys.argv[1:])
    index_path = os.path.join(OUT, "index.json")
    old = {n["id"]: n for n in json.load(open(index_path))["networks"]} if os.path.exists(index_path) else {}
    out = {}
    for net in NETWORKS:
        if only and net["id"] not in only:
            if net["id"] in old:
                out[net["id"]] = old[net["id"]]
            continue
        try:
            r = build(net, today)
            if r:
                out[net["id"]] = r
        except Exception as e:  # uma rede em baixo não estraga as outras: fica a versão anterior
            print(f"  {net['id']}: falhou ({e}) — fica a versão anterior", file=sys.stderr)
            if net["id"] in old:
                out[net["id"]] = old[net["id"]]
    os.makedirs(OUT, exist_ok=True)
    with open(index_path, "w") as f:
        json.dump(dict(generated=today.isoformat(), networks=list(out.values())), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
