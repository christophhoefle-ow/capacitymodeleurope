"""Lage der Umspannwerke schätzen: aus Leitungslängen und Netztopologie, mit einigen Ankerpunkten.

Warum: Das JAO-Netzmodell enthält keine Koordinaten. Für eine Karte wird die Lage deshalb geschätzt:
  1. Entfernung zweier Knoten = kürzester Weg durch das Netz (Leitungslängen in km), mal Faktor alpha (Wege sind länger als Luftlinie).
  2. Aus diesen Entfernungen entsteht per Stress-Minimierung (Kamada-Kawai) eine ebene Anordnung.
  3. Bekannte Orte (Anker, Lat/Lon) halten die Anordnung in der richtigen Lage, Drehung und Größe.
Das Ergebnis ist eine NÄHERUNG (Kartenabweichung typischerweise zweistellig in km), kein Ersatz für echte Koordinaten
(z. B. aus OpenStreetMap). Echte Werte in data/manual/koordinaten_manuell.csv überschreiben die Schätzung.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, shortest_path

LAT0, LON0 = 51.0, 10.4
KM_PER_DEG = 111.2
X_PER_KM_DEFAULT = 0.257          # Median Reaktanz je km (Ω/km) in den Netzdaten, zum Ergänzen fehlender Längen


def to_km(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return np.column_stack([(lon - LON0) * KM_PER_DEG * np.cos(np.radians(LAT0)), (lat - LAT0) * KM_PER_DEG])


def to_latlon(xy):
    xy = np.asarray(xy, float)
    return xy[:, 1] / KM_PER_DEG + LAT0, xy[:, 0] / (KM_PER_DEG * np.cos(np.radians(LAT0))) + LON0


def edge_table(lines: pd.DataFrame) -> pd.DataFrame:
    """Kanten (u, v, km) aus den Stromkreisen; fehlende Längen aus der Reaktanz ergänzt, Parallelkreise = kürzeste Länge."""
    ln = pd.to_numeric(lines["length_km"].replace("", np.nan))
    x = pd.to_numeric(lines["x_ohm"].replace("", np.nan)).abs()
    km = ln.where(ln > 0.3, x / X_PER_KM_DEFAULT).fillna(ln.median()).clip(lower=0.3)
    e = pd.DataFrame({"u": lines["substation_1"], "v": lines["substation_2"], "km": km})
    e = e[(e["u"] != "") & (e["v"] != "") & (e["u"] != e["v"])]
    a, b = np.minimum(e["u"], e["v"]), np.maximum(e["u"], e["v"])
    return e.assign(u=a, v=b).groupby(["u", "v"], as_index=False)["km"].min()


def distance_matrix(nodes: list[str], edges: pd.DataFrame):
    idx = {n: i for i, n in enumerate(nodes)}
    r = [idx[u] for u in edges["u"]]
    c = [idx[v] for v in edges["v"]]
    g = coo_matrix((edges["km"].values, (r, c)), shape=(len(nodes),) * 2)
    return shortest_path(g, method="D", directed=False)


def _similarity(src, dst):
    """Ähnlichkeitstransformation (Drehung/Spiegelung, Maßstab, Verschiebung) src -> dst nach kleinsten Quadraten."""
    ms, md = src.mean(0), dst.mean(0)
    s0, d0 = src - ms, dst - md
    u, sv, vt = np.linalg.svd(d0.T @ s0)
    r = u @ vt                                   # Spiegelung ist erlaubt (MDS kennt keine Orientierung)
    scale = sv.sum() / (s0 ** 2).sum()
    return lambda p: scale * (p - ms) @ r.T + md


def estimate_positions(nodes, edges, anchors: dict[str, tuple[float, float]], maxiter=400, w_exp=2.0):
    """Schätzt (lat, lon) je Knoten. Rückgabe: DataFrame(Umspannwerk, Breitengrad, Laengengrad, Anker) nur für den Hauptverbund."""
    D = distance_matrix(nodes, edges)
    n = len(nodes)
    ncomp, lab = connected_components(coo_matrix(np.isfinite(D) & (D > 0)), directed=False)
    main = np.where(lab == np.bincount(lab).argmax())[0]
    pos = {int(g): k for k, g in enumerate(main)}
    Dm = D[np.ix_(main, main)]
    a_idx = np.array([pos[nodes.index(a)] for a in anchors if a in nodes and nodes.index(a) in pos])
    a_names = [a for a in anchors if a in nodes and nodes.index(a) in pos]
    a_xy = to_km([anchors[a][0] for a in a_names], [anchors[a][1] for a in a_names])

    # Maßstab Weg -> Luftlinie aus den Ankern
    iu = np.triu_indices(len(a_idx), 1)
    dE = np.linalg.norm(a_xy[iu[0]] - a_xy[iu[1]], axis=1)
    dP = Dm[a_idx[iu[0]], a_idx[iu[1]]]
    ok = dP > 30
    alpha = float((dE[ok] * dP[ok]).sum() / (dP[ok] ** 2).sum())

    # Startlage: klassische MDS, dann an die Anker angepasst
    T = alpha * Dm
    J = np.eye(len(main)) - 1.0 / len(main)
    w, v = np.linalg.eigh(-0.5 * J @ (T ** 2) @ J)
    X0 = v[:, -2:] * np.sqrt(np.maximum(w[-2:], 0))
    X = _similarity(X0[a_idx], a_xy)(X0)
    X_init = X.copy()

    # Verfeinerung: Stress minimieren, Anker bleiben fest
    W = 1.0 / np.maximum(T, 1.0) ** w_exp
    np.fill_diagonal(W, 0)
    free = np.setdiff1d(np.arange(len(main)), a_idx)
    X[a_idx] = a_xy

    def fun(flat):
        Y = X.copy()
        Y[free] = flat.reshape(-1, 2)
        diff = Y[:, None, :] - Y[None, :, :]
        d = np.sqrt((diff ** 2).sum(-1)) + 1e-9
        s = 0.5 * (W * (d - T) ** 2).sum()
        g = 2 * (W * (d - T) / d)[:, :, None] * diff
        return s, g.sum(1)[free].ravel()

    def project(X):
        """Physikalische Schranke: Luftlinie <= Leitungsweg. Verletzte Knoten werden auf den Rand der Schranke zurückgesetzt."""
        bound_all = Dm[:, a_idx]
        for _ in range(80):
            moved = 0
            for i in free:
                dv = X[i] - X[a_idx]
                dist = np.linalg.norm(dv, axis=1) + 1e-9
                over = dist - bound_all[i]
                k = int(np.argmax(over))
                if over[k] > 1e-6:
                    X[i] = X[a_idx[k]] + dv[k] * (bound_all[i][k] / dist[k])
                    moved += 1
            if moved == 0:
                break
        return X

    for _round in range(3):
        res = minimize(fun, X[free].ravel(), jac=True, method="L-BFGS-B", options={"maxiter": maxiter if _round == 0 else 120})
        X[free] = res.x.reshape(-1, 2)
        X = project(X)
    lat, lon = to_latlon(X)
    out = pd.DataFrame({"substation": [nodes[g] for g in main], "latitude": lat, "longitude": lon})
    out["anchor"] = [nodes[g] in a_names for g in main]
    dA = Dm[:, a_idx].min(axis=1)
    out["anchor_distance_km"] = np.where(out["anchor"], 0.0, dA).round(0)
    return out, alpha, to_latlon(X_init)


def cross_validate(nodes, edges, anchors, folds=5, seed=7, **kw):
    """Anker abwechselnd weglassen, schätzen, Abweichung in km messen."""
    rng = np.random.default_rng(seed)
    names = [a for a in anchors if a in nodes]
    rng.shuffle(names)
    rows = []
    for k in range(folds):
        test = names[k::folds]
        train = {a: anchors[a] for a in names if a not in test}
        est, alpha, (ilat, ilon) = estimate_positions(nodes, edges, train, **kw)
        e = est.set_index("substation")
        D = distance_matrix(nodes, edges)
        tr_idx = [nodes.index(a) for a in train if a in nodes]
        for a in test:
            if a in e.index:
                t = to_km([anchors[a][0]], [anchors[a][1]])[0]
                p = to_km([e.loc[a, "latitude"]], [e.loc[a, "longitude"]])[0]
                rows.append((a, float(np.linalg.norm(t - p)), float(D[nodes.index(a), tr_idx].min())))
    return pd.DataFrame(rows, columns=["substation", "error_km", "anchor_gap_km"])


def clean_anchors(nodes, edges, anchors, tol=1.2, slack_km=15.0):
    """Ankerpunkte entfernen, die zum Netz nicht passen (falsche Koordinate oder Namensverwechslung).

    Prinzip: Luftlinie zwischen zwei Knoten <= Leitungsweg. Ein Anker, der diese Schranke gegenüber mehreren anderen Ankern
    verletzt, wird entfernt (jeweils der mit den meisten Verstößen), bis keine Verstöße mehr bleiben.
    Rückgabe: (bereinigte Anker, Liste der entfernten Anker mit Zahl der Verstöße).
    """
    D = distance_matrix(nodes, edges)
    names = [a for a in anchors if a in nodes]
    idx = [nodes.index(a) for a in names]
    xy = to_km([anchors[a][0] for a in names], [anchors[a][1] for a in names])
    E = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
    Dp = D[np.ix_(idx, idx)]
    bad = np.isfinite(Dp) & (E > tol * Dp + slack_km)
    np.fill_diagonal(bad, False)
    alive = np.ones(len(names), bool)
    removed = []
    while True:
        counts = (bad & alive[None, :] & alive[:, None]).sum(1)
        k = int(np.argmax(counts))
        if counts[k] == 0:
            break
        alive[k] = False
        removed.append((names[k], int(counts[k])))
    return {a: anchors[a] for a, ok in zip(names, alive) if ok}, removed


def find_ambiguous_nodes(nodes, edges, anchors, tol=1.25, slack_km=25.0):
    """Knoten, die sich nicht als EIN Standort verhalten (gleicher Name bei verschiedenen Betreibern?).

    Test: Zwei Nachbarn a, b eines Knotens v mit bekannter Lage dürfen in Luftlinie nicht weiter auseinander liegen als der
    Leitungsweg a-v-b (Dreiecksungleichung). Wird das deutlich verletzt, verbindet der Name vermutlich zwei verschiedene Standorte.
    """
    xy = {a: to_km([anchors[a][0]], [anchors[a][1]])[0] for a in anchors if a in nodes}
    nb = {}
    for r in edges.itertuples():
        nb.setdefault(r.u, []).append((r.v, r.km))
        nb.setdefault(r.v, []).append((r.u, r.km))
    out = []
    for v, lst in nb.items():
        known = [(a, km) for a, km in lst if a in xy]
        worst = 0.0
        for i in range(len(known)):
            for j in range(i + 1, len(known)):
                (a, ka), (b, kb) = known[i], known[j]
                over = float(np.linalg.norm(xy[a] - xy[b])) - tol * (ka + kb) - slack_km
                worst = max(worst, over)
        if worst > 0:
            out.append((v, round(worst)))
    return sorted(out, key=lambda t: -t[1])
