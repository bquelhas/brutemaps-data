"""Estabelecimentos da Overture Maps (mundo) por quadrícula de 0,2°: places/<lat>_<lon>.tsv
(nome, categoria, lat, lon, rua, localidade), comprimidos. Lê os parquet públicos da Overture
diretamente do S3 com o DuckDB, sem os descarregar todos."""
import duckdb, gzip, os, sys, time, urllib.request, re

def latest_release():
    xml = urllib.request.urlopen("https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/").read().decode()
    return sorted(set(re.findall(r"release/(20\d\d-\d\d-\d\d\.\d+)", xml)))[-1]

rel = os.environ.get("OVERTURE_RELEASE") or latest_release()
print("release", rel, flush=True)
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2'; SET memory_limit='10GB'; SET temp_directory='/tmp/duck';")
con.execute(f"""
CREATE TABLE p AS
SELECT replace(replace(names."primary", chr(9), ' '), chr(10), ' ') AS name,
       coalesce(basic_category, '') AS cat,
       round(ST_Y(geometry), 6) AS lat, round(ST_X(geometry), 6) AS lon,
       replace(coalesce(addresses[1].freeform, ''), chr(9), ' ') AS street,
       replace(coalesce(addresses[1].locality, ''), chr(9), ' ') AS city,
       printf('%.1f_%.1f', floor(ST_Y(geometry) / 0.2) * 0.2, floor(ST_X(geometry) / 0.2) * 0.2) AS cell
FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*', hive_partitioning=1)
WHERE confidence >= 0.5 AND names."primary" IS NOT NULL AND coalesce(operating_status, 'open') = 'open'
""")
print("linhas", con.execute("select count(*) from p").fetchone()[0], flush=True)
os.makedirs("out", exist_ok=True)
cur = con.execute("select cell, name, cat, lat, lon, street, city from p order by cell")
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
    for c, name, cat, lat, lon, st, ci in rows:
        if c != cell:
            flush(); cell, buf = c, []
        buf.append(f"{name}\t{cat}\t{lat}\t{lon}\t{st}\t{ci}")
flush()
print("quadrículas", n)
