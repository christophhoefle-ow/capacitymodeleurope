"""Reading of the JAO Core Static Grid Model (all TSOs) and of TSO files with coordinates.

The JAO workbook has the sheets Lines, Tielines and Transformers (header in the second row below a group row). The TSO spellings of the SGM are mapped to the spellings of the
JAO Final Computation (so that the same TSO has one name everywhere). Cross-border tie-lines are told from internal ones (between two TSOs of one country) by the neighbour country in
the comment. Tie-lines listed by two TSOs (same EIC) are kept once.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

SGM_TSO = {"AMPRION GMBH": "AMPRION", "TENNET NL": "TENNETBV", "TEL": "TRANSELECTRICA", "CREOS": "CREOS"}
COUNTRY_WORDS = {"netherland": "NL", "netherlands": "NL", "german": "DE", "germany": "DE", "austria": "AT", "belgium": "BE", "france": "FR", "poland": "PL", "czech": "CZ",
                 "hungary": "HU", "croatia": "HR", "slovenia": "SI", "slovakia": "SK", "romania": "RO", "luxembourg": "LU", "switzerland": "CH", "denmark": "DK"}
TSO_WORDS = {"apg": "AT", "50hertz": "DE", "amprion": "DE", "tennet": "DE", "transnetbw": "DE", "ceps": "CZ", "pse": "PL", "elia": "BE", "rte": "FR", "mavir": "HU", "seps": "SK",
             "hops": "HR", "eles": "SI", "transelectrica": "RO", "creos": "LU"}
CODES = {"AT", "BE", "CZ", "DE", "FR", "HR", "HU", "LU", "NL", "PL", "RO", "SI", "SK", "CH", "DK", "NO", "RS", "UA", "BA", "IT", "BG", "ME", "MK", "AL", "SE"}
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ő": "oe", "ű": "ue", "ø": "oe", "æ": "ae", "ł": "l", "đ": "d"})


_VOLT_SUFFIX = re.compile(r"\s+(110|132|150|220|225|380|400)\s*(kv)?\s*$", re.I)


_BUSBAR = re.compile(r"\s+[1-9]$")


def display_name(name) -> str:
    """Substation name without voltage level and busbar number ('Meeden 380', 'Meeden 220' and 'Meeden' are one substation; so are 'Ernsthofen 2' and 'Ernsthofen')."""
    return _BUSBAR.sub("", _VOLT_SUFFIX.sub("", str(name or "").strip())).strip()


def pretty_name(name) -> str:
    """Display name: voltage suffix removed, names written in capitals only (PSE, RTE) in normal capitalisation."""
    n = display_name(name)
    return n.title() if n.isupper() and len(n) > 3 else n


def node_key(name) -> str:
    """Identity of a substation independent of spelling and voltage level: 'Röhrsdorf' and 'Roehrsdorf', 'Győr' and 'Gyoer', 'Meeden 380' and 'Meeden' give the same key."""
    t = display_name(name).casefold().translate(_TRANSLIT)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", t)


_COUNTRY_SUFFIX = re.compile(r"\s+\(([A-Z]{2})\)$")


def split_suffix(name) -> tuple[str, str]:
    """('St. Peter (AT)') -> ('St. Peter', 'AT'). The suffix marks a name that stands for different sites in different countries (see mapping.split_homonyms)."""
    n = str(name or "").strip()
    m = _COUNTRY_SUFFIX.search(n)
    if m and m.group(1) in CODES:
        return n[:m.start()].strip(), m.group(1)
    return n, ""


def base_key(name) -> str:
    """Name key without the country suffix: used to look a substation up in outside sources (coordinates, JAO names), which do not carry the suffix."""
    return node_key(split_suffix(name)[0])


def tso_name(raw: str) -> str:
    t = str(raw).strip().upper()
    return SGM_TSO.get(t, t)


def neighbour_from_comment(comment, own: str) -> str:
    """Country at the other end of a tie-line; equal to `own` for internal tie-lines (two TSOs of one country)."""
    c = str(comment or "")
    low = c.casefold()
    if "internal" in low:
        return own
    all_codes = [k for k in re.findall(r"\b([A-Z]{2})\b", c) if k in CODES]
    others = [k for k in all_codes if k != own]
    if others:
        return others[0]
    if all_codes:                                    # only the own country is named: internal tie-line (e.g. 'Tie-line to DE (TTG)' of a German TSO)
        return own
    for w, code in COUNTRY_WORDS.items():
        if re.search(rf"\b{w}", low) and code != own:
            return code
    for w, code in TSO_WORDS.items():
        if re.search(rf"\b{w}", low):
            return code
    return ""


def _find_header(raw: pd.DataFrame, first: tuple) -> int:
    for i in range(min(8, len(raw))):
        if str(raw.iat[i, 0]).strip().casefold() in first:
            return i
    raise ValueError(f"header row with {first} not found")


def _cols(header: list) -> dict:
    """Column positions by header text (prefix match, case-insensitive); duplicates keep every position."""
    pos: dict[str, list[int]] = {}
    for i, h in enumerate(header):
        pos.setdefault(str(h).strip().casefold(), []).append(i)
    return pos


def _pick(pos: dict, *prefixes, nth=0):
    for p in prefixes:
        for k, v in pos.items():
            if k.startswith(p) and len(v) > nth:
                return v[nth]
    return None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def read_lines(path: str, tso_country: dict) -> pd.DataFrame:
    """Lines and tie-lines of all TSOs in the static column layout (English headers, see mapping.LINE_COLUMNS)."""
    parts = []
    for sheet in ("Lines", "Tielines"):
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        h = _find_header(raw, ("ne_name",))
        pos = _cols(raw.iloc[h].tolist())
        d = raw.iloc[h + 1:].reset_index(drop=True)
        d = d[d.iloc[:, 0].notna()]
        g = lambda *p, nth=0: d.iloc[:, _pick(pos, *p, nth=nth)]
        out = pd.DataFrame({"element_name": g("ne_name").astype(str).str.strip(), "eic": g("eic_code").astype(str).str.strip().replace({"nan": ""}),
                            "tso": g("tso").map(tso_name), "substation_1": g("full_name", nth=0).astype(str).str.strip(), "substation_2": g("full_name", nth=1).astype(str).str.strip(),
                            "voltage_kv": _num(g("voltage_level"))})
        for i in range(1, 7):
            out[f"imax_period_{i}_a"] = _num(g(f"period {i}"))
        out["imax_fixed_a"], out["dlr_min_a"], out["dlr_max_a"] = _num(g("fixed")), _num(g("dlrmin")), _num(g("dlrmax"))
        out["r_ohm"], out["x_ohm"], out["b_us"], out["length_km"] = _num(g("resistance")), _num(g("reactance")), _num(g("susceptance")), _num(g("length"))
        out["jao_comment"] = g("comment").astype(str).replace({"nan": ""}).str.strip()
        out["country"] = out["tso"].map(tso_country).fillna("")
        if sheet == "Lines":
            out["type"], out["neighbor_country"] = "Line", ""
        else:
            nb = [neighbour_from_comment(c, own) for c, own in zip(out["jao_comment"], out["country"])]
            out["neighbor_country"] = ["" if (n == own or not n) and "internal" in str(c).casefold() or n == own else n for n, own, c in zip(nb, out["country"], out["jao_comment"])]
            out["type"] = ["Internal tie-line" if (n == own or "internal" in str(c).casefold()) else "Tie-line" for n, own, c in zip(nb, out["country"], out["jao_comment"])]
        out["source"] = "SGM"
        out["_sheet"] = 0 if sheet == "Lines" else 1
        parts.append(out)
    lines = pd.concat(parts, ignore_index=True)
    # tie-lines listed by two TSOs (same EIC): keep one row, prefer the most complete one; remember the other TSO
    num_cols = [c for c in lines.columns if c.endswith("_a") or c in ("r_ohm", "x_ohm", "b_us", "length_km")]
    lines["_fill"] = lines[num_cols].notna().sum(axis=1)
    has = lines["eic"] != ""
    ordered = lines[has].sort_values(["_fill", "_sheet"], ascending=[False, True], kind="stable")
    keep_idx = ordered.drop_duplicates("eic").index
    other = lines[has & ~lines.index.isin(keep_idx)].groupby("eic")["tso"].agg(lambda s: ", ".join(sorted(set(s))))
    kept = lines[~has | lines.index.isin(keep_idx)].copy().sort_index()
    for i, r in kept.iterrows():
        if r["eic"] in other.index and other[r["eic"]] != r["tso"]:
            kept.at[i, "jao_comment"] = (r["jao_comment"] + "; also listed by " + other[r["eic"]]).strip("; ")
    return kept.drop(columns=["_fill", "_sheet"]).reset_index(drop=True)


def _strip_transformer_name(name: str) -> str:
    t = re.sub(r"\b\d+\s*/\s*\d+\s*(kv)?\b", " ", str(name), flags=re.I)
    t = re.sub(r"-[A-Za-z]\d+$", "", t.strip())
    toks = [x for x in re.split(r"\s+", t) if x and x.upper() not in ("TR", "PST", "TRAFO", "TRANSFORMER", "KV") and not re.search(r"\d", x)]
    return " ".join(toks).strip()


def read_transformers(path: str, tso_country: dict, known_substations: dict | None = None) -> pd.DataFrame:
    """Transformers and phase shifters; the substation is the longest known substation name inside the transformer name (otherwise the cleaned name)."""
    raw = pd.read_excel(path, sheet_name="Transformers", header=None)
    h = _find_header(raw, ("full name",))
    pos = _cols(raw.iloc[h].tolist())
    d = raw.iloc[h + 1:].reset_index(drop=True)
    d = d[d.iloc[:, 0].notna()]
    g = lambda *p: d.iloc[:, _pick(pos, *p)]
    out = pd.DataFrame({"element_name": g("full name").astype(str).str.strip(), "eic": g("eic_code").astype(str).str.strip().replace({"nan": ""}), "tso": g("tso").map(tso_name),
                        "imax_min_a": _num(g("min")), "imax_max_a": _num(g("max")), "imax_fixed_a": _num(g("fixed")), "u_primary_kv": _num(g("primary")), "u_secondary_kv": _num(g("secondary")),
                        "r_ohm": _num(g("resistance")), "x_ohm": _num(g("reactance")), "b_us": _num(g("susceptance")), "g_us": _num(g("conductance")),
                        "rao_steps": g("taps").astype(str).replace({"nan": ""}), "angle_deg": _num(g("theta")), "sym_asym": g("symmetrical").astype(str).replace({"nan": ""}),
                        "du_phase_pct": _num(g("phase regulation")), "du_angle_pct": _num(g("angle regulation")), "jao_comment": g("comment").astype(str).replace({"nan": ""}).str.strip()})
    names = known_substations or {}
    keys = sorted(names, key=len, reverse=True)
    subs = []
    for nm in out["element_name"]:
        nk = node_key(nm)
        hit = next((k for k in keys if len(k) >= 4 and k in nk), None)
        subs.append(names[hit] if hit else _strip_transformer_name(nm))
    out["substation"] = subs
    out["type"] = ["PST" if (re.search(r"\bPST", str(n), re.I) or str(sy).strip().casefold() in ("symmetrical", "asymmetrical")) else "Transformer"
                   for n, sy in zip(out["element_name"], out["sym_asym"])]
    out["country"] = out["tso"].map(tso_country).fillna("")
    out["source"] = "SGM"
    has = out["eic"] != ""
    return pd.concat([out[has].drop_duplicates("eic"), out[~has]]).sort_index().reset_index(drop=True)


def read_tso_coordinates(path: str, source: str) -> pd.DataFrame:
    """Substation names with longitude/latitude from a TSO workbook (sheets Lines and Tielines with columns Full_name, Longitude, Latitude for both ends)."""
    rows = {}
    for sheet in ("Lines", "Tielines"):
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        h = _find_header(raw, ("ne_name",))
        pos = _cols(raw.iloc[h].tolist())
        d = raw.iloc[h + 1:].reset_index(drop=True)
        d = d[d.iloc[:, 0].notna()]
        for end in (0, 1):
            ni, lo, la = _pick(pos, "full_name", nth=end), _pick(pos, "longitude", nth=end), _pick(pos, "latitude", nth=end)
            if None in (ni, lo, la):
                continue
            for n, x, y in zip(d.iloc[:, ni], _num(d.iloc[:, lo]), _num(d.iloc[:, la])):
                if isinstance(n, str) and n.strip() and np.isfinite(x) and np.isfinite(y):
                    rows.setdefault(n.strip(), (round(float(y), 5), round(float(x), 5)))
    return pd.DataFrame([(n, la, lo, source) for n, (la, lo) in rows.items()], columns=["substation", "latitude", "longitude", "source"])
