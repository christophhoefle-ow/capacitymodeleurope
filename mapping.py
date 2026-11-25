"""Matching of JAO network elements with the master data and monthly aggregation.

Matching happens here in the script and NOT in Excel. Excel then only needs one unique key per line or transformer
(rule: see normalize.element_key).

Matching rules (in this order):
  0. manual match (data/manual/alias_jao_sgm.csv, checked by humans)                -> match 'alias'
  1. EIC of the SGM element = EIC in the JAO data                                    -> match 'EIC'
  2. otherwise: name of the SGM element = one of the JAO names (normalised,
     case-insensitive)                                                               -> match 'name'
  3. same two substations and voltage class (for elements whose EIC and name differ between
     JAO and the model; parallel systems are assigned one by one)                    -> match 'substations'
  4. JAO elements without a hit stay with their own key and become master rows       -> 'unmatched'
     of their own (source 'JAO').

If several JAO rows hit the same SGM element (e.g. both TSOs report the same tie-line under different names),
the WORST value of each figure counts.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from .normalize import element_key, name_key, norm_eic, norm_text
from .sgm import base_key, node_key, pretty_name

MONTHLY_COLUMNS = ["month", "key", "match", "tso", "element", "eic", "fmax_mw", "hours", "util_sum", "util_max",
                   "hours_high", "hours_overload", "hours_binding"]
LINE_COLUMNS = ["element_name", "eic", "tso", "substation_1", "substation_2", "voltage_kv",
                "imax_period_1_a", "imax_period_2_a", "imax_period_3_a", "imax_period_4_a", "imax_period_5_a", "imax_period_6_a",
                "imax_fixed_a", "dlr_min_a", "dlr_max_a", "r_ohm", "x_ohm", "b_us", "length_km", "jao_comment", "type",
                "country", "neighbor_country", "source", "country_1", "country_2"]
TRAFO_COLUMNS = ["element_name", "eic", "tso", "imax_min_a", "imax_max_a", "imax_fixed_a", "u_primary_kv", "u_secondary_kv",
                 "r_ohm", "x_ohm", "b_us", "g_us", "rao_steps", "angle_deg", "sym_asym", "du_phase_pct", "du_angle_pct",
                 "jao_comment", "substation", "type", "country", "source"]
TYPE_LINE, TYPE_TIE, TYPE_TSO_TIE = "Line", "Tie-line", "Line between German TSOs"
TYPE_TRAFO, TYPE_PST = "Transformer", "PST"


# --------------------------------------------------------------------------- matching
def _vclass(kv) -> str:
    try:
        v = float(kv)
    except (TypeError, ValueError):
        return ""
    return "380" if v >= 300 else ("220" if v >= 150 else "")


def sgm_elements(lines: pd.DataFrame, trafos: pd.DataFrame) -> pd.DataFrame:
    """All lines and transformers of the master data as a table (sgm_key, eic, name, kind, pair, vclass); pair = the two substations of a line (spelling independent)."""
    parts = []
    for df, kind in ((lines, "line"), (trafos, "transformer")):
        if df is None or df.empty:
            continue
        t = pd.DataFrame({"eic": df["eic"].map(norm_eic), "name": df["element_name"].map(norm_text)})
        t["sgm_key"] = [element_key(e, n) for e, n in zip(t["eic"], t["name"])]
        t["kind"] = kind
        if kind == "line" and "substation_1" in df.columns:
            t["pair"] = ["|".join(sorted((base_key(a), base_key(b)))) if a and b else "" for a, b in zip(df["substation_1"], df["substation_2"])]
            t["vclass"] = [_vclass(v) for v in df["voltage_kv"]] if "voltage_kv" in df.columns else ""
        else:
            t["pair"], t["vclass"] = "", ""
        parts.append(t)
    if not parts:
        return pd.DataFrame(columns=["sgm_key", "eic", "name", "kind", "pair", "vclass"])
    return pd.concat(parts, ignore_index=True)


def build_mapping(daily: pd.DataFrame, sgm: pd.DataFrame, alias: pd.DataFrame | None = None) -> pd.DataFrame:
    """Mapping table (key, jao_key, match). `alias` (optional) has the columns jao_key and sgm_key."""
    jao = daily.drop_duplicates("key")[["key", "eic", "names"]]
    jao_eics = set(jao.loc[jao["eic"] != "", "key"])
    jao_keys = set(jao["key"])
    name_index: dict[str, set[str]] = {}
    for jk, names in zip(jao["key"], jao["names"]):
        for n in str(names).split(" | "):
            if n:
                name_index.setdefault(name_key(n), set()).add(jk)
    rows, claimed, done = [], set(), set()
    sgm_keys = set(sgm["sgm_key"])
    if alias is not None and not alias.empty:
        for jk, sk in zip(alias["jao_key"], alias["sgm_key"]):
            if jk in jao_keys and sk in sgm_keys:
                rows.append((sk, jk, "alias"))
                claimed.add(jk)
                done.add(sk)
    for _, s in sgm.iterrows():
        if s["sgm_key"] in done:
            continue
        if s["eic"] and s["eic"] in jao_eics:
            rows.append((s["sgm_key"], s["eic"], "EIC"))
            claimed.add(s["eic"])
        else:
            for jk in sorted(name_index.get(name_key(s["name"]), set())):
                rows.append((s["sgm_key"], jk, "name"))
                claimed.add(jk)
    if "pair" in sgm.columns and "substation_from" in daily.columns:
        attrs = daily.sort_values("day").drop_duplicates("key", keep="last").set_index("key")
        free: dict[tuple, list] = {}
        taken = {r[0] for r in rows}
        for _, srow in sgm[(sgm["kind"] == "line") & (sgm["pair"] != "") & ~sgm["sgm_key"].isin(taken)].iterrows():
            free.setdefault((srow["pair"], srow["vclass"]), []).append(srow["sgm_key"])
        for jk in sorted(k for k in jao["key"] if k not in claimed):
            a = attrs.loc[jk]
            if a["element_type"] in ("Transformer", "PST") or not a["substation_from"] or not a["substation_to"]:
                continue
            cand = free.get(("|".join(sorted((node_key(a["substation_from"]), node_key(a["substation_to"])))), _vclass(a["voltage_kv"])))
            if cand:
                rows.append((cand.pop(0), jk, "substations"))
                claimed.add(jk)
    for jk in jao["key"]:
        if jk not in claimed:
            rows.append((jk, jk, "unmatched"))
    return pd.DataFrame(rows, columns=["key", "jao_key", "match"]).drop_duplicates()


def monthly_from_daily(daily: pd.DataFrame, sgm: pd.DataFrame, alias: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily files -> monthly table per Excel key (delivery to sheet D_Utilization)."""
    if daily.empty:
        return pd.DataFrame(columns=MONTHLY_COLUMNS)
    mapping = build_mapping(daily, sgm, alias)
    m = daily.rename(columns={"key": "jao_key"}).merge(mapping, on="jao_key", how="inner")
    # a) several JAO rows -> one SGM element: worst value per day
    day = m.sort_values(["day", "key", "jao_key"]).groupby(["day", "key"], as_index=False).agg(
        match=("match", "first"), tso=("tso", "first"), element=("element", "first"), eic=("eic", "first"),
        fmax_mw=("fmax_mw", "min"), hours=("hours", "max"), util_sum=("util_sum", "max"), util_max=("util_max", "max"),
        hours_high=("hours_high", "max"), hours_overload=("hours_overload", "max"), hours_binding=("hours_binding", "max"))
    # b) days -> months (add the sums, take the maximum)
    day["month"] = day["day"].str.slice(0, 7) + "-01"
    mon = day.groupby(["month", "key"], as_index=False).agg(
        match=("match", "first"), tso=("tso", "first"), element=("element", "first"), eic=("eic", "first"),
        fmax_mw=("fmax_mw", "min"), hours=("hours", "sum"), util_sum=("util_sum", "sum"), util_max=("util_max", "max"),
        hours_high=("hours_high", "sum"), hours_overload=("hours_overload", "sum"), hours_binding=("hours_binding", "sum"))
    mon["util_sum"] = mon["util_sum"].round(6)
    mon["util_max"] = mon["util_max"].round(6)
    return mon[MONTHLY_COLUMNS].sort_values(["month", "key"]).reset_index(drop=True)


# --------------------------------------------------------------------------- master data
def sgm_master(lines_raw: pd.DataFrame, trafos_raw: pd.DataFrame):
    """Master rows from the static SGM extracts (one file per country or TSO group); adds the country of each end of a line.

    Rule for the ends: a node that appears in a domestic line or a transformer belongs to the country of that element;
    a node that only appears in tie-lines belongs to the neighbouring country of that tie-line.
    """
    lines, trafos = lines_raw.copy(), trafos_raw.copy()
    tie = lines["type"] == TYPE_TIE
    node_country: dict[str, str] = {}
    for s1, s2, c in zip(lines.loc[~tie, "substation_1"], lines.loc[~tie, "substation_2"], lines.loc[~tie, "country"]):
        node_country.setdefault(s1, c)
        node_country.setdefault(s2, c)
    for sub, c in zip(trafos["substation"], trafos["country"]):
        node_country.setdefault(sub, c)
    for i in (1, 2):
        lines[f"country_{i}"] = [node_country.get(sub) or (nb if t else c) for sub, t, nb, c in
                                 zip(lines[f"substation_{i}"], tie, lines["neighbor_country"], lines["country"])]
    return lines[LINE_COLUMNS], trafos[TRAFO_COLUMNS]


def apply_substation_aliases(lines: pd.DataFrame, trafos: pd.DataFrame, aliases: pd.DataFrame | None):
    """Merge typing variants of a substation name (data/manual/substation_aliases.csv: alias, substation, note).

    The Static Grid Model and the JAO data contain a few misspellings ('Herbentingen' for 'Herbertingen'). Without the alias each
    variant is a node of its own: the line hangs in the air on the map and the substation loses one of its elements.
    Only add an alias when both names clearly mean the same site; returns (lines, trafos, number of replaced cells).
    """
    lines, trafos = lines.copy(), trafos.copy()
    if aliases is None or aliases.empty:
        return lines, trafos, 0
    amap = {node_key(a): t for a, t in zip(aliases["alias"], aliases["substation"]) if a and t}
    n = 0
    for df, cols in ((lines, ("substation_1", "substation_2")), (trafos, ("substation",))):
        for c in cols:
            new = [amap.get(node_key(v), v) if v else v for v in df[c]]
            n += sum(a != b for a, b in zip(new, df[c]))
            df[c] = new
    return lines, trafos, n


def split_homonyms(lines: pd.DataFrame, trafos: pd.DataFrame):
    """One node per site: a substation name used for different sites in different countries gets the country as suffix.

    Example: 'St. Peter' is a substation of APG in Upper Austria and of Amprion near Duesseldorf. Without the split both would be ONE node,
    with lines of 570 km between the Rhineland and Austria on the map and wrong counts in the sheet Substations.
    Rule: a name key is a homonym if DOMESTIC elements (lines that are not cross-border tie-lines, transformers) use it in more than one country.
    A real border substation has domestic elements in one country only and is therefore never split.
    Ends of cross-border tie-lines: the country of the pair (own, neighbour) that knows the name; if both do, the country the other end is NOT in.
    Returns (lines, trafos, report) with report = [(name, country, number of elements)].
    """
    lines, trafos = lines.copy(), trafos.copy()
    dom: dict[str, Counter] = {}
    cross = lines["type"] == TYPE_TIE
    for i in (1, 2):
        for sub, c in zip(lines.loc[~cross, f"substation_{i}"], lines.loc[~cross, "country"]):
            if sub and c:
                dom.setdefault(node_key(sub), Counter())[c] += 1
    for sub, c in zip(trafos["substation"], trafos["country"]):
        if sub and c:
            dom.setdefault(node_key(sub), Counter())[c] += 1
    hom = {k: v for k, v in dom.items() if len(v) > 1}
    if not hom:
        return lines, trafos, []
    used: Counter = Counter()

    def tag(name, cc):
        used[(pretty_name(name), cc)] += 1
        return f"{pretty_name(name)} ({cc})"             # pretty_name first: 'St. Peter 2' (busbar 2) and 'St. Peter' are the same site

    for idx, r in lines.iterrows():
        keys = [node_key(r["substation_1"]), node_key(r["substation_2"])]
        for i in (0, 1):
            if keys[i] not in hom:
                continue
            if r["type"] != TYPE_TIE:
                cc = r["country"]
            else:
                cands = [c for c in dict.fromkeys((r["country"], r["neighbor_country"])) if c in hom[keys[i]]]
                other = r[f"country_{2 - i}"] if keys[1 - i] not in hom else ""
                cc = cands[0] if len(cands) == 1 else (next((c for c in cands if c != other), r["country"]) if cands else hom[keys[i]].most_common(1)[0][0])
            lines.at[idx, f"substation_{i + 1}"] = tag(r[f"substation_{i + 1}"], cc)
            lines.at[idx, f"country_{i + 1}"] = cc
    for idx, r in trafos.iterrows():
        if node_key(r["substation"]) in hom:
            cc = r["country"] or hom[node_key(r["substation"])].most_common(1)[0][0]
            trafos.at[idx, "substation"] = tag(r["substation"], cc)
    return lines, trafos, sorted((n, c, k) for (n, c), k in used.items())


def latest_attributes(daily: pd.DataFrame) -> pd.DataFrame:
    """Latest attributes (last day with data) per JAO key."""
    return daily.sort_values(["day", "key"]).drop_duplicates("key", keep="last").reset_index(drop=True)


def jao_master(attrs: pd.DataFrame):
    """Master rows for JAO elements without a partner in the SGM extract (source 'JAO')."""
    lines, trafos = [], []
    for r in attrs.itertuples(index=False):
        base = dict(element_name=r.element, eic=r.eic, tso=r.tso, country=r.country, source="JAO")
        if r.element_type in ("Transformer", "PST"):
            trafos.append({**base, "u_primary_kv": r.voltage_kv, "imax_fixed_a": r.imax_a, "substation": r.substation_from,
                           "type": TYPE_PST if r.element_type == "PST" else TYPE_TRAFO})
            continue
        cross = bool(r.hub_from) and bool(r.hub_to) and r.hub_from != r.hub_to
        neighbor = ""
        if cross:
            neighbor = r.hub_to if r.hub_from == r.country else r.hub_from
        lines.append({**base, "substation_1": r.substation_from, "substation_2": r.substation_to, "voltage_kv": r.voltage_kv,
                      "imax_fixed_a": r.imax_a, "type": TYPE_TIE if cross else TYPE_LINE, "neighbor_country": neighbor,
                      "country_1": r.hub_from or r.country, "country_2": r.hub_to or r.country})
    return (pd.DataFrame(lines).reindex(columns=LINE_COLUMNS).fillna(""), pd.DataFrame(trafos).reindex(columns=TRAFO_COLUMNS).fillna(""))


def canonical_names(lines: pd.DataFrame, trafos: pd.DataFrame) -> dict[str, str]:
    """Display name per substation identity (spelling of the first occurrence wins, SGM rows come first)."""
    names: dict[str, str] = {}
    for col in ("substation_1", "substation_2"):
        for n in lines[col]:
            if n:
                names.setdefault(node_key(n), pretty_name(n))
    for n in trafos["substation"]:
        if n:
            names.setdefault(node_key(n), pretty_name(n))
    return names


def apply_canonical(lines: pd.DataFrame, trafos: pd.DataFrame, canon: dict[str, str]):
    """Write the display names into all rows so that 'Roehrsdorf' and 'Röhrsdorf' are one substation."""
    lines, trafos = lines.copy(), trafos.copy()
    fix = lambda n: canon.get(node_key(n), n) if n else n
    for col in ("substation_1", "substation_2"):
        lines[col] = lines[col].map(fix)
    trafos["substation"] = trafos["substation"].map(fix)
    return lines, trafos


def derive_substations(lines: pd.DataFrame, trafos: pd.DataFrame) -> pd.DataFrame:
    """List of all substations / nodes with their country (identity by spelling-independent key, most frequent country wins)."""
    recs = []
    for i in (1, 2):
        recs += list(zip(lines[f"substation_{i}"].map(norm_text), lines[f"country_{i}"]))
    recs += list(zip(trafos["substation"].map(norm_text), trafos["country"]))
    seen: dict[str, Counter] = {}
    display: dict[str, str] = {}
    for s, c in recs:
        if s:
            k = node_key(s)
            display.setdefault(k, pretty_name(s))
            seen.setdefault(k, Counter())[c or ""] += 1
    rows = []
    for k, cnt in seen.items():
        named = [(n, c) for c, n in cnt.items() if c]
        rows.append((display[k], max(named)[1] if named else ""))
    return pd.DataFrame(sorted(rows, key=lambda x: x[0].casefold()), columns=["substation", "country"])
