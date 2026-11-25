"""Sheet Guide: what the model answers, how to use it, where the data come from, how it is updated and what it cannot say.

Written for a consultant who opens the file for the first time and has not seen the project. Texts that depend on the data (data status, rules) are formulas.
"""
from __future__ import annotations

from openpyxl.styles import Alignment
from openpyxl.worksheet.properties import PageSetupProperties

from .style import BORDER, L_GOLD, NAVY, WRAP_TOP, fill, font, header, row_height, set_widths

W = {"A": 3, "B": 30, "C": 66, "D": 34, "E": 30}
META = lambda key: f'INDEX(D_Meta!$B$5:$B$60,MATCH("{key}",D_Meta!$A$5:$A$60,0))'


def _band(ws, r, text):
    ws.merge_cells(f"B{r}:E{r}")
    ws[f"B{r}"] = text
    for c in ws[f"B{r}:E{r}"][0]:
        header(c, "result")
    ws[f"B{r}"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[r].height = 20


def _text(ws, r, text, bold=False, size=10, color="000000"):
    ws.merge_cells(f"B{r}:E{r}")
    c = ws[f"B{r}"]
    c.value = text
    c.font = font(bold=bold, size=size, color=NAVY if str(text).startswith("=") else color)
    c.alignment = WRAP_TOP
    ws.row_dimensions[r].height = max(16, row_height(str(text) if not str(text).startswith("=") else "x" * 190, 160, line_pt=13))


def _table(ws, r, heads, rows, links=None):
    """Table in columns B..: header row, then one row per entry; links = {row index: sheet name} makes the first cell a link to that sheet."""
    for j, h in enumerate(heads):
        header(ws.cell(r, 2 + j, h), "calc")
    ws.row_dimensions[r].height = 18
    widths = [W["B"], W["C"], W["D"], W["E"]]
    for i, row in enumerate(rows):
        rr = r + 1 + i
        need = 16
        for j, v in enumerate(row):
            c = ws.cell(rr, 2 + j, v)
            c.alignment = WRAP_TOP
            c.border = BORDER
            c.font = font(bold=(j == 0), color=NAVY if j == 0 else "000000", size=10 if j == 0 else 9)
            need = max(need, row_height(str(v), widths[j] * (0.9 if j == 0 else 1.2), line_pt=12.5))
        if links and i in links:
            ws.cell(rr, 2).hyperlink = f"#'{links[i]}'!A1"
            ws.cell(rr, 2).font = font(bold=True, color="0B4BFF", underline="single")
        ws.row_dimensions[rr].height = need
    return r + 1 + len(rows)


def build_guide(wb, base_url, borders_source: str):
    ws = wb["Guide"]
    set_widths(ws, W)
    ws["A1"] = "Guide – how to use this model"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    r = 3
    _band(ws, r, "1  What this model answers")
    _text(ws, r + 1, "How heavily is the extra-high-voltage grid (220 and 380 kV) of the 13 countries of the Core capacity calculation region loaded, and where is "
                     "connection capacity still free? The model gives one traffic light per line, transformer and substation. It uses public data only and is rebuilt automatically from GitHub.")
    _text(ws, r + 2, ('=IFERROR("Data status: created "&' + META("created_utc") + '&" UTC, "&' + META("days_with_data") + '&" day(s) of utilization data ("&' + META("data_from_day")
                      + '&" to "&' + META("data_to_day") + '&"), evaluation window "&MONTH(P_From)&"/"&YEAR(P_From)&" to "&MONTH(P_To)&"/"&YEAR(P_To)&", scenario "&LOWER(P_Scenario)&".",'
                      '"Data status: no utilization data in the evaluation window (see sheet Checks).")'), bold=True)
    _text(ws, r + 3, '=IFERROR(IF(' + META("note") + '="","","Note: "&' + META("note") + '),"")', bold=True, color="C53532")
    ws[f"B{r + 3}"].font = font(bold=True, color="C53532")
    ws.row_dimensions[r + 2].height = 30
    ws.row_dimensions[r + 3].height = 30

    r += 5
    _band(ws, r, "2  Five steps")
    r = _table(ws, r + 1, ["Step", "What to do", "Where", "What to look for"],
               [("1  Check the data status", "Open the sheet Checks. Every status should be OK, or you should understand why it is not.", "Checks, section C", "CHECK means: do not quote numbers before it is resolved"),
                ("2  Choose the selection", "Set view (feed-in or withdrawal), country and TSO in the gold cells of row 3.", "Dashboard, cells B3, D3, F3", "All sheets follow this selection"),
                ("3  Read the result", "Tiles: number of substations per light. Table: the ten most heavily loaded substations. More tables under Details (plus sign at the left edge).", "Dashboard", "Grey means no data, not free capacity"),
                ("4  Look at the map", "Choose a zoom window, or type a substation name to mark it.", "Map, cells C3 and G3", "Table on the right: how exact the locations are per country"),
                ("5  Go into detail", "Filter the lists. The calculation columns are collapsed: plus sign above the column heads.", "Substations, Lines, Transformers", "Column Reason explains each light in words")],
               links={0: "Checks", 1: "Dashboard", 2: "Dashboard", 3: "Map", 4: "Substations"}) + 1

    _band(ws, r, "3  The sheets")
    r = _table(ws, r + 1, ["Sheet", "Content", "May I change it?", ""],
               [("Dashboard", "Selection, key message, tiles, ranking, details per country and TSO, grid expansion projects, small map.", "Only the gold cells in row 3", ""),
                ("Map", "Large map with zoom, substation search, legend and the quality of the locations.", "Only the gold cells in row 3", ""),
                ("Substations", "Result per substation: light for feed-in and withdrawal, highest utilization, reason. Calculation to the right.", "No (formulas)", ""),
                ("Lines, Transformers", "Calculation per network element: capacity, utilization in the window, status, light.", "No (formulas)", ""),
                ("Parameters", "Time window, traffic-light thresholds and technical assumptions with origin and effect.", "Yes: the gold cells", ""),
                ("Checks", "Data status from the pipeline and about twenty checks with explanation.", "No", ""),
                ("Hidden: D_...", "Raw data delivered by the pipeline, one sheet per CSV file. Replaced on every refresh.", "Never by hand", ""),
                ("Hidden: Map_Data, Map_Lines", "Helper sheets of the map: projection, zoom windows, borders. Unhide with a right click on a sheet tab.", "Zoom windows and labels (blue cells)", "")],
               links={0: "Dashboard", 1: "Map", 2: "Substations", 4: "Parameters", 5: "Checks"}) + 1

    _band(ws, r, "4  Colours and rules")
    for text in ("Gold cell with blue text: a selection or an assumption you may change. Navy text: a formula, do not overwrite it. Blue text in the raw data sheets: delivered data.",
                 '="Lights: red from "&ROUND(P_RedShare*100,0)&" % of hours at or above 100 % utilization, amber from "&ROUND(P_AmberShare*100,0)&" % of hours at or above "'
                 '&ROUND(P_AmberUtil*100,0)&" %, green below. A substation takes the light of its most heavily loaded element. Grey means no data."',
                 '="Utilization of an hour = expected flow divided by the limit of the element (JAO day-ahead capacity calculation, "&LOWER(P_Scenario)&"). It is a forecast before redispatch, so values above 100 % occur."',
                 "Connection light: from the free capacity a TSO publishes for the substation (MW range), or from its status if it publishes no MW. The light of a substation is the worse of grid and connection."):
        r += 1
        _text(ws, r, text)
        ws.row_dimensions[r].height = 30
    r += 2

    _band(ws, r, "5  Where the data come from")
    r = _table(ws, r + 1, ["Source", "Content", "Update", "Licence, terms"],
               [("JAO Publication Tool, Core Final Computation", "Expected flow and limit per network element and hour, all 16 TSOs", "Daily, automatic (GitHub)", "Public; terms of JAO"),
                ("JAO Core Static Grid Model", "Lines, tie-lines, transformers with limits and technical data", "Automatic: GitHub checks monthly and adopts a new release after plausibility checks", "Public; terms of JAO"),
                ("OpenStreetMap, matched to the JAO names by DLR (Zenodo 10.5281/zenodo.13367535)", "Position of the substations", "Automatic, monthly (GitHub action Update map geodata)", "ODbL; credit: © OpenStreetMap contributors"),
                ("Natural Earth", "Country borders of the map", "Automatic, monthly (GitHub action Update map geodata)", "Public domain"),
                ("Publications of the TSOs on connection capacity (directory: Capacitypedia of ENTSO-E and DSO Entity)", "Free connection capacity or status per substation; register of what each TSO publishes",
                 "Automatic, weekly (GitHub action Fetch connection capacity): 50Hertz, TransnetBW, Amprion; TenneT by browser, not yet verified. A failed source keeps its last state and raises an issue",
                 "Differs per operator: see the register"),
                ("ENTSO-E TYNDP, EU list of PCI and PMI, national plans", "Planned and under-construction lines", "Editorial table in the repository (no machine-readable source with status exists)", "CC BY 4.0 and public pages"),
                ("Full register with links", "docs/DATA_SOURCES.md and docs/DATENQUELLEN.md in the repository", "", "")]) + 1

    _band(ws, r, "6  How the model is updated")
    conn_text = (f"This file has data connections to {base_url}: Data, Refresh all loads the current CSV files (the repository must be publicly readable)." if base_url else
                 "This file has no data connections: it is a snapshot. Download a newer file from the release model-latest, or use Capacity_Model_Core_refreshable.xlsx.")
    for text in ("Every evening GitHub fetches the new day from JAO and stores small CSV files in the repository (action Fetch JAO utilization).",
                 "Every Monday, and whenever someone starts it, GitHub builds this workbook from those files and publishes it under Releases, release model-latest (action Build Excel model). "
                 "The release also contains network_map.html, the same map on a real background for the browser.",
                 conn_text,
                 "Instructions in the repository: ANLEITUNG_GitHub.md (setup, German), docs/UEBERGABE.md (handover, German), docs/OPERATIONS.md (operation), docs/DATA_CONTRACT.md (interface between pipeline and Excel)."):
        r += 1
        _text(ws, r, text)
    r += 2

    _band(ws, r, "7  What the model cannot say")
    for text in ("Coverage: JAO publishes only network elements that matter for cross-border trade. All other lines are grey. Grey is no statement about their load.",
                 "Utilization is a forecast from the capacity calculation, not a measured flow. What actually happened after redispatch is not in the data.",
                 "Locations marked approximate can be tens of kilometres off. Lines are straight connections, not routes. Borders: " + borders_source + ".",
                 "Connection capacity is only as good as the publication of each TSO. None of the German TSOs offers an interface: the model reads their pages and files automatically, "
                 "and a changed layout can interrupt that until the reader is adjusted (sheet Checks shows it). Several TSOs publish a status or free switch bays instead of MW.",
                 "The model covers 220 and 380 kV. The 110 kV level and the distribution grids are not included."):
        r += 1
        _text(ws, r, text)
    r += 2

    _band(ws, r, "8  Handover: fill in the blue cells")
    repo = ""
    if base_url and "raw.githubusercontent.com/" in base_url:
        parts = base_url.split("raw.githubusercontent.com/")[1].split("/")
        repo = "https://github.com/" + "/".join(parts[:2])
    for j, h in enumerate(["Role", "Name or address", "Since, contact", ""]):
        header(ws.cell(r + 1, 2 + j, h), "calc")
    for i, (role, value) in enumerate((("Model owner", ""), ("Deputy", ""), ("GitHub repository", repo), ("Assumptions last reviewed on", ""))):
        rr = r + 2 + i
        ws.cell(rr, 2, role).font = font(bold=True, color=NAVY)
        for j in (3, 4):
            c = ws.cell(rr, j, value if j == 3 else None)
            c.fill = fill(L_GOLD)
            c.font = font(color="0B4BFF")
            c.border = BORDER
        ws.cell(rr, 2).border = BORDER
    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 100
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = ws.sheet_properties.pageSetUpPr or PageSetupProperties()
    ws.sheet_properties.pageSetUpPr.fitToPage = True
