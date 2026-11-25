"""Tests des JAO-Clients gegen einen lokalen Schein-Server (kein Internet nötig)."""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from capmodel.jao_client import JaoClient, JaoError, JaoRejected

FIRST_HOUR = "2026-11-15T23:00:00.000Z"
ROWS = [  # JSON-Schreibweise in camelCase – der Client muss auch das verstehen
    {"dateTimeUtc": "2026-11-15T23:00:00Z", "tso": "AMPRION", "cneName": f"Leitung {i} ", "cneEic": f"EIC-{i}",
     "fmax": 1000.0, "fref": 100.0 * i}
    for i in range(1, 6)
] + [{"dateTimeUtc": "2026-11-15T23:00:00Z", "tso": "TENNETBV", "cneName": "NL", "cneEic": "EIC-NL",
      "fmax": 1000.0, "fref": 50.0}]


@contextmanager
def serve(handler_fn):
    """Startet einen Schein-Server; handler_fn(path, query, state) -> (status, body_dict_or_str)."""
    state = {"requests": []}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            state["requests"].append((u.path, q))
            status, body = handler_fn(u.path, q, state)
            raw = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/core/api", state
    finally:
        srv.shutdown()


def _client(base, **kw):
    return JaoClient(base, pause_s=0, backoff_base_s=0, **kw)


def test_fetch_day_calls_24_hourly_windows_and_keeps_only_german_tsos():
    def h(path, q, state):
        if path.endswith("/data/finalComputation"):
            rows = ROWS if q["FromUtc"] == FIRST_HOUR else []
            return 200, {"data": rows, "rejected": False, "totalRows": len(rows)}
        return 404, ""
    with serve(h) as (base, state):
        frame, expected, with_data = _client(base).fetch_day("2026-11-16", ["AMPRION", "50HERTZ"])
    assert expected == 24 and with_data == 1
    assert len(state["requests"]) == 24
    froms = [q["FromUtc"] for _, q in state["requests"]]
    assert froms[0] == FIRST_HOUR and froms[-1] == "2026-11-16T22:00:00.000Z" and len(set(froms)) == 24
    assert len(frame) == 5 and set(frame["tso"]) == {"AMPRION"}       # TENNETBV (NL) herausgefiltert


def test_partial_answer_triggers_paging_with_take_cap():
    def h(path, q, state):
        if "Skip" not in q:
            return 200, {"data": ROWS[:2], "rejected": False, "totalRows": 6}
        skip, take = int(q["Skip"]), int(q["Take"])
        return 200, {"data": ROWS[skip:skip + min(take, 4)], "rejected": False, "totalRows": 6}
    with serve(h) as (base, state):
        rows = _client(base, take=999999).fetch_hour("2026-11-15T23:00:00Z")
    assert len(rows) == 6
    takes = [int(q["Take"]) for _, q in state["requests"] if "Take" in q]
    assert takes and max(takes) <= 100000                              # JAO-Limit ab 19.11.2026


def test_rejected_flag_is_an_error_even_with_http_200():
    with serve(lambda p, q, s: (200, {"data": [], "rejected": True, "messages": "Zeitraum zu lang"})) as (base, _):
        try:
            _client(base).fetch_hour("2026-11-15T23:00:00Z")
            raise AssertionError("JaoRejected erwartet")
        except JaoRejected as exc:
            assert "Zeitraum zu lang" in str(exc)


def test_server_error_is_retried_but_400_is_not():
    def flaky(path, q, state):
        return (500, "boom") if len(state["requests"]) <= 2 else (200, {"data": ROWS[:1], "rejected": False, "totalRows": 1})
    with serve(flaky) as (base, state):
        assert len(_client(base).fetch_hour("2026-11-15T23:00:00Z")) == 1
        assert len(state["requests"]) == 3
    with serve(lambda p, q, s: (400, "Zeitraum zu lang")) as (base, state):
        try:
            _client(base).fetch_hour("2026-11-15T23:00:00Z")
            raise AssertionError("JaoError erwartet")
        except JaoError:
            assert len(state["requests"]) == 1


def test_monitoring_interpretation():
    for payload, expected in (
        ([{"page": "finalComputation", "status": "Received", "businessDay": "2026-11-16"}], True),
        ({"data": [{"Page": "FinalComputation", "Status": "Expected", "Date": "2026-11-16T00:00:00"}]}, False),
        ([{"page": "netPos", "status": "Received"}], None),                       # anderer Datensatz
        ({"irgendwas": 1}, None),                                                # unbekanntes Format
    ):
        with serve(lambda p, q, s, pl=payload: (200, pl)) as (base, _):
            assert _client(base).monitoring_received("2026-11-16") is expected


def test_monitoring_fallback_and_page_names_with_spaces():
    for payload, expected in (
        ([{"page": "Final Computation", "status": "Spanning/DFP", "date": "2026-11-16"}], "fallback"),
        ([{"page": "Final Computation", "status": "Pending"}], "pending"),
        ([{"page": "Final Computation", "status": "Received"}], "received"),
        ([{"page": "Final Computation", "status": "Expected"}, {"page": "LTN", "status": "Received"}], "expected"),
    ):
        with serve(lambda p, q, s, pl=payload: (200, pl)) as (base, _):
            assert _client(base).monitoring_status("2026-11-16") == expected


def test_optional_token_is_sent_as_bearer_header():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["auth"] = self.headers.get("Authorization")
            raw = json.dumps({"data": [], "rejected": False, "totalRows": 0}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}/core/api"
        JaoClient(base, pause_s=0, backoff_base_s=0, token="geheim").fetch_hour("2026-11-15T23:00:00Z")
        assert seen["auth"] == "Bearer geheim"
        JaoClient(base, pause_s=0, backoff_base_s=0).fetch_hour("2026-11-15T23:00:00Z")
        assert seen["auth"] is None
    finally:
        srv.shutdown()
