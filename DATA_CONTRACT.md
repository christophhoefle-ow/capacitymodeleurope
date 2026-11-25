# Data contract between pipeline and Excel model

The pipeline delivers nine CSV files in `data/processed/`. The Excel model reads them by column position into hidden sheets (D_...). Anything that writes these files (the GitHub pipeline, a script,
Power Query, Power Automate) can feed the model as long as it keeps this contract. The version is stored in `meta.csv` as `schema_version`; the sheet Checks compares it with the version the model was built for.

Rules: UTF-8, comma separated, dot as decimal separator, one header row, no thousand separators, empty text for missing values.

| File | Excel sheet | One row per | Columns (in this order) |
|---|---|---|---|
| `master_lines.csv` | D_Lines | line or tie-line | element_name, eic, tso, substation_1, substation_2, voltage_kv, imax_period_1_a to imax_period_6_a, imax_fixed_a, dlr_min_a, dlr_max_a, r_ohm, x_ohm, b_us, length_km, jao_comment, type, country, neighbor_country, source, country_1, country_2 |
| `master_transformers.csv` | D_Transformers | transformer or phase shifter | element_name, eic, tso, imax_min_a, imax_max_a, imax_fixed_a, u_primary_kv, u_secondary_kv, r_ohm, x_ohm, b_us, g_us, rao_steps, angle_deg, sym_asym, du_phase_pct, du_angle_pct, jao_comment, substation, type, country, source |
| `master_substations.csv` | D_Substations | substation | substation, country |
| `utilization_monthly.csv` | D_Utilization | element and month | month, key, match, tso, element, eic, fmax_mw, hours, util_sum, util_max, hours_high, hours_overload, hours_binding |
| `substation_coordinates.csv` | D_Coordinates | substation | substation, latitude, longitude, accuracy, source |
| `grid_expansion.csv` | D_Expansion | planned or under-construction project (all of Europe) | project_id, plan_id, name, corridor, type, tsos, from_name, from_lat, from_lon, to_name, to_lat, to_lon, link_from, link_to, capacity_mw, voltage_kv, length_km, built_km, status, planned_year, commissioning_note, as_of, source_url, remark, countries, scope, plan_source |
| `grid_expansion_sections.csv` | D_ExpSections | section of a project | project_id, section, description, length_km, built_km, tso, state, construction_start, status_text, as_of |
| `grid_connection_tso.csv` | D_Connection | substation with a statement of its TSO | substation, tso, voltage_level, feed_in_free_from_mw, feed_in_free_to_mw, load_free_from_mw, load_free_to_mw, available_from_year, as_of, source_url, remark, connection_status, status_feed_in, status_load |
| `meta.csv` | D_Meta | setting | key, value |

Values: `type` of a line is Line, Tie-line (cross-border) or Internal tie-line (between two TSOs of one country); `source` is SGM (Static Grid Model) or JAO (element without partner in the model).
`match` in `utilization_monthly.csv` tells how a JAO element was assigned to the model: alias, EIC, name, substations (same two substations and voltage class) or unmatched.
Expansion values: `status` is Under construction, Permitting, Planning, Listed (named in a European plan, stage not verified) or In operation; `scope` is national, cross-border or offshore; `countries` are ISO codes separated by semicolons.
Keys: an element is identified by its EIC, otherwise by `NAME|<name>`. `util_sum` is the sum of hourly utilizations (mean = sum / hours), so months and days can be added.
Connection values: MW ranges ('below 500 MW' = 0 to 500, 'above 2,000 MW' = 2,000 to 2,000) and/or `connection_status` = available, limited or none (for operators that publish no MW). `status_feed_in` and `status_load` override the status for one direction. The connection light is the worse of MW range and status, per direction. A substation name used in two countries carries the country in brackets (`St. Peter (AT)`).
Without effect on the model so far: `occupancy_mastr.csv` (headers only). Not read by Excel: `connection_publications.csv` (register of what each TSO publishes), `network_map.geojson` (map for GitHub).

## Changing the contract
Add columns only at the end, never rename or reorder existing ones. Any other change: raise `SCHEMA_VERSION` in `scripts/build_processed.py` and the expected version in `src/capmodel/xl/build.py`
(check "Data contract version"), rebuild the model, and describe the change here.

## Ways to connect
1. Built-in connections (`Capacity_Model_Core_refreshable.xlsx`): Data > Refresh all. Needs a publicly readable repository.
2. Power Query (`excel/power_query/*.m`, see `POWER_QUERY.md`): works with private repositories (token).
3. No connection: the action Build Excel model publishes the finished workbook under Releases (release `model-latest`), stable link
   `https://github.com/<ORG>/<REPO>/releases/latest/download/Capacity_Model_Core.xlsx`. The file contains calculated values, so previews and tools such as Power Automate can read it.
