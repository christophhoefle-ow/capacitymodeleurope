# Core capacity model: grid utilization and connection capacity in 13 countries

A traffic-light model for the extra-high-voltage grid (220 and 380 kV) of the Core capacity calculation region (13 countries, 16 TSOs), built on public data only.
It shows how heavily lines, transformers and substations are loaded and where the TSOs still publish free connection capacity.
The repository holds the data pipeline (Python, GitHub Actions) and the generator of the Excel model. Setup in German: `ANLEITUNG_GitHub.md`. Handover in German: `docs/UEBERGABE.md`.

## What runs by itself
| GitHub action | What it does | When | Checked against |
|---|---|---|---|
| Fetch JAO utilization | hourly flows and limits of all 16 TSOs, aggregated per element and day | daily 20:15 UTC | a mock server, not the live JAO interface |
| Fetch connection capacity | publications of the TSOs on free connection capacity per substation (50Hertz, TransnetBW, Amprion; TenneT by browser), register of all Core TSOs from Capacitypedia | Mondays 04:00 UTC | the real content of the TransnetBW page and of the Amprion and 50Hertz files, and a local web server; TenneT unverified; nothing run from GitHub yet |
| Build Excel model | both workbooks with calculated values, independent check, browser map; published as release `model-latest` | Mondays 05:30 UTC, after a new network model or new geodata | LibreOffice and `scripts/check_model.py`; not opened in Excel |
| Update network model | new release of the JAO Static Grid Model: download, import, validation, plausibility, adoption | 1st of each month | the release 03/2026 for the import; the download not run live |
| Update map geodata | substation positions (OpenStreetMap via DLR, Zenodo) and country borders (Natural Earth) | 2nd of each month | the layout of the real DLR file; the borders with built data only |

A source that fails keeps its last good state and raises a GitHub issue. Hand-maintained: only the table of grid expansion projects (no machine-readable source with status exists).

## Decisions behind this version (weekly of 25.11.2026)
| No. | Decision | Implementation |
|---|---|---|
| 01 | Continue the JAO model as the core | pipeline and model built on JAO Final Computation and Static Grid Model |
| 02 | Close data gaps with a second source | connection capacity per substation from the TSO publications (automatic: 50Hertz, TransnetBW, Amprion; TenneT unverified), exact locations from OpenStreetMap, planned projects; redispatch still open |
| 03 | Base case (n-0) instead of the worst outage case (n-1) | `evaluation.scenario: base_case` in `config/config.yml` |
| 04 | Red: at least 5 % of hours at 100 % or more. Amber: at least 5 % of hours at 80 % or more | parameters `P_RedShare`, `P_AmberUtil`, `P_AmberShare` in the sheet Parameters |
| 05 | Region: Core, 13 countries, check coverage | 16 TSOs in the config, sheet Checks shows countries and TSOs with data |
| 06 | Quarterly evaluation, automatic via the pipeline | evaluation window of 3 months; the workbook is rebuilt every week |

## How it works
1. `scripts/fetch_jao.py` fetches the missing days and stores one small file per day in `data/interim/daily/`.
2. `scripts/fetch_connection_capacity.py` reads the TSO publications configured in `config/connection_sources.yml` into `data/interim/connection/`.
3. `scripts/build_processed.py` joins everything with the master data and writes the delivery files in `data/processed/` (interface: `docs/DATA_CONTRACT.md`).
   `scripts/estimate_coordinates.py` places the substations: OpenStreetMap first, then TSO data, then estimates.
4. `scripts/build_excel_model.py` builds the workbook from these files; `scripts/build_map.py` builds `network_map.html` and `network_map.geojson`.

Excel never receives raw data (about 500,000 rows per day for the whole region), only the small CSV files.

## The workbook
Sheets: Guide (how to use it), Dashboard, Map (zoom, substation search), Substations, Lines, Transformers, Parameters, Checks; hidden raw data (`D_...`) and map helpers.
The map charts keep their proportions: the plot area fills the chart, title and legend are cells, the aspect ratio of the chart is locked (`tests/test_model_map.py`).

## Quick start (local)
```
pip install -r requirements.txt
python -m pytest -q
python scripts/update_geodata.py                    # positions and borders (needs internet)
python scripts/fetch_connection_capacity.py         # TSO publications (needs internet)
python scripts/mock_jao_server.py --port 8765       # in a second window: JAO stand-in with synthetic data, then
JAO_BASE_URL=http://127.0.0.1:8765/core/api python scripts/fetch_jao.py --from 2026-11-17 --to 2026-11-23
python scripts/build_processed.py
python scripts/estimate_coordinates.py
python scripts/build_excel_model.py --out build/Capacity_Model_Core.xlsx --no-connections
python scripts/build_map.py --html build/network_map.html
```

## Data
* `data/static/`: JAO Static Grid Model of all 16 TSOs, coordinates (`coordinates_dlr_osm*.csv`, `coordinates_tennet_*.csv`), borders (after the first run of Update map geodata), grid expansion tables.
* `data/manual/`: corrections and reports. `substation_aliases.csv` (typing variants), `coordinates_manual.csv` (overrides), `alias_jao_sgm.csv`; reports `coordinates_report.csv`, `coordinates_line_check.csv`, `grid_connection_report.csv`.
* `data/processed/`: the delivery files for Excel, `connection_publications.csv` (what each TSO publishes) and `network_map.geojson` (GitHub shows it as a map).
* Substation identity: spelling, voltage suffix and busbar number do not matter. A name used for sites in two countries is split (`St. Peter (AT)`, `St. Peter (DE)`).
* Rules per element: no data, too little data, bottleneck (red), highly loaded (amber), uncritical (green). A substation takes the worse of its weakest element and its connection status. No data is grey, never green.

## Folders
| Path | Content |
|---|---|
| `config/config.yml`, `config/connection_sources.yml` | JAO settings, TSOs, scenario, thresholds, geodata addresses; publications to read for the connection capacity |
| `src/capmodel/` | library: JAO client, aggregation, matching, locations, harvest of publications, geodata, lights, Excel generator (`xl/`) |
| `scripts/` | command line tools: fetch, update, process, build, check |
| `tests/` | automatic tests (run in every action) |
| `.github/workflows/` | `jao-daily`, `connection-capacity`, `build-model`, `network-model`, `geodata`, `tyndp-check` |
| `docs/` | `UEBERGABE.md`, `OPERATIONS.md`, `DATA_CONTRACT.md`, `DATA_SOURCES.md`, `POWER_QUERY.md`, `DATENQUELLEN.md` |

## Known limits
* Coverage: JAO publishes utilization only for elements that are critical in the Core capacity calculation. In the test hour this is 3 % of the French substations, 56 % of the German and 91 % of the Hungarian ones.
* Connection capacity: read per substation for TransnetBW (status, year, MW classes), Amprion (status per direction, year) and 50Hertz (switch-bay status; its MW classes are cell colours, reading them is implemented but not yet run on the real PDF). The TenneT page turned away automatic requests on 25.11.2026; its reader uses a browser and is unverified. The other twelve countries have no reader yet. No TSO offers an interface, so a changed page layout interrupts the reading until the source is adjusted.
* Locations: exact for the substations matched with OpenStreetMap. Until the first run of Update map geodata the repository holds an excerpt (AT, BE, CZ, DE, part of FR, typed from the Zenodo file); the other countries are approximate and the borders are hand-drawn outlines.
* One hour of test data so far (16.11.2026, 00:00 to 01:00 UTC). The results are an example, not a finding.
* Not opened in Excel: checked with LibreOffice and an independent recalculation. The built-in data connections and the Power Query code are untested in Excel.
* `network_map.html` was opened without internet only (script runs, notice appears); with the map background it is untested.

## Use and sharing
The data are public but carry different terms of use (see `docs/DATA_SOURCES.md`). A public repository publishes the derived CSV files as well, so clarify this internally first.
Positions based on OpenStreetMap need the attribution "© OpenStreetMap contributors" (ODbL). Natural Earth is public domain.
