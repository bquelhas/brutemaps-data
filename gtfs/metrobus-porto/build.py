"""GTFS do metroBus do Porto (linha M1, Casa da Música ↔ Império; Metro do Porto, operação STCP).

Não há GTFS oficial (nem no do Metro do Porto nem no da STCP, setembro 2026). Feito a partir de:
  - regras oficiais de horário e frequência (metrobus.metrodoporto.pt, "Qual é a frequência do serviço?"):
    todos os dias 06:30–22:00; dias úteis 10 em 10 min nas pontas (07:30–10:00, 16:30–19:30) e 15 em 15
    no resto; fins de semana e feriados 15 em 15; ~12 min de ponta a ponta;
  - paragens e traçado das relações M1 do OpenStreetMap (ODbL).
Os tempos entre paragens repartem os 12 min pela distância ao longo do traçado.
"""
import csv, os, sys, zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metro-mondego"))
import build as mm  # noqa: E402  (funções do OSM e do traçado)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
mm.HERE = HERE  # a cache do OSM fica em ./fonte
START, END = date(2026, 4, 20), date(2027, 3, 31)
RELATIONS = {0: 20295428, 1: 20295429}  # Casa da Música → Império, Império → Casa da Música
TRIP_MIN = 12
WEEKDAY = [(6 * 60 + 30, 7 * 60 + 30, 15), (7 * 60 + 30, 10 * 60, 10), (10 * 60, 16 * 60 + 30, 15),
           (16 * 60 + 30, 19 * 60 + 30, 10), (19 * 60 + 30, 22 * 60 + 1, 15)]
WEEKEND = [(6 * 60 + 30, 22 * 60 + 1, 15)]
HOLIDAYS = [date(2026, 4, 25), date(2026, 5, 1), date(2026, 6, 4), date(2026, 6, 10), date(2026, 6, 24),
            date(2026, 8, 15), date(2026, 10, 5), date(2026, 11, 1), date(2026, 12, 1), date(2026, 12, 8),
            date(2026, 12, 25), date(2027, 1, 1)]  # nacionais + São João (Porto, 24 jun)


def main():
    os.makedirs(OUT, exist_ok=True)
    trips, stop_times, freqs, stops_all, shapes = [], [], [], {}, {}
    for d, rid in RELATIONS.items():
        rel, line, stops = mm.shape_and_stops(rid)
        shapes[d] = line
        al = [mm.along(line, pt) for _, _, pt in stops]
        span = (al[-1] - al[0]) or 1
        for sid, name, pt in stops:
            stops_all[sid] = (name, pt)
        for day, periods in (("DU", WEEKDAY), ("FDS", WEEKEND)):
            tid = f"M1-{day}-{d}"
            trips.append(["M1", day, tid, stops[-1][1], d, f"M1-{d}"])
            for i, ((sid, _, _), a) in enumerate(zip(stops, al)):
                t = round((a - al[0]) / span * TRIP_MIN)
                stop_times.append([tid, mm.hhmm(t), mm.hhmm(t), f"osm-{sid}", i + 1])
            for a, b, h in periods:
                freqs.append([tid, mm.hhmm(a), mm.hhmm(b), h * 60, 0])

    def w(name, header, rows):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as fh:
            c = csv.writer(fh); c.writerow(header); c.writerows(rows)

    w("agency.txt", ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"],
      [["MBP", "metroBus do Porto (Metro do Porto / STCP)", "https://metrobus.metrodoporto.pt", "Europe/Lisbon", "pt"]])
    w("routes.txt", ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_color", "route_text_color", "route_desc"],
      [["M1", "MBP", "M1", "Casa da Música – Império", 3, "00A3E0", "FFFFFF", "Metrobus"]])
    w("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"],
      [[f"osm-{s}", n, f"{p[0]:.6f}", f"{p[1]:.6f}"] for s, (n, p) in sorted(stops_all.items())])
    w("trips.txt", ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"], trips)
    w("stop_times.txt", ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"], stop_times)
    w("frequencies.txt", ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"], freqs)
    s, e = START.strftime("%Y%m%d"), END.strftime("%Y%m%d")
    w("calendar.txt", ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
      [["DU", 1, 1, 1, 1, 1, 0, 0, s, e], ["FDS", 0, 0, 0, 0, 0, 1, 1, s, e]])
    cd = []
    for h in HOLIDAYS:
        if START <= h <= END and h.weekday() < 5:
            cd += [["FDS", h.strftime("%Y%m%d"), 1], ["DU", h.strftime("%Y%m%d"), 2]]
    w("calendar_dates.txt", ["service_id", "date", "exception_type"], cd)
    rows = []
    for d, line in shapes.items():
        acc = 0.0
        for i, p in enumerate(line):
            if i:
                acc += mm.dist(line[i - 1], p)
            rows.append([f"M1-{d}", f"{p[0]:.6f}", f"{p[1]:.6f}", i + 1, f"{acc:.1f}"])
    w("shapes.txt", ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"], rows)
    w("feed_info.txt", ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version", "feed_contact_url"],
      [["brute maps (não oficial; regras de frequência do Metro do Porto, traçado © contribuidores do OpenStreetMap, ODbL)",
        "https://github.com/bquelhas/brutemaps-data", "pt", s, e, date.today().isoformat(), "https://github.com/bquelhas/brutemaps-data/issues"]])
    with zipfile.ZipFile(os.path.join(HERE, "metrobus-porto.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, f), f)
    print(f"{len(stops_all)} paragens, {len(trips)} viagens-modelo, {len(freqs)} frequências")


if __name__ == "__main__":
    main()
