"""GTFS do Metrobus do Metro Mondego (Coimbra – Miranda do Corvo – Lousã – Serpins).

Não há GTFS oficial. Feito a partir de:
  - horários oficiais em PDF (metromondego.pt › Viajar › Horários), texto extraído com a posição
    de cada célula para fonte/horarios-<data>.json (o site bloqueia pedidos que não sejam de um
    browser, por isso a extração faz-se à mão quando os horários mudam);
  - paragens e traçado das relações do OpenStreetMap (network=Metro Mondego), pela API do OSM.

Linhas suburbanas (S1 Coimbra-B ↔ Serpins, S2 República ↔ Serpins): uma viagem por coluna do PDF.
Linhas urbanas (U1 Coimbra-B ↔ Vale das Flores, U2 República ↔ Vale das Flores, U3 Coimbra-B ↔
República): o PDF só dá 1.ª/última viagem e intervalos por período → frequencies.txt, com os
tempos entre paragens tirados das viagens suburbanas (U3: pela distância, à mesma velocidade).

Uso: python build.py  →  out/ (ficheiros) e metro-mondego.zip
"""
import csv, io, json, math, os, re, sys, time, urllib.request, zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "fonte", "horarios-2026-09-10.json")
OUT = os.path.join(HERE, "out")
START, END = date(2026, 9, 10), date(2027, 3, 31)
# feriados nacionais (dias úteis viram domingo) dentro da validade
HOLIDAYS = [date(2026, 10, 5), date(2026, 11, 1), date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 25), date(2027, 1, 1)]
RELATIONS = {  # ref, sentido → relação OSM
    ("U1", 0): 21409151, ("U1", 1): 19653947, ("U2", 0): 21409407, ("U2", 1): 21409406,
    ("U3", 0): 21417392, ("U3", 1): 21417393, ("S1", 0): 21240141, ("S1", 1): 21240142,
    ("S2", 0): 21418636, ("S2", 1): 21418635,
}
ROUTE_NAMES = {
    "U1": "Coimbra-B – Vale das Flores", "U2": "República – Vale das Flores", "U3": "Coimbra-B – República",
    "S1": "Coimbra-B – Serpins", "S2": "República – Serpins",
}
UA = "brutemaps-data GTFS (github.com/bquelhas/brutemaps-data)"
TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def osm(rel_id):
    cache = os.path.join(HERE, "fonte", f"osm-{rel_id}.json")
    if not os.path.exists(cache) or "--fresh" in sys.argv:
        req = urllib.request.Request(f"https://api.openstreetmap.org/api/0.6/relation/{rel_id}/full.json", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            open(cache, "wb").write(r.read())
        time.sleep(1)
    els = json.load(open(cache))["elements"]
    nodes = {e["id"]: e for e in els if e["type"] == "node"}
    ways = {e["id"]: e for e in els if e["type"] == "way"}
    rel = next(e for e in els if e["type"] == "relation" and e["id"] == rel_id)
    return rel, nodes, ways


def dist(a, b):
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * k)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("-", " ").replace("–", " ")).strip().lower().replace("coimbra b", "coimbra b")


def shape_and_stops(rel_id):
    """Traçado (vias pela ordem, viradas para continuar) e paragens (nós stop/platform, sem repetir nomes seguidos)."""
    rel, nodes, ways = osm(rel_id)
    line = []
    for m in rel["members"]:
        if m["type"] != "way" or m["role"] not in ("", "forward", "backward"):
            continue
        pts = [(nodes[n]["lat"], nodes[n]["lon"]) for n in ways[m["ref"]]["nodes"]]
        if line:
            # vira a via para começar onde a anterior acabou
            if dist(line[-1], pts[-1]) < dist(line[-1], pts[0]):
                pts.reverse()
            if len(line) >= 2 and dist(line[0], pts[0]) < 1 and len(line) == len(line):
                pass
            if dist(line[-1], pts[0]) < 1:
                pts = pts[1:]
        elif len([w for w in rel["members"] if w["type"] == "way"]) > 1:
            # a primeira via: virada para ligar à segunda
            nxt = next(w for w in rel["members"][rel["members"].index(m) + 1:] if w["type"] == "way")
            n2 = [(nodes[n]["lat"], nodes[n]["lon"]) for n in ways[nxt["ref"]]["nodes"]]
            if min(dist(pts[0], n2[0]), dist(pts[0], n2[-1])) < min(dist(pts[-1], n2[0]), dist(pts[-1], n2[-1])):
                pts.reverse()
        line += pts
    stops = []
    for m in rel["members"]:
        if not m["role"].startswith(("stop", "platform")):
            continue
        if m["type"] == "node":
            n = nodes[m["ref"]]
            name, pt = n.get("tags", {}).get("name", ""), (n["lat"], n["lon"])
        elif m["type"] == "way" and m["ref"] in ways:
            # cais desenhado como área: o centro dos nós
            wy = ways[m["ref"]]
            ps = [(nodes[i]["lat"], nodes[i]["lon"]) for i in wy["nodes"] if i in nodes]
            if not ps:
                continue
            name, pt = wy.get("tags", {}).get("name", ""), (sum(a for a, _ in ps) / len(ps), sum(b for _, b in ps) / len(ps))
        else:
            continue
        if stops and norm(stops[-1][1]) == norm(name):
            continue  # paragem e plataforma da mesma estação
        stops.append((m["ref"], name, pt))
    return rel, line, stops


def along(line, p):
    """Distância ao longo do traçado do ponto mais perto de p."""
    best, acc, best_d = 0.0, 0.0, 1e18
    for a, b in zip(line, line[1:]):
        seg = dist(a, b)
        # projeção aproximada no plano
        k = math.cos(math.radians(a[0]))
        ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
        q = (ay + dy * t, (ax + dx * t) / k)
        d = dist(q, p)
        if d < best_d:
            best_d, best = d, acc + seg * t
        acc += seg
    return best


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}:00"


def parse_pages():
    """Viagens suburbanas: por página, as colunas (lista de (paragem, minutos)), pela ordem das linhas."""
    d = json.load(open(SRC))
    pages = []
    for p in d["s"]:
        rows = []
        for y, cells in p:
            times = [c[1] for c in cells if TIME.match(c[1]) or c[1] == "-"]
            label = " ".join(c[1] for c in cells if not (TIME.match(c[1]) or c[1] == "-")).strip()
            if times and label:
                rows.append((label, times))
        n = max(len(t) for _, t in rows)
        cols = []
        for i in range(n):
            col, last = [], -1
            for label, times in rows:
                t = times[i] if i < len(times) else "-"
                m = TIME.match(t)
                if not m:
                    continue
                mins = int(m.group(1)) * 60 + int(m.group(2))
                while mins < last - 600:
                    mins += 1440  # passou da meia-noite
                last = mins
                col.append((label, mins))
            if len(col) >= 2:
                cols.append(col)
        header = " ".join(c[1] for _, cells in p for c in cells)
        day = "DU" if "DIAS ÚTEIS" in header else "SAB" if "SÁBADOS" in header else "DOM"
        outbound = rows[0][0].startswith(("Coimbra B", "República"))
        pages.append((day, 0 if outbound else 1, cols))
    return pages


def main():
    os.makedirs(OUT, exist_ok=True)
    shapes, stop_rows, route_stops = {}, {}, {}
    for (ref, d), rid in RELATIONS.items():
        rel, line, stops = shape_and_stops(rid)
        shapes[(ref, d)] = line
        route_stops[(ref, d)] = [(sid, name, along(line, pt)) for sid, name, pt in stops]
        color = rel["tags"].get("colour", "#006AD1").lstrip("#").upper()
        route_stops[(ref, d, "color")] = color
        for sid, name, pt in stops:
            stop_rows[sid] = (name, pt)

    trips, stop_times, freqs = [], [], []
    services = {"DU": "DU", "SAB": "SAB", "DOM": "DOM"}

    def stop_id_for(ref, d, name):
        for sid, n, _ in route_stops[(ref, d)]:
            if norm(n) == norm(name):
                return sid
        return None

    # --- suburbanas: uma viagem por coluna
    seq_offsets = {}  # (ref, d) → {paragem: minutos desde o início}, da 1.ª viagem completa (para as urbanas)
    for day, d, cols in parse_pages():
        for k, col in enumerate(cols):
            names = [n for n, _ in col]
            branch_rep = "República" in names
            ref = "S2" if branch_rep else "S1"
            ids = [(stop_id_for(ref, d, n), n, t) for n, t in col]
            missing = [n for s, n, _ in ids if s is None]
            if missing:
                print(f"aviso: {ref}/{d} sem paragem OSM para {missing}", file=sys.stderr)
            ids = [x for x in ids if x[0] is not None]
            if len(ids) < 2:
                continue
            tid = f"{ref}-{day}-{d}-{k + 1:03d}"
            trips.append((ref, services[day], tid, ids[-1][1], d, f"{ref}-{d}"))
            for i, (sid, n, t) in enumerate(ids):
                stop_times.append((tid, hhmm(t), hhmm(t), sid, i + 1))
            if (ref, d) not in seq_offsets and len(ids) >= 20:
                t0 = ids[0][2]
                seq_offsets[(ref, d)] = {norm(n): t - t0 for _, n, t in ids}

    # --- urbanas: frequências (PDF urbano)
    urb = json.load(open(SRC))["u"][0]
    blocks = {}  # título → {coluna: [valores]}
    titles = [(x, y, s) for x, y, s in urb if " / " in s and len(s) > 10]
    for tx, ty, title in titles:
        col_vals = sorted([(x, y, s) for x, y, s in urb if 0 < ty - y < 200 and tx - 215 <= x <= tx + 340 and s != title], key=lambda c: (-c[1], c[0]))
        blocks[title] = col_vals
    urban_map = {  # título do PDF → (linha, sentido)
        "Coimbra B / Vale das Flores": ("U1", 0), "Vale das Flores / Coimbra B": ("U1", 1),
        "República / Vale das Flores": ("U2", 0), "Vale das Flores / República": ("U2", 1),
        "Coimbra B / República": ("U3", 0), "República / Coimbra B": ("U3", 1),
    }
    periods = [(5 * 60, 7 * 60 + 30), (7 * 60 + 30, 19 * 60), (19 * 60, 24 * 60 + 40)]

    def headway(v):
        nums = [float(x.replace(",", ".")) for x in re.findall(r"[\d,]+", v)]
        return round(sum(nums) / len(nums) * 60) if nums else None

    def mins(v):
        m = re.match(r"(\d{1,2})h(\d{2})", v)
        if not m:
            return None
        h = int(m.group(1)) * 60 + int(m.group(2))
        return h + 1440 if h < 4 * 60 else h

    for title, cells in blocks.items():
        key = urban_map.get(title)
        if not key:
            continue
        ref, d = key
        # linhas do bloco por y: 1ª viagem, 3 períodos, última; colunas por x: DU, SAB, DOM
        rows = {}
        for x, y, s in cells:
            rows.setdefault(y, []).append((x, s))
        ys = sorted(rows, reverse=True)
        table = [[s for _, s in sorted(rows[y])] for y in ys]
        data_rows = [r for r in table if len(r) >= 4]  # rótulo + 3 dias
        first = next(r for r in data_rows if r[0].startswith("1"))
        last = next(r for r in data_rows if r[0].startswith("Última"))
        per = [r for r in data_rows if "|" in r[0]]
        # tempos entre paragens: da suburbana no mesmo troço; U3 pela distância à mesma velocidade
        seq = route_stops[(ref, d)]
        sub = seq_offsets.get(("S1" if ref in ("U1",) else "S2", d)) if ref != "U3" else None
        offs = []
        for sid, name, al in seq:
            if sub and norm(name) in sub:
                offs.append(sub[norm(name)])
            else:
                offs.append(None)
        if None in offs or ref == "U3":
            v = 330.0  # m/min (~20 km/h, média da suburbana no centro)
            base = seq[0][2]
            offs = [round((al - base) / v) for _, _, al in seq]
        base0 = offs[0]
        offs = [o - base0 for o in offs]
        for di, day in enumerate(["DU", "SAB", "DOM"]):
            f, l = mins(first[1 + di]), mins(last[1 + di])
            if f is None or l is None:
                continue
            tid = f"{ref}-{day}-{d}-freq"
            trips.append((ref, services[day], tid, seq[-1][1], d, f"{ref}-{d}"))
            for i, ((sid, name, _), o) in enumerate(zip(seq, offs)):
                stop_times.append((tid, hhmm(o), hhmm(o), sid, i + 1))
            # stop_times relativos (exact_times=0): começam às 00:00 e a frequência dá as partidas
            for (a, b), r in zip(periods, per):
                h = headway(r[1 + di])
                s0, s1 = max(a, f), min(b, l + 1)
                if h and s0 < s1:
                    freqs.append((tid, hhmm(s0), hhmm(s1), h * 60 // 60 * 1 if False else h, 0))

    # --- escrever
    def w(name, header, rows):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as fh:
            c = csv.writer(fh)
            c.writerow(header)
            c.writerows(rows)

    w("agency.txt", ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang", "agency_phone"],
      [["MM", "Metro Mondego", "https://metromondego.pt", "Europe/Lisbon", "pt", ""]])
    refs = sorted({t[0] for t in trips})
    w("routes.txt", ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_color", "route_text_color", "route_desc"],
      [[r, "MM", r, ROUTE_NAMES[r], 3, route_stops[(r, 0, "color")], "FFFFFF", "Metrobus"] for r in refs])
    used = {st[3] for st in stop_times}
    w("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"],
      [[f"osm-{sid}", stop_rows[sid][0], f"{stop_rows[sid][1][0]:.6f}", f"{stop_rows[sid][1][1]:.6f}"] for sid in sorted(used)])
    w("trips.txt", ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"], trips)
    w("stop_times.txt", ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
      [[t, a, dpt, f"osm-{s}", q] for t, a, dpt, s, q in stop_times])
    w("frequencies.txt", ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"],
      [[t, a, b, h * 1, e] for t, a, b, h, e in freqs])
    w("calendar.txt", ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"], [
        ["DU", 1, 1, 1, 1, 1, 0, 0, START.strftime("%Y%m%d"), END.strftime("%Y%m%d")],
        ["SAB", 0, 0, 0, 0, 0, 1, 0, START.strftime("%Y%m%d"), END.strftime("%Y%m%d")],
        ["DOM", 0, 0, 0, 0, 0, 0, 1, START.strftime("%Y%m%d"), END.strftime("%Y%m%d")],
    ])
    cd = []
    for h in HOLIDAYS:
        if START <= h <= END and h.weekday() < 6:
            normal = "DU" if h.weekday() < 5 else "SAB"
            cd += [["DOM", h.strftime("%Y%m%d"), 1], [normal, h.strftime("%Y%m%d"), 2]]
    w("calendar_dates.txt", ["service_id", "date", "exception_type"], cd)
    shape_rows = []
    for (ref, d), line in shapes.items():
        acc = 0.0
        for i, p in enumerate(line):
            if i:
                acc += dist(line[i - 1], p)
            shape_rows.append([f"{ref}-{d}", f"{p[0]:.6f}", f"{p[1]:.6f}", i + 1, f"{acc:.1f}"])
    w("shapes.txt", ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"], shape_rows)
    w("feed_info.txt", ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version", "feed_contact_url"], [[
        "brute maps (não oficial; horários do Metro Mondego, traçado © contribuidores do OpenStreetMap, ODbL)",
        "https://github.com/bquelhas/brutemaps-data", "pt", START.strftime("%Y%m%d"), END.strftime("%Y%m%d"),
        date.today().isoformat(), "https://github.com/bquelhas/brutemaps-data/issues",
    ]])
    with zipfile.ZipFile(os.path.join(HERE, "metro-mondego.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, f), f)
    print(f"{len(refs)} linhas, {len(used)} paragens, {len(trips)} viagens, {len(freqs)} frequências, {len(stop_times)} horas")


if __name__ == "__main__":
    main()
