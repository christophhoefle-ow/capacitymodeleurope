"""Texts and Power Query templates for the Excel model (English)."""

NUM = "type number"
# M code per query: (query name, file, column types {column: m-type})
M_QUERIES = [
    ("D_Lines", "master_lines.csv",
     {c: NUM for c in ["voltage_kv", "imax_period_1_a", "imax_period_2_a", "imax_period_3_a", "imax_period_4_a", "imax_period_5_a", "imax_period_6_a",
                       "imax_fixed_a", "dlr_min_a", "dlr_max_a", "r_ohm", "x_ohm", "b_us", "length_km"]}),
    ("D_Transformers", "master_transformers.csv",
     {c: NUM for c in ["imax_min_a", "imax_max_a", "imax_fixed_a", "u_primary_kv", "u_secondary_kv", "r_ohm", "x_ohm", "b_us", "g_us", "angle_deg",
                       "du_phase_pct", "du_angle_pct"]}),
    ("D_Substations", "master_substations.csv", {}),
    ("D_Expansion", "grid_expansion.csv",
     {c: NUM for c in ["from_lat", "from_lon", "to_lat", "to_lon", "capacity_mw", "voltage_kv", "length_km", "built_km"]} | {"planned_year": "Int64.Type"}),
    ("D_ExpSections", "grid_expansion_sections.csv", {"length_km": NUM, "built_km": NUM}),
    ("D_Utilization", "utilization_monthly.csv",
     {"month": "type date", "fmax_mw": NUM, "hours": "Int64.Type", "util_sum": NUM, "util_max": NUM, "hours_high": "Int64.Type",
      "hours_overload": "Int64.Type", "hours_binding": "Int64.Type"}),
    ("D_Connection", "grid_connection_tso.csv",
     {"feed_in_free_from_mw": NUM, "feed_in_free_to_mw": NUM, "load_free_from_mw": NUM, "load_free_to_mw": NUM, "available_from_year": "Int64.Type"}),
    ("D_Occupancy", "occupancy_mastr.csv",
     {"occupied_feed_in_mw": NUM, "occupied_load_mw": NUM, "requested_feed_in_mw": NUM, "requested_load_mw": NUM}),
    ("D_Coordinates", "substation_coordinates.csv", {"latitude": NUM, "longitude": NUM}),
    ("D_Meta", "meta.csv", {}),
]


def m_code(name: str, filename: str, types: dict) -> list[str]:
    """M code of a query as a list of single lines (one line per cell: easy to copy)."""
    lines = [
        "let",
        f'    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "{filename}"]),',
        '        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        "    Empty = Table.ReplaceValue(Header, \"\", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),",
    ]
    if types:
        pairs = ", ".join("{" + f'"{c}", {t}' + "}" for c, t in types.items())
        lines += [f"    Typed = Table.TransformColumnTypes(Empty, {{{pairs}}}, \"en-US\")", "in", "    Typed"]
    else:
        lines += ["in", "    Empty"]
    return lines
