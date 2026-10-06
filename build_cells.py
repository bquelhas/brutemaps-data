"""Linhas de metro/comboio suburbano por quadrícula de 0,2° (o mesmo pedido que a app faz ao
Overpass), para as cidades de cities.txt. Guarda cells/<lat>_<lon>.json; só refaz as que têm
mais de 6 dias. A app lê daqui primeiro e só vai ao Overpass se a quadrícula não existir."""
import json, math, os, sys, time, urllib.parse, urllib.request

CELL = 0.2
SERVERS = ["https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
MAX_AGE = 6 * 24 * 3600
BUDGET = float(os.environ.get("BUDGET_S", "18000"))  # pára antes do limite do GitHub Actions
start = time.time()

def cells_for(lat, lon, r):
    out = set()
    a = lat - r
    while a < lat + r:
        b = lon - r
        while b < lon + r:
            out.add((round(math.floor(a / CELL) * CELL, 1), round(math.floor(b / CELL) * CELL, 1)))
            b += CELL
        a += CELL
    return out

def query(lat, lon):
    bbox = "%.4f,%.4f,%.4f,%.4f" % (lat, lon, lat + CELL, lon + CELL)
    q = ("[out:json][timeout:90];("
         f"relation[type=route][route~\"^(subway|light_rail|monorail)$\"]({bbox});"
         f"relation[type=route][route=train][service~\"^(commuter|suburban|urban)$\"]({bbox}););"
         f"out geom({bbox});")
    for attempt in range(3):
        for s in SERVERS:
            try:
                req = urllib.request.Request(s, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "brutemaps-data (github.com/bquelhas/brutemaps-data)"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    body = r.read().decode()
                    if body.startswith("{"):
                        return body
            except Exception as e:
                print("  falhou", s, e, file=sys.stderr)
        time.sleep(20 * (attempt + 1))
    return None

os.makedirs("cells", exist_ok=True)
todo = []  # pela ordem de cities.txt (Porto primeiro), não por coordenadas
for line in open("cities.txt"):
    line = line.split("#")[0].strip()
    if not line:
        continue
    name, lat, lon, r = [x.strip() for x in line.split(",")]
    todo += [c for c in sorted(cells_for(float(lat), float(lon), float(r))) if c not in todo]

def age(path):
    # a data do ficheiro num checkout é sempre "agora": a idade vem do campo t
    try:
        return time.time() - json.load(open(path)).get("t", 0)
    except Exception:
        return float("inf")
done = 0
for lat, lon in todo:
    if time.time() - start > BUDGET:
        print("fim do tempo; o resto fica para a próxima"); break
    path = "cells/%.1f_%.1f.json" % (lat, lon)
    if age(path) < MAX_AGE:
        continue
    body = query(lat, lon)
    if body:
        # sem as chaves inúteis à app (menos peso)
        d = json.loads(body)
        open(path, "w").write(json.dumps({"t": int(time.time()), "elements": d.get("elements", [])}, separators=(",", ":")))
        done += 1
        print("ok", path)
    time.sleep(3)
print("quadrículas novas:", done, "de", len(todo))
