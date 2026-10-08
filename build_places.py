"""Estabelecimentos por quadrícula de 0,2° (âmbito em BOUNDS): places/<lat>_<lon>.tsv
(nome, categoria, lat, lon, rua, localidade, horário), comprimidos.

Duas fontes abertas:
  - AllThePlaces (CC0, todas as semanas): cadeias e marcas, tiradas dos sites das próprias marcas
    — posição, nome oficial e horário bons. Tem prioridade.
  - Overture Maps (CDLA-Permissive): a cobertura geral (cafés, lojas independentes…).
Quando os dois têm o mesmo sítio (nome igual ou muito parecido a menos de ~100 m), fica o do
AllThePlaces. A Overture lê-se do S3 com o DuckDB; o AllThePlaces vem num zip de GeoJSON."""
import duckdb, gzip, io, json, os, shutil, sys, time, urllib.request, re, zipfile

# Âmbito: a Overture no mundo inteiro dava ~178 mil quadrículas (~50 GB no R2, acima dos 10 GB
# grátis) e uploads de horas. Gera-se só onde a app é usada; caixas (lat_min, lon_min, lat_max,
# lon_max) — acrescentar as que fizerem falta. Lista vazia = mundo inteiro.
BOUNDS = [
    (35.8, -10.0, 44.0, 4.6),   # Península Ibérica (Portugal, Espanha, Baleares)
]
def in_bounds(lat, lon):
    return (not BOUNDS) or any(a <= lat <= c and b <= lon <= d for a, b, c, d in BOUNDS)


def latest_release():
    xml = urllib.request.urlopen("https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/").read().decode()
    return sorted(set(re.findall(r"release/(20\d\d-\d\d-\d\d\.\d+)", xml)))[-1]

rel = os.environ.get("OVERTURE_RELEASE") or latest_release()
print("release", rel, flush=True)
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2'; SET memory_limit='10GB'; SET temp_directory='/tmp/duck';")
bounds = '' if not BOUNDS else ' AND (' + ' OR '.join(
    f'(ST_Y(geometry) BETWEEN {a} AND {c} AND ST_X(geometry) BETWEEN {b} AND {d})' for a, b, c, d in BOUNDS) + ')'
con.execute(f"""
CREATE TABLE p AS
SELECT replace(replace(names."primary", chr(9), ' '), chr(10), ' ') AS name,
       coalesce(basic_category, '') AS cat,
       round(ST_Y(geometry), 6) AS lat, round(ST_X(geometry), 6) AS lon,
       replace(coalesce(addresses[1].freeform, ''), chr(9), ' ') AS street,
       replace(coalesce(addresses[1].locality, ''), chr(9), ' ') AS city,
       printf('%.1f_%.1f', floor(ST_Y(geometry) / 0.2) * 0.2, floor(ST_X(geometry) / 0.2) * 0.2) AS cell
FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*', hive_partitioning=1)
WHERE confidence >= 0.5 AND names."primary" IS NOT NULL AND coalesce(operating_status, 'open') = 'open'{bounds}
""")
print("overture", con.execute("select count(*) from p").fetchone()[0], flush=True)

# --- AllThePlaces: último run com o zip publicado
def clean(v):
    return re.sub(r"[\t\r\n]+", " ", str(v or "")).strip()

atp_rows = 0
try:
    # o data.alltheplaces.xyz responde 403 ao User-Agent do urllib: manda-se um próprio
    _ua = {"User-Agent": "brutemaps-data/1.0 (+https://github.com/bquelhas/brutemaps-data)"}
    def _get(url):
        return urllib.request.urlopen(urllib.request.Request(url, headers=_ua))
    run = json.load(_get("https://data.alltheplaces.xyz/runs/latest.json"))
    print("atp", run["run_id"], flush=True)
    with _get(run["output_url"]) as r, open("/tmp/atp.zip", "wb") as f:
        shutil.copyfileobj(r, f)
    CAT_KEYS = ("shop", "amenity", "tourism", "leisure", "office", "craft", "healthcare")
    with zipfile.ZipFile("/tmp/atp.zip") as z, open("/tmp/atp.tsv", "w") as out:
        for n in z.namelist():
            if not n.endswith(".geojson"):
                continue
            try:
                feats = json.loads(z.read(n)).get("features", [])
            except Exception:
                continue
            for f in feats:
                g = f.get("geometry") or {}
                if g.get("type") != "Point":
                    continue
                lon, lat = g["coordinates"][:2]
                pr = f.get("properties") or {}
                name = clean(pr.get("name") or pr.get("brand"))
                if not name or not (-90 <= lat <= 90 and -180 <= lon <= 180) or not in_bounds(lat, lon):
                    continue
                cat = next((clean(pr[k]) for k in CAT_KEYS if pr.get(k)), "")
                street = clean(pr.get("addr:street_address") or " ".join(x for x in (clean(pr.get("addr:street")), clean(pr.get("addr:housenumber"))) if x) or pr.get("addr:full"))
                out.write("\t".join([name, cat, f"{lat:.6f}", f"{lon:.6f}", street, clean(pr.get("addr:city")), clean(pr.get("opening_hours"))]) + "\n")
                atp_rows += 1
    os.remove("/tmp/atp.zip")
    con.execute("""CREATE TABLE a AS SELECT name, cat, lat, lon, street, city, hours,
        printf('%.1f_%.1f', floor(lat / 0.2) * 0.2, floor(lon / 0.2) * 0.2) AS cell
        FROM read_csv('/tmp/atp.tsv', delim=chr(9), header=false, quote='', escape='',
          columns={'name':'VARCHAR','cat':'VARCHAR','lat':'DOUBLE','lon':'DOUBLE','street':'VARCHAR','city':'VARCHAR','hours':'VARCHAR'})""")
    print("atp linhas", atp_rows, flush=True)
    # a Overture perde os repetidos (mesma quadrícula, ~100 m, nome igual/contido/parecido)
    con.execute("""DELETE FROM p WHERE rowid IN (
        SELECT p.rowid FROM p JOIN a ON p.cell = a.cell
         AND abs(p.lat - a.lat) < 0.0009 AND abs(p.lon - a.lon) < 0.0012
         AND (lower(p.name) = lower(a.name) OR strpos(lower(p.name), lower(a.name)) > 0
              OR strpos(lower(a.name), lower(p.name)) > 0 OR jaro_winkler_similarity(lower(p.name), lower(a.name)) > 0.88))""")
    print("overture sem repetidos", con.execute("select count(*) from p").fetchone()[0], flush=True)
except Exception as e:
    # sem AllThePlaces este mês: fica só a Overture (melhor do que nada)
    print("AllThePlaces falhou:", e, flush=True)
    con.execute("CREATE TABLE a (name VARCHAR, cat VARCHAR, lat DOUBLE, lon DOUBLE, street VARCHAR, city VARCHAR, hours VARCHAR, cell VARCHAR)")
os.makedirs("out", exist_ok=True)
# o AllThePlaces primeiro dentro de cada quadrícula
cur = con.execute("""select cell, name, cat, lat, lon, street, city, hours from (
    select cell, name, cat, lat, lon, street, city, hours, 0 as src from a
    union all select cell, name, cat, lat, lon, street, city, '' as hours, 1 as src from p) order by cell, src""")
cell, buf, n = None, [], 0
def flush():
    global n
    if cell is None: return
    k = cell.replace("-0.0", "0.0")
    with gzip.open(f"out/{k}.tsv", "wt", compresslevel=9) as f:
        f.write("\n".join(buf))
    n += 1
while True:
    rows = cur.fetchmany(200000)
    if not rows: break
    for c, name, cat, lat, lon, st, ci, hrs in rows:
        if c != cell:
            flush(); cell, buf = c, []
        buf.append(f"{name}\t{cat}\t{lat}\t{lon}\t{st}\t{ci}\t{hrs}")
flush()
print("quadrículas", n)
