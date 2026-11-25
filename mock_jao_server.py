#!/usr/bin/env python3
"""Local stand-in for the JAO Publication Tool API (Final Computation) for end-to-end tests without internet.

It serves hourly data of synthetic critical network elements built from the Static Grid Model in data/static (names, EIC, voltage, limits). Every element has its own
probability to be part of an hour (like the changing CNEC selection at JAO): a few appear in almost every hour, most only now and then. Per element and hour there are two base-case rows
(both directions) and several n-1 rows. THE VALUES ARE SYNTHETIC. The tool only checks the pipeline (fetching, aggregation, storage, runtime, file sizes), never real utilization.

  python scripts/mock_jao_server.py --port 8765
  JAO_BASE_URL=http://127.0.0.1:8765/core/api python scripts/fetch_jao.py --from 2026-11-17 --to 2026-11-23
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONT_PER_ELEMENT = 6          # n-1 rows per element and hour (the real hour has about 20 rows per element); change with --contingencies


def build_catalog(seed: int = 7) -> pd.DataFrame:
    st = ROOT / "data" / "static"
    lines = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in sorted(st.glob("sgm_lines_*.csv"))], ignore_index=True)
    lines = lines[lines["eic"] != ""].copy()
    imax = pd.to_numeric(lines["imax_fixed_a"], errors="coerce").fillna(pd.to_numeric(lines["imax_period_1_a"], errors="coerce")).fillna(2000)
    kv = pd.to_numeric(lines["voltage_kv"], errors="coerce").fillna(380)
    cat = pd.DataFrame({"name": lines["element_name"], "eic": lines["eic"], "tso": lines["tso"], "sub_from": lines["substation_1"], "sub_to": lines["substation_2"], "kv": kv, "imax": imax,
                        "element_type": ["TieLine" if t == "Tie-line" else "Line" for t in lines["type"]], "hub_from": lines["country"], "hub_to": [n or c for n, c in zip(lines["neighbor_country"], lines["country"])]})
    cat["fmax"] = np.sqrt(3) * cat["kv"] * cat["imax"] / 1000.0
    rng = np.random.default_rng(seed)
    cat["p"] = rng.beta(0.35, 1.6, len(cat))              # probability of being in an hour: heavy-tailed
    cat["base"] = rng.uniform(0.05, 0.8, len(cat))
    cat["phase"] = rng.uniform(0, 2 * math.pi, len(cat))
    return cat.drop_duplicates("eic").reset_index(drop=True)


def rows_for_hour(cat: pd.DataFrame, start: pd.Timestamp) -> list[dict]:
    rng = np.random.default_rng(int(hashlib.md5(str(start).encode()).hexdigest()[:8], 16))
    pick = rng.random(len(cat)) < cat["p"].to_numpy()
    c = cat[pick]
    hour_angle = 2 * math.pi * (start.hour + start.dayofyear * 0.7) / 24
    util = np.clip(c["base"].to_numpy() * (0.85 + 0.3 * np.sin(hour_angle + c["phase"].to_numpy())) + rng.normal(0, 0.03, len(c)), 0.01, 1.3)
    hot = rng.random(len(c)) < 0.01
    util = np.where(hot, rng.uniform(0.95, 1.2, len(c)), util)
    recs = []
    ts = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    names = c["name"].tolist()
    for i, r in enumerate(c.itertuples(index=False)):
        base = dict(DateTimeUtc=ts, Tso=r.tso, CneName=r.name, CneEic=r.eic, Fmax=round(float(r.fmax), 2), Imax=float(r.imax), U=float(r.kv), Presolved=bool(hot[i] and rng.random() < 0.5),
                    ElementType=r.element_type, HubFrom=r.hub_from, HubTo=r.hub_to, SubstationFrom=r.sub_from, SubstationTo=r.sub_to, ContName=None)
        for sign, direction in ((1, "DIRECT"), (-1, "OPPOSITE")):
            recs.append({**base, "Direction": direction, "Fref": round(sign * float(util[i] * r.fmax), 2)})
        for k in range(CONT_PER_ELEMENT):
            recs.append({**base, "Direction": "DIRECT", "Fref": round(float(min(1.4, util[i] * rng.uniform(1.0, 1.35)) * r.fmax), 2), "ContName": names[(i * 7 + k * 13) % len(names)]})
    recs.append(dict(DateTimeUtc=ts, Tso="AMPRION", CneName="External Constraint BE_AL_export", CneEic=None, Fmax=1000.0, Fref=100.0, Imax=9999.0, U=380.0, ContName=None))
    return recs


def make_handler(cat, today: str, log):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path.endswith("/system/monitoring"):
                day = q["FromUtc"][:10]
                status = "Received" if day < today else "Expected"
                body = [{"page": "Final Computation", "businessDay": day, "status": status}]
            elif u.path.endswith("/data/finalComputation"):
                start = pd.Timestamp(q["FromUtc"])
                rows = rows_for_hour(cat, start)
                log.append(len(rows))
                body = {"data": rows, "rejected": False, "totalRows": len(rows)}
            else:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass
    return H


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--today", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="days before this date are 'Received', later ones 'Expected'")
    ap.add_argument("--contingencies", type=int, default=CONT_PER_ELEMENT, help="n-1 rows per element and hour (more rows = more load for the pipeline)")
    args = ap.parse_args()
    globals()["CONT_PER_ELEMENT"] = args.contingencies
    cat = build_catalog()
    print(f"mock JAO server on port {args.port}: {len(cat)} synthetic elements, about {int(cat['p'].sum())} per hour (SYNTHETIC VALUES)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(cat, args.today, [])).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
