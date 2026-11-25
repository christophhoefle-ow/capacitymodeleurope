# Operations guide

## Automatic operation
Nothing has to be started or typed in. The actions and their times are listed in `README.md`; every action can also be started by hand (Actions > name > Run workflow).
* All actions that write into the repository share one concurrency group (`data-writes`), so they never run at the same time.
* A failed source keeps its last good state. The action then opens an issue: `Automatic update failed: ...`. Close the issue when it is solved; the next failure opens a new one.
* **Connection capacity** (`scripts/fetch_connection_capacity.py`, `config/connection_sources.yml`): one block per publication. Adapter `pdf_status` reads a PDF with one row per substation and a status in words
  (50Hertz); the link to the PDF is looked up on the page at every run because the file name carries the date, with the last known address as fallback. Adapter `page_blocks` reads a page with one block per substation (TransnetBW), `pdf_rows` a PDF with one text row per substation (Amprion), `table` an HTML table, CSV or Excel file
  (columns found by their header words). `browser: true` reads the page with a headless browser (pages with bot protection or client-side rendering); a plain request that fails falls back to the browser. Results: `data/interim/connection/<id>.csv` and `status.csv`. Rows in `data/manual/grid_connection_tso.csv` win over harvested rows (for corrections).
  The words-to-status mapping (`status_map`) is an assumption of the model: change it in the configuration, not in the code.
* **Network model** (`scripts/update_sgm.py`): a new release is adopted only if the validation passes, no TSO disappears and lines, transformers and substations do not shrink by more than 10 %.
  Otherwise the files are put back and an issue explains why. After an adoption, look at `data/manual/coordinates_report.csv` and run `python scripts/suggest_aliases.py`.
* **Map geodata** (`scripts/update_geodata.py`): positions from the newest version of the Zenodo record, borders from Natural Earth (addresses in `config/config.yml`, `sources.geodata`).
* **Location ranking** (`scripts/estimate_coordinates.py`): manual > OpenStreetMap (name and country) > TSO file > anchor > estimate. `coordinates_line_check.csv` lists lines whose air distance exceeds their
  stated length (a wrong position). Not checked: tie-lines (each TSO lists only its own part) and lines whose two ends are both exact (RTE lists section lengths).

## Daily operation
* GitHub action **Fetch JAO utilization** (daily, 20:15 UTC) fetches the missing days of the last 7 days: 24 hourly requests per day, all 16 Core TSOs,
  keeps only the rows of the configured **scenario** (`evaluation.scenario`, default `base_case` = no outage), aggregates per network element and day
  (`data/interim/daily/YYYY-MM-DD.csv.gz`, one small file per day) and then builds the delivery files for Excel (`data/processed/*.csv`).
* Catch up a period: Actions > Fetch JAO utilization > Run workflow with start and end date (or locally `python scripts/fetch_jao.py --from 2026-11-01 --to 2026-11-15`).
  Large catch-ups (months) should be agreed with JAO first.
* A day with status `fallback` (JAO used the backup procedure) is not retried; `waiting` days are retried in the next run.

## Excel
* **Quarterly evaluation** (decision 06): the model aggregates a window of 3 months (sheet Parameters). The action *Build Excel model* runs on the 1st of every quarter and on demand.
* File `Capacity_Model_Core_refreshable.xlsx`: one data connection per hidden raw data sheet (range queries on the CSV files, not Excel tables). Open, Enable editing,
  Enable content, then Data > Refresh all. The repository must be **publicly readable**; for a private repository use Power Query with a token (`docs/POWER_QUERY.md`).
  The address is fixed in the connections; change it with `python scripts/set_base_url.py <file> https://raw.githubusercontent.com/<ORG>/<REPO>/main/data/processed/`.
  Not tested in Excel: if Excel reports a damaged file, use `Capacity_Model_Core.xlsx` (no connections) and Power Query.
* Files from the action contain formulas without stored results (Excel calculates on opening; in Protected View cells look empty). With LibreOffice installed, results can be stored:
  `python scripts/add_cached_values.py ORIGINAL.xlsx CALCULATED_BY_LIBREOFFICE.xlsx OUTPUT.xlsx`.
* Check after every refresh: sheet **Checks** (all statuses OK or understood) and `python scripts/check_model.py <calculated file>` (independent recalculation in pandas).

## Master data
* Network of all 16 TSOs: the JAO Core Static Grid Model (twice a year, jao.eu/static-grid-model). Load a new release with `python scripts/ingest_sgm.py <workbook.xlsx> --release "<label>"`; it writes
  `data/static/sgm_lines_core.csv` and `sgm_transformers_core.csv` (cross-border and internal tie-lines told apart, tie-lines listed by two TSOs kept once, substation of every transformer derived).
  Then `python scripts/validate_sgm.py`, `python scripts/build_processed.py`, `python scripts/estimate_coordinates.py`.
* Substation identity: spelling and voltage suffix do not matter (`Röhrsdorf` = `Roehrsdorf`, `Meeden 380` = `Meeden 220` = `Meeden`).
* JAO elements without a partner in the SGM stay as own master rows (source `JAO`), so nothing published by JAO is lost.
* Matching of JAO elements with the master data: alias (`data/manual/alias_jao_sgm.csv`), then EIC, then name, then unmatched (becomes its own master row). Suggestions: `python scripts/suggest_aliases.py`.

## Map
The network map covers all 13 countries and is driven completely by formulas (sheets Map_Data, Map_Lines): longitude and latitude, projection, zoom window, chart units.
The window follows the country selected on the Dashboard (All = whole region); points, lines, borders, corridors and country codes zoom together, the selected country is highlighted.
* Locations: `python scripts/estimate_coordinates.py` to `data/processed/substation_coordinates.csv`. Ranking: exact (`data/manual/coordinates_manual.csv`) > anchor (`coordinate_anchors.csv`: place of the
  same-named locality, general knowledge, unchecked) > estimate from line lengths (German SGM grid) > mean of located neighbours (schematic). A position outside its country is rejected
  (`src/capmodel/countries.py`); `data/manual/coordinates_report.csv` lists rejections and ambiguous names, `coordinates_line_check.csv` lists suspiciously long lines (wrong anchors).
* Improve a location: add the exact value to `coordinates_manual.csv` (substation, latitude, longitude), rerun the script, rebuild the model. Coverage per country: Dashboard > Details > Map coverage.
* Borders (`src/capmodel/xl/outline.py`) are coarse schematic polygons; view windows and label positions are in `src/capmodel/countries.py`.

## Switching the scenario
`evaluation.scenario: worst_case` in `config/config.yml` makes the pipeline use all n-1 rows. Daily files carry the scenario; `build_processed.py` only uses the configured one.
Re-fetch the period (`--force`) after a switch so that the new scenario exists for all days.

## Grid expansion data (hand-maintained, all of Europe)
* Files: `data/static/grid_expansion_projects.csv` (one row per project, all countries) and `grid_expansion_sections.csv` (one row per section where progress is published). Always fill `plan_id`,
  `countries`, `scope`, `plan_source`, `source_url` and `as_of`; leave unknown values (capacity, TSO, year) **empty** instead of guessing. Status Listed = named in a European plan, stage not verified.
* Sources by tier: 1. ENTSO-E TYNDP and the EU list of PCI/PMI (all countries), 2. national plans for detail (BNetzA, Elia, TenneT NL, RTE, PSE, APG and others; the Regional Investment Plans list the links).
* `link_from` / `link_to` must be spelled like a substation in `master_substations.csv` (spelling, voltage and busbar number do not matter); the validation warns otherwise. Ends without a model substation stay empty.
* Update cycle: TYNDP and PCI list every two years (TYNDP 2026 is in preparation), national plans yearly, projects in construction quarterly. Edit the CSV, run `python scripts/build_processed.py`, rebuild the model.
* Not yet collected: the other TYNDP projects of the 13 countries (workflow Check TYNDP project data shows the structure of the data), sections of other projects, capacity of many projects.

## Test run over several days without JAO
`python scripts/mock_jao_server.py` starts a local stand-in for the JAO interface with SYNTHETIC data (elements of the Static Grid Model that appear in changing hours). With
`JAO_BASE_URL=http://127.0.0.1:8765/core/api python scripts/fetch_jao.py --from ... --to ...` the whole chain can be tested for weeks: fetching, daily files, `build_processed.py`, `estimate_coordinates.py`, the Excel model.
Measured with 30 simulated days (about 360,000 rows per day): 7 seconds per day for fetching and aggregating (without network time), 73 KB per day file, 1 second for the delivery files, Excel 259,000 formulas without errors.
Never publish results of this tool: the values are not real.

## What changes with more days
Elements appear in the JAO data only when they are critical in that hour, and this changes with the grid situation. Every additional day therefore adds elements with data: lines and substations leave the group
'no data' (grey) step by step, and the Excel model shows this after every refresh (sheet Checks: share of lines with JAO data). How far the share will rise with real data is unknown until a few weeks have been loaded.
