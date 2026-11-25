"""Tests der Lageschätzung an einem Gitternetz mit bekannter Lage."""
import numpy as np
import pandas as pd

from capmodel import geo


def _grid(n=7, spacing_km=30.0):
    """n x n Gitter mit bekannter Lage; Leitungslänge = 1,1 x Luftlinie."""
    nodes, pos = [], {}
    for i in range(n):
        for j in range(n):
            name = f"K{i}{j}"
            nodes.append(name)
            x, y = j * spacing_km, i * spacing_km
            pos[name] = (51.0 + y / geo.KM_PER_DEG, 10.4 + x / (geo.KM_PER_DEG * np.cos(np.radians(51.0))))
    rows = []
    for i in range(n):
        for j in range(n):
            if j + 1 < n:
                rows.append((f"K{i}{j}", f"K{i}{j+1}", spacing_km * 1.1))
            if i + 1 < n:
                rows.append((f"K{i}{j}", f"K{i+1}{j}", spacing_km * 1.1))
    return nodes, pos, pd.DataFrame(rows, columns=["u", "v", "km"])


def test_positions_are_recovered_from_topology_and_few_anchors():
    nodes, pos, edges = _grid()
    anchors = {n: pos[n] for n in ("K00", "K06", "K60", "K66", "K33", "K03", "K30", "K36", "K63")}
    est, alpha, _ = geo.estimate_positions(nodes, edges, anchors)
    e = est.set_index("substation")
    err = []
    for n in nodes:
        if n not in anchors:
            t = geo.to_km([pos[n][0]], [pos[n][1]])[0]
            p = geo.to_km([e.loc[n, "latitude"]], [e.loc[n, "longitude"]])[0]
            err.append(np.linalg.norm(t - p))
    assert np.median(err) < 12 and max(err) < 40, (np.median(err), max(err))   # Gitterabstand 30 km
    assert 0.6 < alpha < 1.0                                                   # Gitterwege sind Manhattan-Wege, daher unter 1/1,1


def test_wrong_anchor_is_removed():
    nodes, pos, edges = _grid()
    anchors = {n: pos[n] for n in ("K00", "K06", "K60", "K66", "K33", "K03", "K30", "K36", "K63", "K11", "K15")}
    anchors["K11"] = pos["K55"]                                    # falsch gesetzt: Namensverwechslung
    clean, removed = geo.clean_anchors(nodes, edges, anchors)
    assert "K11" not in clean and removed[0][0] == "K11" and len(clean) == len(anchors) - 1


def test_node_that_joins_two_distant_sites_is_flagged():
    # 'X' hat zwei kurze Leitungen zu Knoten, die 400 km auseinander liegen: kann nicht ein Standort sein
    edges = pd.DataFrame([("A", "X", 10.0), ("B", "X", 10.0)], columns=["u", "v", "km"])
    anchors = {"A": (51.0, 10.0), "B": (54.6, 10.0)}               # ca. 400 km Abstand
    nodes = ["A", "B", "X"]
    assert [n for n, _ in geo.find_ambiguous_nodes(nodes, edges, anchors)] == ["X"]
    assert geo.find_ambiguous_nodes(nodes, pd.DataFrame([("A", "X", 10.0), ("B", "X", 300.0)], columns=["u", "v", "km"]), anchors) == []
