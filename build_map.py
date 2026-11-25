#!/usr/bin/env python3
"""Map outside Excel: the network on a real background (OpenStreetMap) for the browser, and as GeoJSON.

  python scripts/build_map.py --html build/network_map.html --geojson data/processed/network_map.geojson
network_map.html  one self-contained page (data inside); the background tiles and the map library (Leaflet) are loaded from the internet when the page is opened.
network_map.geojson  the same content as data; GitHub shows a .geojson file as an interactive map right in the repository.
Lights follow the rules of the Excel model with its default parameters (src/capmodel/lights.py). Lines are straight connections between the substations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

import _common as common
from capmodel import lights

COLOR = {"Red": "#C53532", "Amber": "#F4B400", "Green": "#6ABF30", "Grey": "#B9B6B1"}
LINE_COLOR = {"Bottleneck": "#C53532", "Highly loaded": "#F4B400", "Uncritical": "#6f8f5a", "Too little data": "#9E9B96", "No data": "#B0ADA8"}
PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Core capacity model: network map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 html,body{height:100%;margin:0;font-family:Arial,Helvetica,sans-serif;color:#000F47}
 #map{position:absolute;top:54px;bottom:0;left:0;right:0}
 header{height:54px;box-sizing:border-box;padding:8px 14px;border-bottom:1px solid #D1CEC9;background:#fff}
 header b{font-family:Georgia,serif;font-size:17px} header span{font-size:12px;color:#595959;display:block;margin-top:2px}
 .legend{background:#fff;padding:8px 10px;border:1px solid #D1CEC9;font-size:12px;line-height:18px;color:#000F47}
 .legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px} .legend u{display:inline-block;width:14px;height:3px;margin:0 6px 3px 0;text-decoration:none}
 #offline{display:none;padding:24px;font-size:14px}
</style></head><body>
<header><b>Core capacity model | network map</b><span>__STATUS__</span></header>
<div id="map"></div>
<div id="offline">The map needs an internet connection: the background (OpenStreetMap) and the map library are loaded when the page is opened.</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var POINTS = __POINTS__;
var LINES = __LINES__;
var COLOR = __COLOR__;
var LINE_COLOR = __LINE_COLOR__;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
if (typeof L === "undefined") {
  document.getElementById("map").style.display = "none";
  document.getElementById("offline").style.display = "block";
} else {
  var map = L.map("map", {preferCanvas: true}).setView([49.5, 11.5], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 14, attribution: "&copy; OpenStreetMap contributors | network: JAO Core Static Grid Model | utilization: JAO Publication Tool"}).addTo(map);
  var layers = {"Lines without data": L.layerGroup(), "Lines with data": L.layerGroup(), "Substations without data": L.layerGroup(), "Substations with a light": L.layerGroup()};
  LINES.forEach(function(d){
    var hot = d[4] === "Bottleneck" || d[4] === "Highly loaded", data = d[4] !== "No data";
    L.polyline([[d[0], d[1]], [d[2], d[3]]], {color: LINE_COLOR[d[4]], weight: hot ? 3.5 : (data ? 2 : 1), opacity: data ? 0.9 : 0.55})
      .bindPopup("<b>" + esc(d[5]) + "</b><br>" + esc(d[6]) + " kV, " + esc(d[8]) + "<br>Status: " + esc(d[4]) + (d[7] === null ? "" : "<br>Highest utilization: " + d[7] + " %"))
      .addTo(layers[data ? "Lines with data" : "Lines without data"]);
  });
  POINTS.forEach(function(d){
    var grey = d[3] === "Grey";
    L.circleMarker([d[1], d[2]], {radius: grey ? 3 : 5.5, color: "#fff", weight: 1, fillColor: COLOR[d[3]], fillOpacity: 1})
      .bindPopup("<b>" + esc(d[0]) + "</b> (" + esc(d[4]) + ")<br>Light: " + esc(d[3]) + (d[5] === null ? "" : "<br>Highest utilization: " + d[5] + " %") + "<br>" + esc(d[6]) + "<br><small>Location: " + esc(d[7]) + "</small>")
      .addTo(layers[grey ? "Substations without data" : "Substations with a light"]);
  });
  ["Lines without data", "Lines with data", "Substations with a light"].forEach(function(k){ layers[k].addTo(map); });
  L.control.layers(null, layers, {collapsed: false}).addTo(map);
  var legend = L.control({position: "bottomleft"});
  legend.onAdd = function(){
    var div = L.DomUtil.create("div", "legend");
    div.innerHTML = "<i style='background:" + COLOR.Red + "'></i>Red: exhausted<br><i style='background:" + COLOR.Amber + "'></i>Amber: tight<br><i style='background:" + COLOR.Green + "'></i>Green: free<br>"
      + "<i style='background:" + COLOR.Grey + "'></i>Grey: no data<br><u style='background:" + LINE_COLOR.Bottleneck + "'></u>Line: bottleneck<br><u style='background:" + LINE_COLOR["Highly loaded"] + "'></u>Line: highly loaded<br>"
      + "<u style='background:" + LINE_COLOR["No data"] + "'></u>Line without data<br><small>Lines are straight connections,<br>not the real routes.</small>";
    return div;
  };
  legend.addTo(map);
  L.control.scale({imperial: false}).addTo(map);
}
</script></body></html>
"""


def load(root: Path):
    proc = root / "data" / "processed"
    rd = lambda n: pd.read_csv(proc / n, dtype=str, keep_default_na=False)
    lines, trafos, subs = lights.compute(rd("master_lines.csv"), rd("master_transformers.csv"), rd("master_substations.csv"), rd("utilization_monthly.csv"), rd("grid_connection_tso.csv"))[0:3]
    coords = rd("substation_coordinates.csv")
    coords = coords[(coords["latitude"] != "") & (coords["longitude"] != "")]
    pos = {n: (round(float(a), 5), round(float(b), 5), acc) for n, a, b, acc in zip(coords["substation"], coords["latitude"], coords["longitude"], coords["accuracy"])}
    meta = dict(zip(*[rd("meta.csv")[c] for c in ("key", "value")]))
    return lines, subs, pos, meta


def build(root: Path):
    lines, subs, pos, meta = load(root)
    pct = lambda u: None if u is None or pd.isna(u) else round(float(u) * 100)
    points = [[r.substation, pos[r.substation][0], pos[r.substation][1], r.light, r.country, pct(r.util_max), r.reason, pos[r.substation][2]] for r in subs.itertuples() if r.substation in pos]
    segs = []
    for r in lines.itertuples():
        if r.substation_1 in pos and r.substation_2 in pos and r.substation_1 != r.substation_2:
            a, b = pos[r.substation_1], pos[r.substation_2]
            kv = str(r.voltage_kv).split(".")[0]
            segs.append([a[0], a[1], b[0], b[1], r.status, r.element_name, kv, pct(r.util_max), r.tso])
    status = (f"Data as of {meta.get('created_utc', '?')} UTC, utilization {meta.get('data_from_day', '?')} to {meta.get('data_to_day', '?')} ({meta.get('days_with_data', '?')} day(s)), "
              f"{meta.get('scenario', '')}. Lights as in the Excel model with its default parameters. {meta.get('note', '')}")
    return points, segs, status


def to_html(points, segs, status: str) -> str:
    dumps = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    esc = status.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (PAGE.replace("__STATUS__", esc).replace("__POINTS__", dumps(points)).replace("__LINES__", dumps(segs))
            .replace("__COLOR__", dumps(COLOR)).replace("__LINE_COLOR__", dumps(LINE_COLOR)))


def to_geojson(points, segs) -> dict:
    """Points and lines with the display hints GitHub understands (simplestyle: marker-color, stroke, stroke-width)."""
    feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[s[1], s[0]], [s[3], s[2]]]},
              "properties": {"name": s[5], "tso": s[8], "voltage_kv": s[6], "status": s[4], "highest_utilization_pct": s[7], "stroke": LINE_COLOR[s[4]],
                             "stroke-width": 3 if s[4] in ("Bottleneck", "Highly loaded") else 1, "stroke-opacity": 0.8}} for s in segs]
    feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p[2], p[1]]},
               "properties": {"name": p[0], "country": p[4], "light": p[3], "highest_utilization_pct": p[5], "reason": p[6], "location": p[7],
                              "marker-color": COLOR[p[3]], "marker-size": "small"}} for p in points if p[3] != "Grey"]
    return {"type": "FeatureCollection", "features": feats}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", help="write the browser map to this file")
    ap.add_argument("--geojson", help="write the GeoJSON to this file")
    a = ap.parse_args()
    points, segs, status = build(common.ROOT)
    for target, text in ((a.html, lambda: to_html(points, segs, status)), (a.geojson, lambda: json.dumps(to_geojson(points, segs), ensure_ascii=False, separators=(",", ":")))):
        if target:
            out = Path(target) if Path(target).is_absolute() else common.ROOT / target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text(), encoding="utf-8")
            print(f"{out}: {out.stat().st_size / 1e6:.2f} MB")
    n = pd.Series([p[3] for p in points]).value_counts().to_dict()
    print(f"{len(points)} substations on the map {n}, {len(segs)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
