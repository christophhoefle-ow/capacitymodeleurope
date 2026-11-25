"""End-to-end test of the pipeline without internet: mock JAO server -> client -> aggregation -> daily files -> monthly table."""
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pandas as pd

import mock_jao_server as mock
from capmodel.aggregate import daily_aggregate
from capmodel.jao_client import JaoClient
from capmodel.mapping import monthly_from_daily, sgm_elements
from capmodel.storage import read_daily, write_day

TSOS = {"50HERTZ": "DE", "AMPRION": "DE", "TENNETGMBH": "DE", "TRANSNETBW": "DE", "TENNETBV": "NL", "ELIA": "BE", "CREOS": "LU", "RTE": "FR", "APG": "AT", "CEPS": "CZ", "SEPS": "SK",
        "MAVIR": "HU", "PSE": "PL", "TRANSELECTRICA": "RO", "ELES": "SI", "HOPS": "HR"}


def test_two_simulated_days_run_through_all_stages_and_coverage_grows():
    mock.CONT_PER_ELEMENT = 2
    cat = mock.build_catalog()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock.make_handler(cat, "2026-12-01", []))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = JaoClient(f"http://127.0.0.1:{srv.server_port}/core/api", pause_s=0, backoff_base_s=0)
        with tempfile.TemporaryDirectory() as d:
            sizes = []
            for day in ("2026-11-17", "2026-11-18"):
                assert client.monitoring_status(day) == "received"
                frame, expected, hours = client.fetch_day(day, TSOS)
                assert (expected, hours) == (24, 24) and frame["tso"].nunique() >= 10
                agg = daily_aggregate(frame, day, 0.8, 1.0, "base_case")
                write_day(d, day, agg)
                sizes.append(len(agg))
            daily = read_daily(d)
            lines = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in sorted((Path(mock.ROOT) / "data" / "static").glob("sgm_lines_*.csv"))], ignore_index=True)
            sgm = sgm_elements(lines, pd.DataFrame(columns=["element_name", "eic"]))
            one = monthly_from_daily(daily[daily["day"] == "2026-11-17"], sgm)
            two = monthly_from_daily(daily, sgm)
            assert sorted(p.name for p in Path(d).iterdir()) == ["2026-11-17.csv.gz", "2026-11-18.csv.gz"]
            assert sizes[0] > 500 and daily["day"].nunique() == 2
            assert len(two) > len(one) and two["hours"].max() <= 48          # more days: more elements with data, hours add up
            assert (two["match"] != "unmatched").mean() > 0.95                # the synthetic elements come from the model itself
    finally:
        srv.shutdown()
