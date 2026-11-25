"""Generator of the Excel model (English): capacity utilization of the Core region (13 countries, 16 TSOs).

Structure (6 visible sheets, 10 hidden):
  Dashboard | Substations (result) | Lines | Transformers (calculation) | Parameters | Checks
  hidden: Map_Data, Map_Lines (chart helpers), D_* (raw data = CSV deliveries of the pipeline)
All numbers on the visible sheets are formulas. The raw data sheets D_* are replaced by the Excel connections / Power Query.
"""
from __future__ import annotations

import csv
import re
import datetime as dt
import math
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.chart import BarChart, Reference, ScatterChart, Series
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.legend import LegendEntry
from openpyxl.chart.series import SeriesLabel
from openpyxl.chart.data_source import StrRef
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.formatting.rule import CellIsRule, DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import Outline, PageSetupProperties

from . import connections as conn
from .outline import OUTLINES, OUTLINES_CONTEXT
from ..countries import FOUND, FOUND_HALF, LABEL, REGIONS, VIEW
from openpyxl.chart.layout import Layout, ManualLayout
from .style import (AMPEL, BORDER, CENTER, FONT_TITLE, GREY, L_BLUE, L_GOLD, L_GREY, NAVY, WRAP_TOP, WHITE_SEP, color_formula, col, fill, font,
                    header, row_height, set_widths)

R0 = 5                                    # first data row of all table sheets
SZ = dict(lines=1500, trafos=300, subs=1100, util=12000, conn=500, occ=700, coord=1000, seg=1000, exp=20, sec=60)   # sizes: set from the data in build_workbook
K_LAT = 49.0                              # reference latitude used to shorten the map in x (cos); about the middle of the Core region
CORE = [("AT", "Austria"), ("BE", "Belgium"), ("CZ", "Czechia"), ("DE", "Germany"), ("FR", "France"), ("HR", "Croatia"), ("HU", "Hungary"),
        ("LU", "Luxembourg"), ("NL", "Netherlands"), ("PL", "Poland"), ("RO", "Romania"), ("SI", "Slovenia"), ("SK", "Slovakia")]

SHEETS = ["Guide", "Dashboard", "Map", "Substations", "Lines", "Transformers", "Parameters", "Checks", "Map_Data", "Map_Lines",
          "D_Lines", "D_Transformers", "D_Substations", "D_Expansion", "D_ExpSections", "D_Utilization", "D_Connection", "D_Occupancy", "D_Coordinates", "D_Meta"]
HIDDEN = ("D_", "Map_")
TAB = {"Guide": "0B4BFF", "Dashboard": "000F47", "Map": "000F47", "Substations": "000F47", "Lines": "82BAFF", "Transformers": "82BAFF", "Map_Data": "82BAFF",
       "Map_Lines": "82BAFF", "Parameters": "0B4BFF", "Checks": "0B4BFF"}
CSV_FILE = {"D_Lines": "master_lines.csv", "D_Transformers": "master_transformers.csv", "D_Substations": "master_substations.csv", "D_Expansion": "grid_expansion.csv", "D_ExpSections": "grid_expansion_sections.csv",
            "D_Utilization": "utilization_monthly.csv", "D_Connection": "grid_connection_tso.csv", "D_Occupancy": "occupancy_mastr.csv",
            "D_Coordinates": "substation_coordinates.csv", "D_Meta": "meta.csv"}
_STATE = {"connections": False, "specs": [], "borders": None, "borders_source": "schematic outlines (drawn by hand, not survey data)"}
PRESET = {"view": "Feed-in", "country": "All", "tso": "All", "grey": "Hide"}      # start selection of the Dashboard (the user changes it in Excel)
BLUE_FONT = font(color="0B4BFF")


# --------------------------------------------------------------------------- raw data headers (= CSV)
class Cols:
    """Column registry of a table sheet: spec = [(key, header, width)]; letters are derived, never hard-coded."""

    def __init__(self, spec):
        self.spec = spec
        self.keys = [s[0] for s in spec]

    def L(self, key: str) -> str:
        return get_column_letter(self.keys.index(key) + 1)

    @property
    def last(self) -> str:
        return get_column_letter(len(self.keys))

    def widths(self) -> dict:
        return {get_column_letter(i + 1): s[2] for i, s in enumerate(self.spec)}

    def heads(self) -> dict:
        return {get_column_letter(i + 1): s[1] for i, s in enumerate(self.spec)}


H_LINES = ["element_name", "eic", "tso", "substation_1", "substation_2", "voltage_kv", "imax_period_1_a", "imax_period_2_a", "imax_period_3_a",
           "imax_period_4_a", "imax_period_5_a", "imax_period_6_a", "imax_fixed_a", "dlr_min_a", "dlr_max_a", "r_ohm", "x_ohm", "b_us", "length_km",
           "jao_comment", "type", "country", "neighbor_country", "source", "country_1", "country_2"]
F_LINES = ["Element name", "EIC", "TSO", "Substation 1", "Substation 2", "Voltage (kV)", "Imax period 1 (A)", "Imax period 2 (A)", "Imax period 3 (A)",
           "Imax period 4 (A)", "Imax period 5 (A)", "Imax period 6 (A)", "Imax fixed (A)", "DLR min (A)", "DLR max (A)", "R (Ω)", "X (Ω)", "B (µS)",
           "Length (km)", "JAO comment", "Type", "Country", "Neighbor country", "Source", "Country of end 1", "Country of end 2"]
H_TRAFOS = ["element_name", "eic", "tso", "imax_min_a", "imax_max_a", "imax_fixed_a", "u_primary_kv", "u_secondary_kv", "r_ohm", "x_ohm", "b_us", "g_us",
            "rao_steps", "angle_deg", "sym_asym", "du_phase_pct", "du_angle_pct", "jao_comment", "substation", "type", "country", "source"]
F_TRAFOS = ["Element name", "EIC", "TSO", "Imax min (A)", "Imax max (A)", "Imax fixed (A)", "Voltage primary (kV)", "Voltage secondary (kV)", "R (Ω)",
            "X (Ω)", "B (µS)", "G (µS)", "Steps for RAO", "Angle θ (°)", "Sym./Asym.", "δu phase (%)", "δu angle (%)", "JAO comment", "Substation",
            "Type", "Country", "Source"]
H_SUBS, F_SUBS = ["substation", "country"], ["Substation / node", "Country"]
H_UTIL = ["month", "key", "match", "tso", "element", "eic", "fmax_mw", "hours", "util_sum", "util_max", "hours_high", "hours_overload", "hours_binding"]
F_UTIL = ["Month", "Key (EIC or NAME|name)", "Match", "TSO (per JAO)", "Element (per JAO)", "EIC (per JAO)", "Smallest Fmax in the month (MW)",
          "Hours with data", "Sum of hourly utilizations", "Highest utilization", "Hours ≥ 'high'", "Hours ≥ 'overload'", "Hours 'binding' (JAO)"]
H_CONN = ["substation", "tso", "voltage_level", "feed_in_free_from_mw", "feed_in_free_to_mw", "load_free_from_mw", "load_free_to_mw",
          "available_from_year", "as_of", "source_url", "remark", "connection_status", "status_feed_in", "status_load"]
F_CONN = ["Substation (spelling as in sheet Substations)", "TSO", "Voltage level", "Feed-in free from (MW)", "Feed-in free to (MW)", "Load free from (MW)",
          "Load free to (MW)", "Available from (year)", "Map as of", "Source (link)", "Remark", "Status if no MW are published (available / limited / none)", "Status for feed-in only (overrides the status)", "Status for load only (overrides the status)"]
H_OCC = ["substation", "occupied_feed_in_mw", "occupied_load_mw", "requested_feed_in_mw", "requested_load_mw", "as_of", "source"]
F_OCC = ["Substation", "Occupied feed-in (MW)", "Occupied load (MW)", "Requested feed-in (MW)", "Requested load (MW)", "As of", "Source"]
H_EXP = ["project_id", "plan_id", "name", "corridor", "type", "tsos", "from_name", "from_lat", "from_lon", "to_name", "to_lat", "to_lon", "link_from", "link_to",
         "capacity_mw", "voltage_kv", "length_km", "built_km", "status", "planned_year", "commissioning_note", "as_of", "source_url", "remark", "countries", "scope", "plan_source"]
F_EXP = ["Project ID", "Plan ID", "Project", "Corridor", "Type", "TSO(s)", "From", "From latitude", "From longitude", "To", "To latitude", "To longitude",
         "Model substation at From", "Model substation at To", "Capacity (MW)", "Voltage (kV)", "Length (km)", "Built (km)", "Status", "Planned year", "Commissioning note",
         "As of", "Source", "Remark", "Countries", "Scope", "Plan source"]
H_SEC = ["project_id", "section", "description", "length_km", "built_km", "tso", "state", "construction_start", "status_text", "as_of"]
F_SEC = ["Project ID", "Section", "Description", "Length (km)", "Built (km)", "TSO", "State(s)", "Construction since", "Status", "As of"]
H_COORD = ["substation", "latitude", "longitude", "accuracy", "source"]
F_COORD = ["Substation", "Latitude (°N)", "Longitude (°E)", "Accuracy of the location", "Source of the location"]
NUM = {"D_Lines": {"voltage_kv", "imax_period_1_a", "imax_period_2_a", "imax_period_3_a", "imax_period_4_a", "imax_period_5_a", "imax_period_6_a",
                   "imax_fixed_a", "dlr_min_a", "dlr_max_a", "r_ohm", "x_ohm", "b_us", "length_km"},
       "D_Transformers": {"imax_min_a", "imax_max_a", "imax_fixed_a", "u_primary_kv", "u_secondary_kv", "r_ohm", "x_ohm", "b_us", "g_us", "angle_deg",
                          "du_phase_pct", "du_angle_pct"},
       "D_Utilization": {"fmax_mw", "hours", "util_sum", "util_max", "hours_high", "hours_overload", "hours_binding"},
       "D_Connection": {"feed_in_free_from_mw", "feed_in_free_to_mw", "load_free_from_mw", "load_free_to_mw", "available_from_year"},
       "D_Occupancy": {"occupied_feed_in_mw", "occupied_load_mw", "requested_feed_in_mw", "requested_load_mw"},
       "D_Coordinates": {"latitude", "longitude"}, "D_Substations": set(), "D_Meta": set(),
       "D_Expansion": {"from_lat", "from_lon", "to_lat", "to_lon", "capacity_mw", "voltage_kv", "length_km", "built_km", "planned_year"}, "D_ExpSections": {"length_km", "built_km"}}


# --------------------------------------------------------------------------- load data
def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_inputs(root: Path) -> dict:
    proc = root / "data" / "processed"
    return {sheet: _read(proc / f) for sheet, f in CSV_FILE.items()}


def _cell_value(v: str, numeric: bool):
    if v == "":
        return None
    if numeric:
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def _set_sizes(data: dict) -> None:
    """Rows prepared in the calculation sheets: data + 25 % reserve (rounded up to 100)."""
    up = lambda n, lo: max(lo, int(math.ceil(n * 1.1 / 100.0) * 100))
    SZ.update(lines=up(len(data["D_Lines"]), 1500), trafos=up(len(data["D_Transformers"]), 300), subs=up(len(data["D_Substations"]), 1100), coord=up(len(data["D_Coordinates"]), 1000),
              util=max(12000, int(math.ceil(len(data["D_Utilization"]) * 1.5 / 1000.0) * 1000)))
    SZ.update(exp=max(20, len(data["D_Expansion"]) + 5), sec=max(60, len(data["D_ExpSections"]) + 20))
    SZ["seg"] = SZ["lines"]                    # the map draws every line of the sheet Lines


def last(kind: str) -> int:
    return R0 + SZ[kind] - 1


def DU(c: str) -> str:
    return f"D_Utilization!${c}${R0}:${c}${last('util')}"


def DX(c: str) -> str:
    return f"D_Expansion!${c}${R0}:${c}${R0 + SZ['exp'] - 1}"


def DS(c: str) -> str:
    return f"D_ExpSections!${c}${R0}:${c}${R0 + SZ['sec'] - 1}"


def meta_ref(key: str) -> str:
    """Formula part: value from D_Meta (text)."""
    return f'INDEX(D_Meta!$B$5:$B$60,MATCH("{key}",D_Meta!$A$5:$A$60,0))'


# --------------------------------------------------------------------------- raw data sheets
def _fit_width(ws, landscape=True, title_rows=None):
    """Print: A4, one page wide, optionally repeat the header rows on every page."""
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = ws.sheet_properties.pageSetUpPr or PageSetupProperties()
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    if title_rows:
        ws.print_title_rows = title_rows


def landing_sheet(ws, title_text, desc, friendly, tech, df, numeric, widths, date_col=None, pct_cols=()):
    """Raw data sheet: rows 1-2 explanation, row 3 readable heads, row 4 technical heads (= CSV), data from row 5."""
    ws.sheet_properties.tabColor = GREY
    ws["A1"] = title_text.replace(" – ", ": ")
    ws["A1"].font = font(bold=True, size=13, color=NAVY)
    desc = re.sub(r" · (.)", lambda m: ". " + m.group(1).upper(), desc).replace(" – ", ", ")
    ws["A2"] = desc
    ws["A2"].font = font(italic=True, size=9, color="595959")
    for j, (fh, th) in enumerate(zip(friendly, tech), start=1):
        c3 = ws.cell(3, j, fh)
        c3.font = font(italic=True, size=9, color="595959")
        c3.fill = fill(L_GREY)
        c3.alignment = CENTER
        c3.border = BORDER
        header(ws.cell(4, j, th), "data")
    ws.row_dimensions[3].height = 38
    ws.row_dimensions[4].height = 30
    for r, row in enumerate(df.itertuples(index=False), start=R0):
        for j, (v, name) in enumerate(zip(row, tech), start=1):
            if date_col and name == date_col:
                cell = ws.cell(r, j, dt.date.fromisoformat(v))
                cell.number_format = "mm/yyyy"
            else:
                cell = ws.cell(r, j, _cell_value(v, name in numeric))
                if name in pct_cols:
                    cell.number_format = "0.0%"
            cell.font = BLUE_FONT
    set_widths(ws, widths)
    ws.freeze_panes = "A5"
    lastr = max(R0, R0 + len(df) - 1)
    if _STATE["connections"] and ws.title in CSV_FILE:
        # range query: on refresh Excel replaces the content from row 4 (header) with the CSV file from the internet
        idx = len(_STATE["specs"]) + 1
        kinds = ["date" if t == date_col else ("number" if t in numeric else "text") for t in tech]
        ws.defined_names[f"ExternalData_{idx}"] = DefinedName(f"ExternalData_{idx}", attr_text=f"'{ws.title}'!$A$4:${col(len(tech))}${lastr}", hidden=True)
        _STATE["specs"].append(dict(sheet=ws.title, file=CSV_FILE[ws.title], columns=list(zip(tech, kinds))))
    else:
        ws.auto_filter.ref = f"A4:{col(len(tech))}{lastr}"
    _fit_width(ws, title_rows="3:4")


def build_landing_sheets(wb, data):
    w = {col(i): 16 for i in range(1, 27)}
    w.update({"A": 44, "B": 20, "C": 16, "D": 18, "E": 18, "T": 28, "U": 24, "V": 10, "W": 12, "X": 9})
    landing_sheet(wb["D_Lines"], "D_Lines – raw data: lines and tie-lines (master data)",
                  "German SGM extract (JAO Core Static Grid Model) plus all other JAO elements seen in the data (source JAO) · delivery: data/processed/master_lines.csv · "
                  "do not edit by hand (row 4 = header, data from row 5).", F_LINES, H_LINES, data["D_Lines"], NUM["D_Lines"], w)
    w = {col(i): 15 for i in range(1, 23)}
    w.update({"A": 36, "B": 20, "C": 16, "R": 28, "S": 18, "T": 16})
    landing_sheet(wb["D_Transformers"], "D_Transformers – raw data: transformers and phase-shifting transformers (master data)",
                  "Delivery: data/processed/master_transformers.csv · do not edit by hand.", F_TRAFOS, H_TRAFOS, data["D_Transformers"], NUM["D_Transformers"], w)
    landing_sheet(wb["D_Substations"], "D_Substations – raw data: all substations / nodes with their country",
                  "Derived from the substations of lines and transformers · delivery: data/processed/master_substations.csv.",
                  F_SUBS, H_SUBS, data["D_Substations"], set(), {"A": 40, "B": 10})
    landing_sheet(wb["D_Expansion"], "D_Expansion – raw data: planned and under-construction transmission projects of Europe (national, cross-border, offshore)",
                  "Hand-maintained from public sources (BNetzA, TSO project pages, ENTSO-E TYNDP, EU list of PCI/PMI) · delivery: data/processed/grid_expansion.csv · coordinates are approximate places, lines are schematic.",
                  F_EXP, H_EXP, data["D_Expansion"], NUM["D_Expansion"],
                  {"A": 11, "B": 9, "C": 38, "D": 9, "E": 28, "F": 20, "G": 28, "H": 10, "I": 10, "J": 28, "K": 10, "L": 10, "M": 16, "N": 16, "O": 10, "P": 9, "Q": 9, "R": 9, "S": 17,
                   "T": 9, "U": 50, "V": 11, "W": 50, "X": 50, "Y": 10, "Z": 13, "AA": 34})
    landing_sheet(wb["D_ExpSections"], "D_ExpSections – raw data: sections of the expansion projects (construction progress in km)",
                  "Hand-maintained from netzausbau.de (BNetzA) · delivery: data/processed/grid_expansion_sections.csv · so far only SuedLink project 3.",
                  F_SEC, H_SEC, data["D_ExpSections"], NUM["D_ExpSections"], {"A": 11, "B": 9, "C": 70, "D": 10, "E": 10, "F": 13, "G": 30, "H": 12, "I": 26, "J": 11})
    landing_sheet(wb["D_Utilization"], "D_Utilization – raw data: utilization per network element and month (JAO Final Computation)",
                  "Delivery: data/processed/utilization_monthly.csv · one row per month and element · mean = sum ÷ hours · scenario and window: see sheets Parameters / Checks.",
                  F_UTIL, H_UTIL, data["D_Utilization"], NUM["D_Utilization"],
                  {"A": 11, "B": 26, "C": 12, "D": 14, "E": 44, "F": 20, "G": 14, "H": 11, "I": 16, "J": 13, "K": 12, "L": 12, "M": 12},
                  date_col="month", pct_cols=("util_max",))
    landing_sheet(wb["D_Connection"], "D_Connection – free connection capacity according to the publications of the TSOs (ranges or status)",
                  "Delivery from data/processed/grid_connection_tso.csv (maintained by hand in data/manual/grid_connection_tso.csv, directory of the publications: Capacitypedia of ENTSO-E and DSO Entity) · "
                  "'below 500 MW' = from 0 to 500 · operators that publish no MW: column connection_status (available, limited, none) · name = spelling in sheet Substations.",
                  F_CONN, H_CONN, data["D_Connection"], NUM["D_Connection"],
                  {"A": 30, "B": 14, "C": 16, "D": 14, "E": 14, "F": 14, "G": 14, "H": 12, "I": 14, "J": 50, "K": 30, "L": 26, "M": 22, "N": 22})
    landing_sheet(wb["D_Occupancy"], "D_Occupancy – occupancy and pipeline per substation (MaStR, phase 2)",
                  "Not filled yet · delivery: data/processed/occupancy_mastr.csv.", F_OCC, H_OCC, data["D_Occupancy"], NUM["D_Occupancy"],
                  {"A": 30, "B": 16, "C": 14, "D": 16, "E": 16, "F": 14, "G": 40})
    landing_sheet(wb["D_Coordinates"], "D_Coordinates – location of the substations (for the network map on the Dashboard)",
                  "Delivery: data/processed/substation_coordinates.csv. Ranking: exact (manual or OSM), then anchor (place of the same-named locality), then estimate from line lengths or from neighbours. "
                  "All positions are approximate, see column accuracy.",
                  F_COORD, H_COORD, data["D_Coordinates"], NUM["D_Coordinates"], {"A": 30, "B": 13, "C": 13, "D": 44, "E": 52})
    landing_sheet(wb["D_Meta"], "D_Meta – data status and settings of the pipeline",
                  "Delivery: data/processed/meta.csv · values are text (decimal point) – the formulas read them independent of the locale.",
                  ["Key", "Value"], ["key", "value"], data["D_Meta"], set(), {"A": 28, "B": 80})


# --------------------------------------------------------------------------- parameters
PARAMS = [
    # (name, label, value, unit, description, origin, affects, format, kind)
    ("§", "A  Time window of the utilization data"),
    ("P_WindowMonths", "Evaluation window (number of months)", 3, "months",
     "Aggregation period. One hour only shows 0 or 100 % overload; a quarter is stable, 12 months show seasonality. Agreed: quarterly evaluation.",
     "Decision 06", "Lines, Transformers, Substations", "0", "input"),
    ("P_EndMonth", "Last month of the window (empty = latest month with data)", None, "date",
     "Empty = latest month with data; a date looks back.", "", "Lines, Transformers, Substations", "mm/yyyy", "input"),
    ("P_To", "Window to (calculated)", f'=IF(P_EndMonth="",IF(COUNT(D_Utilization!$A${R0}:$A$20004)=0,"",MAX(D_Utilization!$A${R0}:$A$20004)),DATE(YEAR(P_EndMonth),MONTH(P_EndMonth),1))',
     "date", "Result of the input above and the available data.", "formula", "", "mm/yyyy", "calc"),
    ("P_From", "Window from (calculated)", '=IF(P_To="","",EDATE(P_To,-(P_WindowMonths-1)))', "date", "First month of the window.", "formula", "", "mm/yyyy", "calc"),
    ("P_DataFrom", "Data available from", f'=IF(COUNT(D_Utilization!$A${R0}:$A$20004)=0,"",MIN(D_Utilization!$A${R0}:$A$20004))', "date",
     "Oldest month in D_Utilization.", "formula", "", "mm/yyyy", "calc"),
    ("P_DataTo", "Data available to", f'=IF(COUNT(D_Utilization!$A${R0}:$A$20004)=0,"",MAX(D_Utilization!$A${R0}:$A$20004))', "date",
     "Latest month in D_Utilization.", "formula", "", "mm/yyyy", "calc"),
    ("P_MinHours", "Minimum number of hours per network element", 1, "hours",
     "Below: 'too little data'. Ongoing operation: 168 (one week); currently 1 because of the one-hour test data.", "proposal", "Lines, Transformers", "0", "input"),
    ("§", "B  Scenario and capacity (technical)"),
    ("P_Scenario", "Scenario in the data (set in the pipeline)", f'=IFERROR(IF({meta_ref("scenario")}="base_case","Base case (n-0)","Worst case (n-1)"),"")', "text",
     "Base case = rows without outage. Set in config/config.yml (evaluation.scenario); the pipeline filters, Excel only shows it.", "Decision 03", "all", "@", "calc"),
    ("P_ImaxMethod", "Imax method for seasonal / DLR values", "MIN", "MIN / MAX",
     "With several limit-current values (seasonal, DLR): MIN = minimum (cautious), MAX = maximum.", "assumption V2", "Lines, Transformers", "@", "input"),
    ("P_CosPhi", "Power factor cos φ (conversion from MVA to MW)", 1, "", "MVA to MW; approximately 1 in the transmission grid.", "assumption V2", "Lines", "0.00", "input"),
    ("P_Unlimited", "Value for 'not limiting' (transformers)", 99999, "A", "Imax 99,999 A = not limiting according to the data; does not count as capacity.",
     "JAO data", "Transformers", "0", "input"),
    ("§", "C  Traffic-light rules network utilization (JAO)"),
    ("P_RedShare", "Red: share of hours at or above 100 % utilization from", 0.05, "% of hours",
     "Overload hour = utilization at or above 100 % in the selected scenario; from this share the element is a bottleneck (red).", "assumption V2",
     "Lines, Transformers, Substations", "0%", "input"),
    ("P_AmberUtil", "Amber: utilization threshold of an hour", 0.8, "% of limit",
     "An hour at or above this utilization counts as 'high'. Must equal the pipeline threshold (see section E).", "Decision 04", "Lines, Transformers, Substations", "0%", "input"),
    ("P_AmberShare", "Amber: share of hours at or above the threshold from", 0.05, "% of hours",
     "From this share of 'high' hours an element is highly loaded (amber), robust against single peak hours.", "Decision 04", "Lines, Transformers, Substations", "0%", "input"),
    ("§", "D  Traffic-light rules connection capacity (TSO maps)"),
    ("P_UseConnection", "Use the connection publications of the TSOs in the lights", "YES", "YES / NO",
     "YES = the light of a substation is the worse of grid utilization and connection status. NO = grid utilization only "
     "(the published values stay visible in the sheet Substations, the connection light is grey).", "proposal", "Substations, Dashboard, Map", "@", "input"),
    ("P_FreeGreenFrom", "Green if free capacity (lower bound of the range) is at least", 100, "MW",
     "Green if the lower bound is sufficient; red if the upper bound is 0 MW; otherwise amber.", "proposal", "Substations", "0", "input"),
    ("P_NotListed", "Substation that the publication of its TSO does not list", "GREY", "GREY / RED",
     "GREY = no statement. RED = counts as exhausted: 50Hertz states that existing substations it does not list offer no connection at present. "
     "Applies only to TSOs with at least one row in D_Connection.", "proposal", "Substations", "@", "input"),
]


def build_parameters(wb):
    ws = wb["Parameters"]
    ws["A1"] = "Parameters and assumptions"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = "Assumptions in blue can be changed here, all sheets recalculate. Grey rows are calculated."
    ws["A2"].font = font(italic=True, size=9, color="595959")
    for j, h in enumerate(["", "Parameter", "Value", "Unit", "Description", "Origin", "Effect on"], start=1):
        if h:
            header(ws.cell(4, j, h), "input")
    set_widths(ws, {"A": 2, "B": 52, "C": 16, "D": 14, "E": 74, "F": 14, "G": 30})
    r = R0
    dv_imax = DataValidation(type="list", formula1='"MIN,MAX"', allow_blank=False)
    dv_na = DataValidation(type="list", formula1='"GREY,RED"', allow_blank=False)
    dv_yn = DataValidation(type="list", formula1='"YES,NO"', allow_blank=False)
    ws.add_data_validation(dv_imax)
    ws.add_data_validation(dv_na)
    ws.add_data_validation(dv_yn)
    for p in PARAMS:
        if p[0] == "§":
            ws.cell(r, 2, p[1]).font = font(bold=True, color=NAVY)
            for j in range(2, 8):
                ws.cell(r, j).fill = fill("82BAFF")
            r += 1
            continue
        name, label, value, unit, expl, src, affects, fmt, kind = p
        ws.cell(r, 2, label).font = font(bold=(kind == "input"))
        vc = ws.cell(r, 3, value)
        vc.number_format = fmt
        vc.alignment = Alignment(horizontal="center", vertical="top")
        if kind == "input":
            vc.fill = fill(L_GOLD)
            vc.font = font(color="0B4BFF", bold=True)
            vc.border = BORDER
        else:
            vc.font = font(color="000F47")
            vc.fill = fill(L_GREY)
        ws.cell(r, 4, unit).font = font(color="595959")
        ws.cell(r, 5, expl).font = font(size=9)
        ws.cell(r, 6, src).font = font(size=9, italic=True, color="595959")
        ws.cell(r, 7, affects).font = font(size=9, color="595959")
        for j in (2, 4, 5, 6, 7):
            ws.cell(r, j).alignment = WRAP_TOP
        ws.row_dimensions[r].height = max(row_height(expl, 74 * 1.05, line_pt=12), row_height(label, 52, line_pt=13))
        wb.defined_names[name] = DefinedName(name, attr_text=f"Parameters!$C${r}")
        if name == "P_ImaxMethod":
            dv_imax.add(vc)
        if name == "P_NotListed":
            dv_na.add(vc)
        if name == "P_UseConnection":
            dv_yn.add(vc)
        r += 1
    r += 1
    ws.cell(r, 2, "E  Reconciliation with the pipeline").font = font(bold=True, color=NAVY)
    for j in range(2, 8):
        ws.cell(r, j).fill = fill("82BAFF")
    r += 1
    ws.cell(r, 2, "'High' threshold in the pipeline (column 'Hours ≥ high')").font = font()
    c = ws.cell(r, 3, f'=IFERROR(VALUE(SUBSTITUTE({meta_ref("util_high")},".",MID(1/2,2,1))),"")')    # locale-safe: decimal point -> decimal sign of the PC
    c.number_format = "0%"
    c.fill = fill(L_GREY)
    c.alignment = Alignment(horizontal="center")
    color_formula(c)
    ws.cell(r, 5, "The column 'Hours ≥ high' in D_Utilization is counted in the pipeline with this fixed threshold (config/config.yml). "
                  "The amber rule above uses that column, so both thresholds must be equal (see sheet Checks).").font = font(size=9)
    ws.cell(r, 5).alignment = WRAP_TOP
    ws.row_dimensions[r].height = 28
    wb.defined_names["P_PipelineHigh"] = DefinedName("P_PipelineHigh", attr_text=f"Parameters!$C${r}")
    r += 2
    ws.cell(r, 2, "F  Agreed decisions (weekly of 25.11.2026)").font = font(bold=True, color=NAVY)
    for j in range(2, 8):
        ws.cell(r, j).fill = fill("82BAFF")
    decisions = [("01  Continuation", "The JAO model continues as the core for the extra-high-voltage grid and the borders.", "decided"),
                 ("02  Data gaps", "A second source closes the gaps: redispatch data and grid development plans. First step done: planned and under-construction projects of Europe (national, cross-border; Dashboard details and corridors on the map); redispatch data still open.", "partly implemented"),
                 ("03  Scenario", "Base case (n-0, no outage) instead of the worst outage case (n-1). Set in the pipeline (config/config.yml).", "implemented"),
                 ("04  Bottleneck logic", "Red: ≥ 5 % of hours at ≥ 100 % utilization. Amber: ≥ 5 % of hours at ≥ 80 % (share of hours instead of a single peak).", "implemented"),
                 ("05  Region", "Core region: 13 countries, 16 TSOs. Coverage per country is checked in the sheet Checks.", "implemented"),
                 ("06  Update", "Quarterly evaluation, automatic via the GitHub pipeline (evaluation window 3 months).", "pipeline prepared")]
    for label, text_, st in decisions:
        r += 1
        ws.cell(r, 2, label).font = font(bold=True)
        ws.cell(r, 3, st).font = font(size=9, italic=True, color="595959")
        ws.cell(r, 3).alignment = Alignment(horizontal="center", vertical="top")
        ws.cell(r, 5, text_).font = font(size=9)
        ws.cell(r, 5).alignment = WRAP_TOP
        ws.row_dimensions[r].height = max(26, row_height(text_, 74 * 1.05, line_pt=12))
    ws.freeze_panes = "A5"
    ws.sheet_view.zoomScale = 100
    _fit_width(ws)


# --------------------------------------------------------------------------- helpers for calculation sheets
def band(ws, first, last_, row, text, kind):
    ws.merge_cells(f"{first}{row}:{last_}{row}")
    ws[f"{first}{row}"].value = text
    for cc in ws[f"{first}{row}:{last_}{row}"][0]:
        header(cc, kind)


def add_light_cf(ws, rng):
    for name, (bg, fg) in AMPEL.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{name}"'], fill=fill(bg), font=Font(name="Arial", color=fg, bold=True)))


def add_status_cf(ws, rng):
    for text, bg in (("Bottleneck", "F6D3D2"), ("Highly loaded", "FBEDBF"), ("Uncritical", "DDF0CC"), ("Too little data", "EDEDED"), ("No data", "EDEDED")):
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{text}"'], fill=fill(bg)))


def add_util_cf(ws, rng, first_cell):
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f"AND(ISNUMBER({first_cell}),{first_cell}>=1)"], fill=fill("F6D3D2")))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f"AND(ISNUMBER({first_cell}),{first_cell}>=P_AmberUtil)"], fill=fill("FBEDBF")))


def write_formulas(ws, r, formulas: dict, fmts: dict):
    for letter, formula in formulas.items():
        c = ws[f"{letter}{r}"]
        c.value = formula
        color_formula(c)
        if letter in fmts:
            c.number_format = fmts[letter]


def _calc_headers(ws, cols: Cols, height=48):
    for letter, text in cols.heads().items():
        header(ws[f"{letter}4"], "calc")
        ws[f"{letter}4"].value = text
    ws.row_dimensions[4].height = height
    set_widths(ws, cols.widths())


def _title(ws, text, sub, merge_to):
    ws["A1"] = text
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = font(italic=True, size=9, color="595959")
    ws.merge_cells(f"A2:{merge_to}2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 28



# --------------------------------------------------------------------------- Lines
LN = Cols([("name", "Element name", 44), ("eic", "EIC", 20), ("tso", "TSO", 14), ("sub1", "Substation 1", 18), ("sub2", "Substation 2", 18),
           ("kv", "Voltage (kV)", 9), ("type", "Type", 24), ("country", "Country", 9), ("neigh", "Neighbor country", 10), ("len", "Length (km)", 9),
           ("imax", "Imax basis (A)", 10), ("isrc", "Imax source", 10), ("smax", "Smax (MVA)", 10), ("pmax", "Pmax (MW)", 10),
           ("key", "Key (EIC or NAME|name)", 26), ("hours", "Hours with data", 10), ("uavg", "Utilization avg", 10), ("umax", "Utilization max", 10),
           ("hhigh", "Hours ≥ high", 10), ("hover", "Hours ≥ overload", 10), ("shigh", "Share of hours ≥ high", 11), ("sover", "Share of hours ≥ overload", 11),
           ("fmax", "Fmax per JAO (MW)", 11), ("rest", "Rest capacity (MW)", 12), ("status", "Status", 15), ("light", "Traffic light", 9),
           ("dup", "Possible duplicate?", 11), ("assessed", "Assessed (1/0)", 9), ("infilter", "In dashboard filter (1/0)", 10)])


def build_lines(wb):
    ws = wb["Lines"]
    L, n = LN.L, last("lines")
    _title(ws, "Lines – capacity, utilization and status per circuit (all Core countries)",
           f"Row n in this sheet = row n in D_Lines (room for {SZ['lines']} lines). All columns are formulas. Utilization = values from D_Utilization in the evaluation window "
           "(sheet Parameters), scenario as delivered by the pipeline.", "L")
    band(ws, L("name"), L("len"), 3, "MASTER DATA (copy of D_Lines)", "data")
    band(ws, L("imax"), L("pmax"), 3, "CAPACITY (calculated)", "calc")
    band(ws, L("key"), L("fmax"), 3, "UTILIZATION from D_Utilization (window per Parameters)", "calc")
    band(ws, L("rest"), L("light"), 3, "RESULT", "result")
    band(ws, L("dup"), L("assessed"), 3, "CONTROL", "data")
    _calc_headers(ws, LN)
    fm = {L("kv"): "0", L("len"): "0.0", L("imax"): "#,##0", L("smax"): "#,##0", L("pmax"): "#,##0", L("hours"): "#,##0", L("uavg"): "0.0%",
          L("umax"): "0.0%", L("hhigh"): "#,##0", L("hover"): "#,##0", L("shigh"): "0.0%", L("sover"): "0.0%", L("fmax"): "#,##0", L("rest"): "#,##0"}
    d = "D_Lines"
    for r in range(R0, n + 1):
        a, key = f"${L('name')}{r}", f"${L('key')}{r}"
        crit = f'{DU("B")},{key},{DU("A")},">="&P_From,{DU("A")},"<="&P_To'
        hours, over, high = f"${L('hours')}{r}", f"${L('sover')}{r}", f"${L('shigh')}{r}"
        f = {
            L("name"): f'=IF({d}!A{r}="","",{d}!A{r})',
            L("eic"): f'=IF({a}="","",{d}!B{r}&"")',
            L("tso"): f'=IF({a}="","",{d}!C{r}&"")',
            L("sub1"): f'=IF({a}="","",{d}!D{r}&"")',
            L("sub2"): f'=IF({a}="","",{d}!E{r}&"")',
            L("kv"): f'=IF(OR({a}="",{d}!F{r}=""),"",{d}!F{r})',
            L("type"): f'=IF({a}="","",{d}!U{r}&"")',
            L("country"): f'=IF({a}="","",{d}!V{r}&"")',
            L("neigh"): f'=IF({a}="","",{d}!W{r}&"")',
            L("len"): f'=IF(OR({a}="",{d}!S{r}=""),"",{d}!S{r})',
            L("imax"): (f'=IF({a}="","",IF(ISNUMBER({d}!M{r}),{d}!M{r},IF(COUNT({d}!G{r}:L{r})>0,IF(P_ImaxMethod="MAX",MAX({d}!G{r}:L{r}),MIN({d}!G{r}:L{r})),'
                        f'IF(AND(P_ImaxMethod="MAX",ISNUMBER({d}!O{r})),{d}!O{r},IF(ISNUMBER({d}!N{r}),{d}!N{r},IF(ISNUMBER({d}!O{r}),{d}!O{r},""))))))'),
            L("isrc"): (f'=IF({a}="","",IF({d}!X{r}="JAO","JAO",IF(ISNUMBER({d}!M{r}),"fixed",IF(COUNT({d}!G{r}:L{r})>0,"seasonal",'
                        f'IF(OR(ISNUMBER({d}!N{r}),ISNUMBER({d}!O{r})),"DLR","missing")))))'),
            L("smax"): f'=IF(OR({a}="",${L("imax")}{r}="",${L("kv")}{r}=""),"",SQRT(3)*${L("kv")}{r}*${L("imax")}{r}/1000)',
            L("pmax"): f'=IF(${L("smax")}{r}="","",${L("smax")}{r}*P_CosPhi)',
            L("key"): (f'=IF({a}="","",IF(OR(${L("eic")}{r}="",ISNUMBER(SEARCH("NOTAVAILABLE",${L("eic")}{r}))),'
                       f'"NAME|"&TRIM(SUBSTITUTE({a},CHAR(160)," ")),TRIM(${L("eic")}{r})))'),
            L("hours"): f'=IF({a}="","",SUMIFS({DU("H")},{crit}))',
            L("uavg"): f'=IF(OR({a}="",{hours}=0),"",SUMIFS({DU("I")},{crit})/{hours})',
            L("umax"): f'=IF(OR({a}="",{hours}=0),"",_xlfn.MAXIFS({DU("J")},{crit}))',
            L("hhigh"): f'=IF({a}="","",SUMIFS({DU("K")},{crit}))',
            L("hover"): f'=IF({a}="","",SUMIFS({DU("L")},{crit}))',
            L("shigh"): f'=IF(OR({a}="",{hours}=0),"",${L("hhigh")}{r}/{hours})',
            L("sover"): f'=IF(OR({a}="",{hours}=0),"",${L("hover")}{r}/{hours})',
            L("fmax"): f'=IF(OR({a}="",{hours}=0),"",_xlfn.MINIFS({DU("G")},{crit}))',
            L("rest"): f'=IF(OR({a}="",{hours}=0),"",${L("fmax")}{r}*MAX(0,1-${L("umax")}{r}))',
            L("status"): (f'=IF({a}="","",IF({hours}=0,"No data",IF({hours}<P_MinHours,"Too little data",'
                          f'IF({over}>=P_RedShare,"Bottleneck",IF({high}>=P_AmberShare,"Highly loaded","Uncritical")))))'),
            L("light"): (f'=IF({a}="","",IF(${L("status")}{r}="Bottleneck","Red",IF(${L("status")}{r}="Highly loaded","Amber",'
                         f'IF(${L("status")}{r}="Uncritical","Green","Grey"))))'),
            L("dup"): (f'=IF({a}="","",IF(OR(${L("eic")}{r}="",ISNUMBER(SEARCH("NOTAVAILABLE",${L("eic")}{r}))),"",'
                       f'IF(COUNTIFS(${L("eic")}${R0}:${L("eic")}${n},${L("eic")}{r},${L("name")}${R0}:${L("name")}${n},{a})>1,"check","")))'),
            L("assessed"): f'=IF({a}="","",IF(OR(${L("status")}{r}="Bottleneck",${L("status")}{r}="Highly loaded",${L("status")}{r}="Uncritical"),1,0))',
            L("infilter"): f'=IF({a}="",0,IF(AND(OR(K_Country="All",${L("country")}{r}=K_Country),OR(K_TSO="All",${L("tso")}{r}=K_TSO)),1,0))',
        }
        write_formulas(ws, r, f, fm)
    add_status_cf(ws, f"{L('status')}{R0}:{L('status')}{n}")
    add_light_cf(ws, f"{L('light')}{R0}:{L('light')}{n}")
    add_util_cf(ws, f"{L('umax')}{R0}:{L('umax')}{n}", f"{L('umax')}{R0}")
    ws.conditional_formatting.add(f"{L('dup')}{R0}:{L('dup')}{n}", CellIsRule(operator="equal", formula=['"check"'], fill=fill("FBEDBF")))
    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{LN.last}{n}"
    ws.sheet_view.zoomScale = 90
    _fit_width(ws, title_rows="4:4")


# --------------------------------------------------------------------------- Transformers
TN = Cols([("name", "Element name", 36), ("eic", "EIC", 20), ("tso", "TSO", 14), ("sub", "Substation", 18), ("type", "Type", 14), ("country", "Country", 9),
           ("kvp", "Voltage primary (kV)", 10), ("kvs", "Voltage secondary (kV)", 10), ("imax", "Imax basis (A)", 10), ("isrc", "Imax source", 14),
           ("snom", "Snom (MVA)", 10), ("key", "Key (EIC or NAME|name)", 26), ("hours", "Hours with data", 10), ("uavg", "Utilization avg", 10),
           ("umax", "Utilization max", 10), ("hhigh", "Hours ≥ high", 10), ("hover", "Hours ≥ overload", 10), ("shigh", "Share of hours ≥ high", 11),
           ("sover", "Share of hours ≥ overload", 11), ("fmax", "Fmax per JAO (MW)", 11), ("rest", "Rest capacity (MW)", 12), ("status", "Status", 15),
           ("light", "Traffic light", 9), ("assessed", "Assessed (1/0)", 9)])


def build_transformers(wb):
    ws = wb["Transformers"]
    L, n = TN.L, last("trafos")
    _title(ws, "Transformers – capacity, utilization and status per transformer / phase-shifting transformer",
           f"Row n in this sheet = row n in D_Transformers (room for {SZ['trafos']}). Capacity refers to the primary side. "
           "Note: 380/110 kV transformers (interface to the high-voltage grid) are not part of the JAO network model.", "L")
    band(ws, L("name"), L("kvs"), 3, "MASTER DATA (copy of D_Transformers)", "data")
    band(ws, L("imax"), L("snom"), 3, "CAPACITY (calculated)", "calc")
    band(ws, L("key"), L("fmax"), 3, "UTILIZATION from D_Utilization (window per Parameters)", "calc")
    band(ws, L("rest"), L("light"), 3, "RESULT", "result")
    band(ws, L("assessed"), L("assessed"), 3, "CONTROL", "data")
    _calc_headers(ws, TN)
    fm = {L("kvp"): "0", L("kvs"): "0", L("imax"): "#,##0", L("snom"): "#,##0", L("hours"): "#,##0", L("uavg"): "0.0%", L("umax"): "0.0%",
          L("hhigh"): "#,##0", L("hover"): "#,##0", L("shigh"): "0.0%", L("sover"): "0.0%", L("fmax"): "#,##0", L("rest"): "#,##0"}
    d = "D_Transformers"
    for r in range(R0, n + 1):
        a, key = f"${L('name')}{r}", f"${L('key')}{r}"
        crit = f'{DU("B")},{key},{DU("A")},">="&P_From,{DU("A")},"<="&P_To'
        hours, over, high = f"${L('hours')}{r}", f"${L('sover')}{r}", f"${L('shigh')}{r}"
        f = {
            L("name"): f'=IF({d}!A{r}="","",{d}!A{r})',
            L("eic"): f'=IF({a}="","",{d}!B{r}&"")',
            L("tso"): f'=IF({a}="","",{d}!C{r}&"")',
            L("sub"): f'=IF({a}="","",{d}!S{r}&"")',
            L("type"): f'=IF({a}="","",{d}!T{r}&"")',
            L("country"): f'=IF({a}="","",{d}!U{r}&"")',
            L("kvp"): f'=IF(OR({a}="",{d}!G{r}=""),"",{d}!G{r})',
            L("kvs"): f'=IF(OR({a}="",{d}!H{r}=""),"",{d}!H{r})',
            L("imax"): (f'=IF({a}="","",IF(AND(ISNUMBER({d}!F{r}),{d}!F{r}<P_Unlimited),{d}!F{r},IF(AND(ISNUMBER({d}!F{r}),{d}!F{r}>=P_Unlimited),"",'
                        f'IF(COUNT({d}!D{r}:E{r})>0,IF(P_ImaxMethod="MAX",MAX({d}!D{r}:E{r}),MIN({d}!D{r}:E{r})),""))))'),
            L("isrc"): (f'=IF({a}="","",IF({d}!V{r}="JAO","JAO",IF(AND(ISNUMBER({d}!F{r}),{d}!F{r}>=P_Unlimited),"not limiting",'
                        f'IF(ISNUMBER({d}!F{r}),"fixed",IF(COUNT({d}!D{r}:E{r})>0,"min/max","missing")))))'),
            L("snom"): f'=IF(OR({a}="",${L("imax")}{r}="",${L("kvp")}{r}=""),"",SQRT(3)*${L("kvp")}{r}*${L("imax")}{r}/1000)',
            L("key"): (f'=IF({a}="","",IF(OR(${L("eic")}{r}="",ISNUMBER(SEARCH("NOTAVAILABLE",${L("eic")}{r}))),'
                       f'"NAME|"&TRIM(SUBSTITUTE({a},CHAR(160)," ")),TRIM(${L("eic")}{r})))'),
            L("hours"): f'=IF({a}="","",SUMIFS({DU("H")},{crit}))',
            L("uavg"): f'=IF(OR({a}="",{hours}=0),"",SUMIFS({DU("I")},{crit})/{hours})',
            L("umax"): f'=IF(OR({a}="",{hours}=0),"",_xlfn.MAXIFS({DU("J")},{crit}))',
            L("hhigh"): f'=IF({a}="","",SUMIFS({DU("K")},{crit}))',
            L("hover"): f'=IF({a}="","",SUMIFS({DU("L")},{crit}))',
            L("shigh"): f'=IF(OR({a}="",{hours}=0),"",${L("hhigh")}{r}/{hours})',
            L("sover"): f'=IF(OR({a}="",{hours}=0),"",${L("hover")}{r}/{hours})',
            L("fmax"): f'=IF(OR({a}="",{hours}=0),"",_xlfn.MINIFS({DU("G")},{crit}))',
            L("rest"): f'=IF(OR({a}="",{hours}=0),"",${L("fmax")}{r}*MAX(0,1-${L("umax")}{r}))',
            L("status"): (f'=IF({a}="","",IF({hours}=0,"No data",IF({hours}<P_MinHours,"Too little data",'
                          f'IF({over}>=P_RedShare,"Bottleneck",IF({high}>=P_AmberShare,"Highly loaded","Uncritical")))))'),
            L("light"): (f'=IF({a}="","",IF(${L("status")}{r}="Bottleneck","Red",IF(${L("status")}{r}="Highly loaded","Amber",'
                         f'IF(${L("status")}{r}="Uncritical","Green","Grey"))))'),
            L("assessed"): f'=IF({a}="","",IF(OR(${L("status")}{r}="Bottleneck",${L("status")}{r}="Highly loaded",${L("status")}{r}="Uncritical"),1,0))',
        }
        write_formulas(ws, r, f, fm)
    add_status_cf(ws, f"{L('status')}{R0}:{L('status')}{n}")
    add_light_cf(ws, f"{L('light')}{R0}:{L('light')}{n}")
    add_util_cf(ws, f"{L('umax')}{R0}:{L('umax')}{n}", f"{L('umax')}{R0}")
    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{TN.last}{n}"
    ws.sheet_view.zoomScale = 90
    _fit_width(ws, title_rows="4:4")


# --------------------------------------------------------------------------- Substations (result)
SN = Cols([("sub", "Substation / node", 28), ("tso", "TSO", 14), ("country", "Country", 9), ("ntype", "Node type", 16),
           ("lf", "LIGHT feed-in", 10), ("lw", "LIGHT withdrawal", 10), ("umax", "Highest utilization (grid)", 12), ("basis", "Data basis", 15), ("reason", "Reason", 64),
           ("nlines", "Number of lines (domestic)", 9), ("ntie", "Number of tie-lines", 10), ("ntr", "Number of transformers", 8),
           ("nass", "Elements with JAO data", 11), ("nbott", "of which bottleneck", 9), ("nhigh", "of which highly loaded", 10),
           ("rest", "Rest capacity tightest element (MW)", 14), ("lgrid", "Light grid", 9), ("smaxl", "Σ Smax lines (MVA)", 12),
           ("smaxt", "Σ Smax tie-lines (MVA)", 12), ("snomt", "Σ Snom transformers (MVA)", 12), ("cfrom", "Feed-in free from (MW)", 11),
           ("cto", "Feed-in free to (MW)", 11), ("wfrom", "Load free from (MW)", 11), ("wto", "Load free to (MW)", 11), ("lcf", "Light connection feed-in", 12),
           ("lcw", "Light connection withdrawal", 12), ("cdate", "TSO map as of", 12), ("occf", "Occupied feed-in (MW)", 11), ("occl", "Occupied load (MW)", 11),
           ("reqf", "Requested feed-in (MW)", 11), ("reql", "Requested load (MW)", 11), ("pexp", "Planned expansion (MW)", 11),
           ("pyear", "Earliest planned year", 10), ("infilter", "In dashboard filter (1/0)", 10),
           ("sortv", "Sort value (filter)", 11), ("rank", "Rank utilization (filter)", 9), ("rowc", "Row TSO map", 9), ("rowo", "Row occupancy", 9),
           ("cstat", "TSO status (if no MW are published)", 12), ("cstf", "TSO status feed-in", 11), ("cstw", "TSO status load", 11), ("cyear", "Connection earliest from (year)", 11)])


def build_substations(wb):
    ws = wb["Substations"]
    L, n = SN.L, last("subs")
    _title(ws, "Substations – traffic light per network node (feed-in and withdrawal)",
           "Result per node in columns A–I; the weakest connected value determines the light. The calculation is on the right, collapsed (group above the column heads).", "I")
    ws.row_dimensions[2].height = 40
    band(ws, L("sub"), L("ntype"), 3, "SUBSTATION", "data")
    band(ws, L("lf"), L("reason"), 3, "RESULT", "result")
    band(ws, L("nlines"), L("lgrid"), 3, "GRID: utilization of the connected elements (JAO)", "calc")
    band(ws, L("smaxl"), L("snomt"), 3, "TECHNICAL CAPACITY (sums)", "calc")
    band(ws, L("cfrom"), L("cdate"), 3, "CONNECTION: free capacity according to TSO maps", "calc")
    band(ws, L("occf"), L("reql"), 3, "OCCUPANCY (MaStR, phase 2)", "calc")
    band(ws, L("pexp"), L("pyear"), 3, "GRID EXPANSION (projects at this node)", "calc")
    band(ws, L("infilter"), L("cyear"), 3, "HELPER COLUMNS", "data")
    _calc_headers(ws, SN, height=60)
    fm = {L("umax"): "0.0%", L("rest"): "#,##0", L("smaxl"): "#,##0", L("smaxt"): "#,##0", L("snomt"): "#,##0", L("cfrom"): "#,##0", L("cto"): "#,##0",
          L("wfrom"): "#,##0", L("wto"): "#,##0", L("pexp"): "#,##0", L("pyear"): "0", L("occf"): "#,##0", L("occl"): "#,##0", L("reqf"): "#,##0", L("reql"): "#,##0"}
    LT = lambda k: f"Lines!${LN.L(k)}${R0}:${LN.L(k)}${last('lines')}"
    TR = lambda k: f"Transformers!${TN.L(k)}${R0}:${TN.L(k)}${last('trafos')}"
    NA = lambda c: f"D_Connection!${c}${R0}:${c}${R0 + SZ['conn'] - 1}"
    BE = lambda c: f"D_Occupancy!${c}${R0}:${c}${R0 + SZ['occ'] - 1}"
    for r in range(R0, n + 1):
        a = f"${L('sub')}{r}"
        v = lambda k: f"${L(k)}{r}"
        dom = f'{LT("type")},"<>Tie-line"'
        tie = f'{LT("type")},"Tie-line"'
        # connection light = the worse of two statements of the TSO: the free capacity in MW (range) and the status in words (free switch bays, 'limited', 'none').
        # A substation its TSO does not list: grey, or red if P_NotListed = RED and that TSO has at least one row in D_Connection (50Hertz: 'not listed = no connection possibility')
        st_of = lambda k: f'IF({v(k)}="available","Green",IF({v(k)}="limited","Amber",IF({v(k)}="none","Red","")))'
        unlisted = f'IF(AND(P_NotListed="RED",{v("tso")}<>"",COUNTIF({NA("B")},{v("tso")})>0),"Red","Grey")'

        def conn_light(lo, hi, status_col):
            mw = f'IF(OR({lo}="",{hi}=""),"",IF({hi}<=0,"Red",IF({lo}>=P_FreeGreenFrom,"Green","Amber")))'
            st_light = st_of(status_col)
            return (f'=IF({a}="","",IF(P_UseConnection="NO","Grey",IF({v("rowc")}="",{unlisted},IF(AND({mw}="",{st_light}=""),"Grey",'
                    f'IF(OR({mw}="Red",{st_light}="Red"),"Red",IF(OR({mw}="Amber",{st_light}="Amber"),"Amber","Green"))))))')

        def cnt(extra):
            return (f'COUNTIFS({LT("sub1")},{a}{extra})+COUNTIFS({LT("sub2")},{a}{extra})-COUNTIFS({LT("sub1")},{a},{LT("sub2")},{a}{extra})')

        def sm(sumrng, extra=""):
            return (f'SUMIFS({sumrng},{LT("sub1")},{a}{extra})+SUMIFS({sumrng},{LT("sub2")},{a}{extra})-SUMIFS({sumrng},{LT("sub1")},{a},{LT("sub2")},{a}{extra})')

        f = {
            L("sub"): f'=IF(D_Substations!A{r}="","",D_Substations!A{r})',
            L("tso"): (f'=IF({a}="","",IFERROR(INDEX({LT("tso")},MATCH({a},{LT("sub1")},0)),IFERROR(INDEX({LT("tso")},MATCH({a},{LT("sub2")},0)),'
                       f'IFERROR(INDEX({TR("tso")},MATCH({a},{TR("sub")},0)),""))))'),
            L("country"): f'=IF({a}="","",D_Substations!B{r}&"")',
            L("ntype"): f'=IF({a}="","",IF(LEFT({a},2)="Y-","Branch node (Y)",IF(COUNTIF(L_Countries,{v("country")})>0,"Core node","Non-Core node")))',
            L("lf"): (f'=IF({a}="","",IF(OR({v("lgrid")}="Red",{v("lcf")}="Red"),"Red",IF(OR({v("lgrid")}="Amber",{v("lcf")}="Amber"),"Amber",'
                      f'IF(OR({v("lgrid")}="Green",{v("lcf")}="Green"),"Green","Grey"))))'),
            L("lw"): (f'=IF({a}="","",IF(OR({v("lgrid")}="Red",{v("lcw")}="Red"),"Red",IF(OR({v("lgrid")}="Amber",{v("lcw")}="Amber"),"Amber",'
                      f'IF(OR({v("lgrid")}="Green",{v("lcw")}="Green"),"Green","Grey"))))'),
            L("umax"): (f'=IF(OR({a}="",{v("nass")}=0),"",MAX(_xlfn.MAXIFS({LT("umax")},{LT("sub1")},{a},{LT("assessed")},1),'
                        f'_xlfn.MAXIFS({LT("umax")},{LT("sub2")},{a},{LT("assessed")},1),_xlfn.MAXIFS({TR("umax")},{TR("sub")},{a},{TR("assessed")},1)))'),
            L("basis"): (f'=IF({a}="","",IF(AND({v("lgrid")}<>"Grey",OR({v("lcf")}<>"Grey",{v("lcw")}<>"Grey")),"Grid + connection",'
                         f'IF({v("lgrid")}<>"Grey","Grid only",IF(OR({v("lcf")}<>"Grey",{v("lcw")}<>"Grey"),"Connection only","No data"))))'),
            L("reason"): (f'=IF({a}="","",IF({v("lgrid")}="Red","Bottleneck: "&{v("nbott")}&" of "&{v("nass")}&" assessed elements",'
                          f'IF({v("lgrid")}="Amber","Highly loaded: "&{v("nhigh")}&" of "&{v("nass")}&" assessed elements",'
                          f'IF({v("lgrid")}="Green","All "&{v("nass")}&" assessed elements below the thresholds","No utilization data")))'
                          f'&IF({v("lcf")}="Red",IF({v("rowc")}="",", TSO: not listed",IF({v("cfrom")}="",", TSO: no feed-in connection",", TSO: feed-in not free")),'
                          f'IF({v("lcf")}="Amber",IF({v("cfrom")}="",", TSO: feed-in connection limited",", TSO: feed-in "&{v("cfrom")}&" to "&{v("cto")}&" MW"),'
                          f'IF({v("lcf")}="Green",IF({v("cfrom")}="",", TSO: feed-in connection available",", TSO: feed-in free from "&{v("cfrom")}&" MW"),"")))'
                          f'&IF({v("lcw")}="Red",IF({v("rowc")}="","",IF({v("wfrom")}="",", no load connection",", load not free")),'
                          f'IF({v("lcw")}="Amber",IF({v("wfrom")}="",", load connection limited",", load "&{v("wfrom")}&" to "&{v("wto")}&" MW"),'
                          f'IF({v("lcw")}="Green",IF({v("wfrom")}="",", load connection available",", load free from "&{v("wfrom")}&" MW"),"")))'
                          f'&IF({v("cyear")}="","",", earliest "&{v("cyear")}))'),
            L("nlines"): f'=IF({a}="","",{cnt(","+dom)})',
            L("ntie"): f'=IF({a}="","",{cnt(","+tie)})',
            L("ntr"): f'=IF({a}="","",COUNTIFS({TR("sub")},{a}))',
            L("nass"): f'=IF({a}="","",{sm(LT("assessed"))}+SUMIFS({TR("assessed")},{TR("sub")},{a}))',
            L("nbott"): f'=IF({a}="","",{cnt("," + LT("status") + ",\"Bottleneck\"")}+COUNTIFS({TR("sub")},{a},{TR("status")},"Bottleneck"))',
            L("nhigh"): f'=IF({a}="","",{cnt("," + LT("status") + ",\"Highly loaded\"")}+COUNTIFS({TR("sub")},{a},{TR("status")},"Highly loaded"))',
            L("rest"): (f'=IF(OR({a}="",{v("nass")}=0),"",MIN('
                        f'IF(COUNTIFS({LT("sub1")},{a},{LT("assessed")},1)>0,_xlfn.MINIFS({LT("rest")},{LT("sub1")},{a},{LT("assessed")},1),1E+99),'
                        f'IF(COUNTIFS({LT("sub2")},{a},{LT("assessed")},1)>0,_xlfn.MINIFS({LT("rest")},{LT("sub2")},{a},{LT("assessed")},1),1E+99),'
                        f'IF(COUNTIFS({TR("sub")},{a},{TR("assessed")},1)>0,_xlfn.MINIFS({TR("rest")},{TR("sub")},{a},{TR("assessed")},1),1E+99)))'),
            L("lgrid"): f'=IF({a}="","",IF({v("nass")}=0,"Grey",IF({v("nbott")}>0,"Red",IF({v("nhigh")}>0,"Amber","Green"))))',
            L("smaxl"): f'=IF({a}="","",{sm(LT("smax"), "," + dom)})',
            L("smaxt"): f'=IF({a}="","",{sm(LT("smax"), "," + tie)})',
            L("snomt"): f'=IF({a}="","",SUMIFS({TR("snom")},{TR("sub")},{a}))',
            L("cfrom"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(INDEX({NA("D")},{v("rowc")})="","",INDEX({NA("D")},{v("rowc")})))',
            L("cto"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(INDEX({NA("E")},{v("rowc")})="","",INDEX({NA("E")},{v("rowc")})))',
            L("wfrom"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(INDEX({NA("F")},{v("rowc")})="","",INDEX({NA("F")},{v("rowc")})))',
            L("wto"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(INDEX({NA("G")},{v("rowc")})="","",INDEX({NA("G")},{v("rowc")})))',
            L("lcf"): conn_light(v("cfrom"), v("cto"), "cstf"),
            L("lcw"): conn_light(v("wfrom"), v("wto"), "cstw"),
            L("cdate"): f'=IF(OR({a}="",{v("rowc")}=""),"",INDEX({NA("I")},{v("rowc")})&"")',
            L("occf"): f'=IF(OR({a}="",{v("rowo")}=""),"",IF(INDEX({BE("B")},{v("rowo")})="","",INDEX({BE("B")},{v("rowo")})))',
            L("occl"): f'=IF(OR({a}="",{v("rowo")}=""),"",IF(INDEX({BE("C")},{v("rowo")})="","",INDEX({BE("C")},{v("rowo")})))',
            L("reqf"): f'=IF(OR({a}="",{v("rowo")}=""),"",IF(INDEX({BE("D")},{v("rowo")})="","",INDEX({BE("D")},{v("rowo")})))',
            L("reql"): f'=IF(OR({a}="",{v("rowo")}=""),"",IF(INDEX({BE("E")},{v("rowo")})="","",INDEX({BE("E")},{v("rowo")})))',
            L("pexp"): f'=IF({a}="","",SUMIFS({DX("O")},{DX("M")},{a})+SUMIFS({DX("O")},{DX("N")},{a}))',
            L("pyear"): (f'=IF({a}="","",IF(COUNTIFS({DX("M")},{a})+COUNTIFS({DX("N")},{a})=0,"",IF(OR(MIN(IF(COUNTIFS({DX("M")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("M")},{a}),9999),'
                         f'IF(COUNTIFS({DX("N")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("N")},{a}),9999))=0,MIN(IF(COUNTIFS({DX("M")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("M")},{a}),9999),'
                         f'IF(COUNTIFS({DX("N")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("N")},{a}),9999))>=9999),"",MIN(IF(COUNTIFS({DX("M")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("M")},{a}),9999),'
                         f'IF(COUNTIFS({DX("N")},{a})>0,_xlfn.MINIFS({DX("T")},{DX("N")},{a}),9999)))))'),
            L("infilter"): (f'=IF({a}="",0,IF(AND({v("ntype")}="Core node",OR(K_Country="All",{v("country")}=K_Country),OR(K_TSO="All",{v("tso")}=K_TSO)),1,0))'),
            L("sortv"): f'=IF(AND({v("infilter")}=1,ISNUMBER({v("umax")})),{v("umax")}+ROW()/1000000000,"")',
            L("rank"): f'=IF({v("sortv")}="","",RANK({v("sortv")},${L("sortv")}${R0}:${L("sortv")}${n}))',
            L("rowc"): f'=IF({a}="","",IFERROR(MATCH({a},{NA("A")},0),""))',
            L("rowo"): f'=IF({a}="","",IFERROR(MATCH({a},{BE("A")},0),""))',
            L("cstat"): f'=IF(OR({a}="",{v("rowc")}=""),"",LOWER(TRIM(INDEX({NA("L")},{v("rowc")})&"")))',
            # status per direction: the operator's statement for feed-in or load if there is one, otherwise the general status
            L("cstf"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(TRIM(INDEX({NA("M")},{v("rowc")})&"")="",{v("cstat")},LOWER(TRIM(INDEX({NA("M")},{v("rowc")})&""))))',
            L("cstw"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(TRIM(INDEX({NA("N")},{v("rowc")})&"")="",{v("cstat")},LOWER(TRIM(INDEX({NA("N")},{v("rowc")})&""))))',
            L("cyear"): f'=IF(OR({a}="",{v("rowc")}=""),"",IF(INDEX({NA("H")},{v("rowc")})="","",INDEX({NA("H")},{v("rowc")})))',
        }
        write_formulas(ws, r, f, fm)
        ws[f"{L('reason')}{r}"].alignment = Alignment(wrap_text=False, vertical="center")
    for rng in (f"{L('lf')}{R0}:{L('lw')}{n}", f"{L('lgrid')}{R0}:{L('lgrid')}{n}", f"{L('lcf')}{R0}:{L('lcw')}{n}"):
        add_light_cf(ws, rng)
    add_util_cf(ws, f"{L('umax')}{R0}:{L('umax')}{n}", f"{L('umax')}{R0}")
    ws.freeze_panes = "E5"
    ws.auto_filter.ref = f"A4:{SN.last}{n}"
    ws.sheet_view.zoomScale = 90
    _fit_width(ws, title_rows="3:4")


# --------------------------------------------------------------------------- Map_Data layout (letters fixed because the chart refers to them)
MD = dict(sub="A", ntype="B", country="C", lat="D", lon="E", acc="F", x="G", y="H", light="I", red="J", amber="K", green="L", grey="M",
          ox="O", oy="P", ox2="Q", oy2="R", lab="T", ccode="V", cred="W", camber="X", cgreen="Y", cgrey="Z", tso="AB", tsoc="AC", ex="AE", ey="AF")
MD_CORE_ROWS = (6, 5 + len(CORE))                    # country list V6:V18
MD_TSO_ROWS = (6, 5 + 16)                            # TSO list AB6:AB21


def KD(k: str) -> str:
    return f"Map_Data!${MD[k]}${R0}:${MD[k]}${last('subs')}"


# --------------------------------------------------------------------------- Checks
def build_checks(wb, base_url=None):
    ws = wb["Checks"]
    set_widths(ws, {"A": 46, "B": 40, "C": 18, "D": 16, "E": 22, "F": 16, "G": 70})
    ws["A1"] = "Checks – data status and model verification"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = "Check after every refresh. Raw data and map sheets are hidden (right-click a sheet tab, Unhide)."
    ws["A2"].font = font(italic=True, size=9, color="595959")
    band(ws, "A", "G", 4, "A  Raw data sheets: size and structure", "input")
    _tbl_header(ws, 5, ["Sheet", "Content", "Rows", "Room in model", "Columns as expected?", "Room sufficient?", "Note"], "input")
    spec = [("D_Lines", "Lines and tie-lines (master data)", H_LINES, SZ["lines"], "calculation sheet Lines"),
            ("D_Transformers", "Transformers / phase shifters", H_TRAFOS, SZ["trafos"], "calculation sheet Transformers"),
            ("D_Substations", "Substations / nodes", H_SUBS, SZ["subs"], "calculation sheet Substations"),
            ("D_Expansion", "Grid expansion projects", H_EXP, SZ["exp"], "Dashboard, Details"),
            ("D_ExpSections", "Grid expansion sections", H_SEC, SZ["sec"], "Dashboard, Details"),
            ("D_Utilization", "Utilization per element and month", H_UTIL, last("util") - R0 + 1, "formulas read up to row %d" % last("util")),
            ("D_Connection", "Free connection capacity (TSO)", H_CONN, SZ["conn"], "may be empty"),
            ("D_Occupancy", "Occupancy / pipeline (MaStR)", H_OCC, SZ["occ"], "may be empty (phase 2)"),
            ("D_Coordinates", "Location of the substations (map)", H_COORD, SZ["coord"], "formulas read up to row %d" % (R0 + SZ["coord"] - 1)),
            ("D_Meta", "Data status of the pipeline", ["key", "value"], 56, "")]
    n = len(spec)
    last_spec = 5 + n
    for i, (sheet, what, heads, cap, hint) in enumerate(spec):
        r = 6 + i
        ws.cell(r, 1, sheet).font = font(bold=True)
        ws.cell(r, 2, what)
        ws.cell(r, 3, f"=COUNTA({sheet}!$A$5:$A$40000)").number_format = "#,##0"
        ws.cell(r, 4, cap).number_format = "#,##0"
        ws.cell(r, 4).font = BLUE_FONT
        cond = ",".join(f'{sheet}!{col(j)}4="{h}"' for j, h in enumerate(heads, start=1))
        ws.cell(r, 5, f'=IF(AND({cond}),"OK","DEVIATION")')
        ws.cell(r, 6, f'=IF(C{r}<=D{r},"OK","TOO SMALL")')
        ws.cell(r, 7, hint).font = font(size=9, color="595959")
        for j in (3, 5, 6):
            color_formula(ws.cell(r, j))
            ws.cell(r, j).alignment = Alignment(horizontal="center")
        for j in range(1, 8):
            ws.cell(r, j).border = BORDER
    rc = last_spec + 2
    ws.cell(rc, 1, "D_Utilization covers:").font = font(bold=True)
    ws.cell(rc, 2, "=P_DataFrom").number_format = "mm/yyyy"
    ws.cell(rc, 3, "to").alignment = Alignment(horizontal="center")
    ws.cell(rc, 4, "=P_DataTo").number_format = "mm/yyyy"
    for c_ in (ws.cell(rc, 2), ws.cell(rc, 4)):
        c_.font = font(color="000F47", bold=True)
        c_.alignment = Alignment(horizontal="left")
    ws.cell(rc + 1, 1, "Data source for 'Refresh all':").font = font(bold=True)
    src = base_url if base_url else "no connections built in"
    ws.cell(rc + 1, 2, src).font = BLUE_FONT
    ws.merge_cells(start_row=rc + 1, start_column=2, end_row=rc + 1, end_column=7)
    src_row = rc + 1
    rb = rc + 3
    band(ws, "A", "G", rb, "B  Data status from the pipeline (sheet D_Meta)", "input")
    meta_rows = [("created_utc", "Created (UTC)"), ("git_commit", "Code version (commit)"), ("pipeline_version", "Pipeline version"), ("region", "Region"),
                 ("scenario", "Scenario in the data"), ("schema_version", "Data contract version"), ("countries_configured", "Countries in the configuration"), ("tsos_configured", "TSOs in the configuration"),
                 ("countries_in_data", "Countries with data"), ("data_from_day", "Utilization data from (day)"), ("data_to_day", "Utilization data to (day)"),
                 ("days_with_data", "Days with data"), ("days_complete", "of which complete (24 hours)"), ("sgm_release", "Network model (SGM release, German extract)"),
                 ("util_high", "'High' threshold in the pipeline"), ("util_overload", "'Overload' threshold in the pipeline"),
                 ("match_alias", "JAO elements matched by alias"), ("match_eic", "JAO elements matched by EIC"), ("match_name", "JAO elements matched by name"), ("match_substations", "JAO elements matched by substation pair"),
                 ("match_unmatched", "JAO elements without SGM partner (own master rows)"), ("note", "Note")]
    for i, (key, label) in enumerate(meta_rows):
        r = rb + 1 + i
        ws.cell(r, 1, label)
        c = ws.cell(r, 2, f'=IFERROR({meta_ref(key)},"n/a")')
        color_formula(c)
        c.alignment = Alignment(horizontal="left", wrap_text=True)
        ws.cell(r, 1).border = BORDER
        c.border = BORDER
    hint_row = rb + len(meta_rows)
    ws.merge_cells(f"B{hint_row}:G{hint_row}")
    ws.row_dimensions[hint_row].height = 30
    r0 = rb + len(meta_rows) + 2
    band(ws, "A", "G", r0, "C  Checks", "input")
    _tbl_header(ws, r0 + 1, ["Check", "Result", "Status", "What does it mean? What to do?", "", "", ""], "input")
    ws.merge_cells(f"D{r0 + 1}:G{r0 + 1}")
    lt = lambda k: f"Lines!${LN.L(k)}${R0}:${LN.L(k)}${last('lines')}"
    ntr = lambda k: f"Transformers!${TN.L(k)}${R0}:${TN.L(k)}${last('trafos')}"
    nsub = len(CORE)
    checks = [
        ("Column order of the raw data sheets", f'=COUNTIF(E6:E{last_spec},"OK")&" of {n} OK"', f'=IF(COUNTIF(E6:E{last_spec},"OK")={n},"OK","CHECK")',
         "Excel reads the raw data by column position. If a header deviates, the delivery has changed: check raw data sheet and formulas."),
        ("Room in the calculation sheets", f'=COUNTIF(F6:F{last_spec},"OK")&" of {n} OK"', f'=IF(COUNTIF(F6:F{last_spec},"OK")={n},"OK","CHECK")',
         "The calculation sheets have a fixed number of prepared rows. 'TOO SMALL' means: copy the formulas of the calculation sheet further down (or rebuild the file)."),
        ("Data source for 'Refresh all' set up", f"=B{src_row}",
         f'=IF(B{{r}}="no connections built in","INFO",IF(ISNUMBER(SEARCH("{conn.PLACEHOLDER}",B{{r}})),"CHECK","OK"))',
         "If this shows 'ORG/REPO', the address is still a placeholder: build the file with the GitHub action 'Build Excel model' or with --base-url. "
         "The repository must be publicly readable (otherwise Power Query with token, see docs/POWER_QUERY.md in the repository)."),
        ("Data contract version (pipeline and model)", f'=IFERROR({meta_ref("schema_version")},"n/a")', '=IF(B{r}="1","OK","CHECK")',
         "The pipeline delivers its CSV files under a versioned contract (docs/DATA_CONTRACT.md). If the version differs from the one this model was built for, columns or meanings may have changed: rebuild the model with the matching version of the repository."),
        ("Evaluation window contains data", f'=IF(SUM({lt("hours")})>0,"yes","no")', '=IF(B{r}="yes","OK","CHECK")',
         "'no' means: there are no utilization data in the selected period (Parameters). Check the window or D_Utilization."),
        ("Scenario in the data is the base case (n-0)", '=P_Scenario', '=IF(B{r}="Base case (n-0)","OK","INFO")',
         "The scenario is set in the pipeline (config/config.yml). Decision 03: base case. 'Worst case' would include all n-1 outage cases."),
        ("Countries with utilization data (of 13)", f'=SUMPRODUCT(--(COUNTIFS({lt("country")},L_Countries,{lt("assessed")},1)>0))&" of {nsub}"',
         '=IF(LEFT(B{r},2)="13","OK","NOTE")',
         "Countries without any assessed element in the window. Coverage per country differs a lot: JAO publishes only trade-relevant elements. "
         "In a single test hour Luxembourg (Creos) has no rows."),
        ("TSOs with utilization data (of 16)", f'=SUMPRODUCT(--(COUNTIFS({lt("tso")},L_TSOs,{lt("assessed")},1)>0))&" of 16"', '=IF(LEFT(B{r},2)="16","OK","NOTE")',
         "TSOs without any assessed element in the window."),
        ("Lines with JAO data (share)", f'=IF(COUNTIF({lt("name")},"?*")=0,"",SUM({lt("assessed")})/COUNTIF({lt("name")},"?*"))', '="INFO"',
         "Outside the German SGM extract the model only knows elements that JAO publishes; for Germany the share is lower because the full network is listed."),
        ("Elements known only from JAO (no SGM partner)", '=COUNTIF(D_Lines!$X$5:$X$40000,"JAO")+COUNTIF(D_Transformers!$V$5:$V$40000,"JAO")', '="INFO"',
         "Master rows derived from the JAO data (all non-German countries and German elements that could not be matched). "
         "To list the full network of the other countries, add their SGM extract (data/static)."),
        ("Lines without voltage (Smax stays empty)", f'=COUNTIFS({lt("name")},"?*",{lt("kv")},"")', '=IF(B{r}=0,"OK","NOTE")',
         "Gap in the source data. Capacity stays empty instead of 0. Check with the next SGM release."),
        ("Lines without Imax (source 'missing')", f'=COUNTIF({lt("isrc")},"missing")', '=IF(B{r}=0,"OK","NOTE")',
         "Without limit current no capacity. These lines do not count in the sums."),
        ("Possible duplicates (same EIC and same name)", f'=COUNTIF({lt("dup")},"check")', '=IF(B{r}=0,"OK","NOTE")',
         "May be real duplicates (e.g. a tie-line listed as line and tie-line) or two poles / strands. Check technically, do not delete automatically."),
        ("Core substations without map location (all countries)", f'=COUNTIFS({KD("ntype")},"Core node")-SUMPRODUCT(({KD("ntype")}="Core node")*ISNUMBER({KD("x")}))',
         '=IF(B{r}=0,"OK","NOTE")',
         "No coordinate for these substations: the name is ambiguous (same name at several operators or in two countries) or there is no anchor and no located neighbour. "
         "They are in the lists but not on the map. Per country: Dashboard, section Details, table Map coverage."),
        ("Substations with approximate map location", f'=COUNTIF(D_Coordinates!$D$5:$D${R0 + SZ["coord"] - 1},"exact*")&" exact, "&COUNTIF(D_Coordinates!$D$5:$D${R0 + SZ["coord"] - 1},"anchor*")&" anchors, "&COUNTIF(D_Coordinates!$D$5:$D${R0 + SZ["coord"] - 1},"estimated*")&" estimated"', '="INFO"',
         "Exact positions come from OpenStreetMap (matched to the JAO names by DLR, Zenodo 10.5281/zenodo.13367535, ODbL), from TSO data or from manual entries. Anchors are the place of the same-named locality (general knowledge, unchecked, +-10-30 km); "
         "estimates come from line lengths and the grid topology or, as a last resort, from the located neighbours (schematic). Exact values in data/manual/coordinates_manual.csv override everything. The country borders are coarse schematic outlines."),
        ("Map: source of the country borders", '="' + _STATE["borders_source"].replace('"', "'") + '"', '=IF(LEFT(B{r},9)="schematic","NOTE","OK")',
         "Real borders (Natural Earth, public domain) are loaded by the GitHub action 'Update map geodata' into data/static/borders.csv; the model is then rebuilt with them. "
         "Until then the map shows outlines drawn by hand: good for orientation, not exact."),
        ("Substation names used for two sites (split by country)", f'=IFERROR({meta_ref("homonyms_split")},"n/a")', '="INFO"',
         "A name that stands for different sites in different countries is listed once per country, with the country in brackets (for example St. Peter (AT) and St. Peter (DE)). "
         "Typing variants of one name are merged by data/manual/substation_aliases.csv."),
        ("Grid expansion: projects and sections in the data", '=COUNTIF(D_Expansion!$A$5:$A$40000,"?*")&" projects, "&COUNTIF(D_ExpSections!$A$5:$A$40000,"?*")&" sections"', '="INFO"',
         "Public sources, hand-maintained (data/static): each row has source and date. Coordinates are approximate places, lines on the map are schematic. Capacity, TSO and year are blank where the sources do not state them."),
        ("Grid expansion: endpoints without a model substation",
         '=SUMPRODUCT((D_Expansion!$G$5:$G$40000<>"")*(D_Expansion!$M$5:$M$40000=""))+SUMPRODUCT((D_Expansion!$J$5:$J$40000<>"")*(D_Expansion!$N$5:$N$40000=""))', '="INFO"',
         "These project ends have no substation in the model (for example converter sites outside the JAO network model); they appear on the map but without a 'light today'."),
        ("Connection capacity: publications read automatically", f'=IFERROR({meta_ref("connection_sources")},"n/a")', '=IF(OR(B{r}="none",B{r}="n/a"),"NOTE",IF(ISNUMBER(SEARCH("failed",B{r})),"CHECK",IF(ISNUMBER(SEARCH("not read",B{r})),"NOTE","OK")))',
         "The GitHub action 'Fetch connection capacity' reads the publications of the TSOs every week (list: config/connection_sources.yml; register of all Core TSOs: "
         "data/processed/connection_publications.csv). 'failed' means: the publication could not be read, the last good state is shown; GitHub has opened an issue. "
         "'not read yet' means: no successful reading so far."),
        ("Names in D_Connection without hit in the model", f'=SUMPRODUCT((D_Connection!$A$5:$A${R0 + SZ["conn"] - 1}<>"")*(COUNTIF(Substations!$A$5:$A${last("subs")},D_Connection!$A$5:$A${R0 + SZ["conn"] - 1})=0))',
         '=IF(B{r}=0,"OK","NOTE")', "Substations the TSOs list that the JAO network model does not know: new or planned sites, or a different spelling. These rows have no effect. "
         "List with the reason: data/manual/grid_connection_report.csv. A different spelling is fixed in config/connection_sources.yml (name_map of the source)."),
        ("Names in D_Occupancy without hit in the model", f'=SUMPRODUCT((D_Occupancy!$A$5:$A${R0 + SZ["occ"] - 1}<>"")*(COUNTIF(Substations!$A$5:$A${last("subs")},D_Occupancy!$A$5:$A${R0 + SZ["occ"] - 1})=0))',
         '=IF(B{r}=0,"OK","CHECK")', "As above, for the occupancy data."),
        ("'High' threshold: pipeline = Excel", '=IF(P_PipelineHigh="","n/a",P_PipelineHigh)', '=IF(P_PipelineHigh="","INFO",IF(P_PipelineHigh=P_AmberUtil,"OK","CHECK"))',
         "The amber rule counts the pipeline column 'Hours ≥ high'. If the pipeline threshold differs from the amber threshold in Parameters, the status is wrong: align both."),
        ("Pipeline note", f'=IFERROR(IF({meta_ref("note")}="","none",{meta_ref("note")}),"none")', '=IF(B{r}="none","OK","NOTE")', "For example: only example data available."),
    ]
    for i, (label, result, status, expl) in enumerate(checks):
        r = r0 + 2 + i
        ws.cell(r, 1, label).alignment = WRAP_TOP
        rc_ = ws.cell(r, 2, result)
        color_formula(rc_)
        rc_.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        if "share" in label:
            rc_.number_format = "0%"
        sc = ws.cell(r, 3, status.replace("{r}", str(r)))
        sc.alignment = Alignment(horizontal="center", vertical="top")
        sc.font = font(bold=True)
        ws.merge_cells(f"D{r}:G{r}")
        ws.cell(r, 4, expl).font = font(size=9)
        ws.cell(r, 4).alignment = WRAP_TOP
        ws.row_dimensions[r].height = max(30, row_height(expl, 120, line_pt=12), 44 if label.startswith(("Pipeline note", "Data source")) else 0)
        for j in range(1, 8):
            ws.cell(r, j).border = BORDER
    lastc = r0 + 1 + len(checks)
    for text, bg in (("OK", "DDF0CC"), ("CHECK", "F6D3D2"), ("DEVIATION", "F6D3D2"), ("TOO SMALL", "F6D3D2"), ("NOTE", "FBEDBF"), ("INFO", "CEECFF")):
        ws.conditional_formatting.add(f"C{r0 + 2}:C{lastc}", CellIsRule(operator="equal", formula=[f'"{text}"'], fill=fill(bg)))
        ws.conditional_formatting.add(f"E6:F{last_spec}", CellIsRule(operator="equal", formula=[f'"{text}"'], fill=fill(bg)))
    _fit_width(ws)


def _tbl_header(ws, row, labels, kind="result", first_col=1):
    for j, text in enumerate(labels, start=first_col):
        c = ws.cell(row, j, text)
        header(c, kind)
    ws.row_dimensions[row].height = 32


def _sum_row(ws, r, first, last_, cols, label="Total"):
    ws.cell(r, 1, label).font = font(bold=True, color=NAVY)
    for c in cols:
        cell = ws[f"{c}{r}"]
        cell.value = f"=SUM({c}{first}:{c}{last_})"
        cell.font = font(bold=True, color=NAVY)
        cell.number_format = "#,##0"
        cell.border = Border(top=Side(style="thin", color="000F47"))


# --------------------------------------------------------------------------- Map_Data / Map_Lines / map chart
CCOL = 25                                  # column Y: country chart table (code); the counts are in Z..AC
MAP_W, MAP_H = 100, 62                     # chart units = ratio of the map charts: the plot area fills the whole chart, so width : height of the chart object = 100 : 62 (see add_map)


def _PX(lon, lat):
    """Lambert azimuthal equal-area projection (as the European standard ETRS89-LAEA): x in km."""
    s, c = f"SIN(RADIANS({lat}))", f"COS(RADIANS({lat}))"
    return f"K_R*SQRT(2/(1+K_S1*{s}+K_C1*{c}*COS(RADIANS({lon}-K_L0))))*{c}*SIN(RADIANS({lon}-K_L0))"


def _PY(lon, lat):
    s, c = f"SIN(RADIANS({lat}))", f"COS(RADIANS({lat}))"
    return f"K_R*SQRT(2/(1+K_S1*{s}+K_C1*{c}*COS(RADIANS({lon}-K_L0))))*(K_C1*{s}-K_S1*{c}*COS(RADIANS({lon}-K_L0)))"


def _U(lon, lat):
    return f"(({_PX(lon, lat)})-K_Xc)*K_S+K_W/2"


def _V(lon, lat):
    return f"(({_PY(lon, lat)})-K_Yc)*K_S+K_H/2"


def _outline_rows():
    if _STATE["borders"] is not None:
        return _STATE["borders"]
    rows = []
    for code in [c for c, _ in CORE] + list(OUTLINES_CONTEXT):
        rows += [(code, lon, lat) for lon, lat in (OUTLINES.get(code) or OUTLINES_CONTEXT[code])]
        rows.append(("", None, None))
    return rows


def _graticule_rows():
    rows = []
    for lon in (5, 10, 15, 20, 25):
        rows += [(lon, lat) for lat in range(41, 57)] + [(None, None)]
    for lat in (45, 50, 55):
        rows += [(lon, lat) for lon in range(0, 31)] + [(None, None)]
    return rows


def build_map_data(wb, tsos: dict):
    """Every map coordinate is a FORMULA: lon/lat, projection (LAEA), zoom window of the selected country, chart units."""
    ws = wb["Map_Data"]
    n = last("subs")
    ws["A1"] = "Map_Data – helper sheet: location, projection, zoom and traffic light of every substation for the network map (all 13 countries)"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = ("Row n = row n in sheet Substations. Longitude and latitude come from D_Coordinates and are projected with the Lambert azimuthal equal-area projection (the European map standard). "
                "Map X/Y = (position − centre of the view window) × scale: the window follows the country selected on the Dashboard (All = whole region), so points, lines, borders and corridors zoom together. "
                "NA() in the point columns is intended: the chart does not draw such points.")
    ws["A2"].font = font(italic=True, size=9, color="595959")
    ws.merge_cells("A2:M2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 52
    for first, last_, text, kind in (("A", "H", "SUBSTATION, LOCATION AND MAP POSITION", "data"), ("I", "M", "LIGHT (view per Dashboard)", "calc"), ("O", "T", "COUNTRY OUTLINES (schematic)", "data"),
                                     ("V", "W", "PROJECTION, VIEW AND LABELS", "calc"), ("Y", "AC", "CHART: LIGHT PER COUNTRY", "calc"), ("AE", "AF", "TSO LIST", "data"),
                                     ("AH", "AI", "PLANNED CORRIDORS", "calc"), ("AK", "AQ", "VIEW WINDOW PER COUNTRY", "data"), ("AS", "AU", "COUNTRY LABELS", "calc"),
                                     ("AW", "BQ", "PROJECTED WINDOW CORNERS AND EXTENTS (km)", "calc"), ("BS", "BV", "GRATICULE", "calc"), ("BX", "BY", "SCALE BAR, FOUND SUBSTATION", "calc")):
        band(ws, first, last_, 3, text, kind)
    heads = {"A": "Substation", "B": "Node type", "C": "Country", "D": "Latitude", "E": "Longitude", "F": "Accuracy of the location", "G": "Map X", "H": "Map Y", "I": "Light",
             "J": "Point red", "K": "Point amber", "L": "Point green", "M": "Point grey", "O": "Country", "P": "Longitude", "Q": "Latitude", "R": "Map X", "S": "Map Y",
             "T": "Map Y selected", "V": "Legend text / parameter", "W": "Value", "Y": "Country", "Z": "Red", "AA": "Amber", "AB": "Green", "AC": "Grey", "AE": "TSO", "AF": "Country",
             "AH": "Corridor X", "AI": "Corridor Y", "AK": "View", "AL": "Lon from", "AM": "Lon to", "AN": "Lat from", "AO": "Lat to", "AP": "Label lon", "AQ": "Label lat",
             "AS": "Country", "AT": "Label X", "AU": "Label Y", "BN": "X from", "BO": "X to", "BP": "Y from", "BQ": "Y to", "BS": "Longitude", "BT": "Latitude", "BU": "Map X", "BV": "Map Y", "BX": "Map X", "BY": "Map Y"}
    for k_ in range(1, 9):
        heads[get_column_letter(49 + k_ - 1)] = f"X{k_}"
        heads[get_column_letter(57 + k_ - 1)] = f"Y{k_}"
    for letter, text in heads.items():
        header(ws[f"{letter}4"], "calc")
        ws[f"{letter}4"].value = text
    ws.row_dimensions[4].height = 34
    set_widths(ws, {"A": 28, "B": 16, "C": 9, "D": 11, "E": 11, "F": 36, "G": 9, "H": 9, "I": 8, "J": 9, "K": 9, "L": 9, "M": 9, "N": 3, "O": 9, "P": 9, "Q": 9, "R": 9, "S": 9, "T": 11,
                    "U": 3, "V": 46, "W": 12, "X": 3, "Y": 9, "Z": 7, "AA": 7, "AB": 7, "AC": 7, "AD": 3, "AE": 18, "AF": 9, "AG": 3, "AH": 10, "AI": 10, "AJ": 3, "AK": 8, "AL": 9, "AM": 9,
                    "AN": 9, "AO": 9, "AP": 9, "AQ": 9, "AR": 3, "AS": 9, "AT": 9, "AU": 9, "AV": 3, "BR": 3, "BW": 3, "AK": 18})
    KO = lambda c: f"D_Coordinates!${c}$5:${c}${R0 + SZ['coord'] - 1}"
    SNr = lambda k: f"Substations!${SN.L(k)}"
    for r in range(R0, n + 1):
        pos = f"MATCH($A{r},{KO('A')},0)"
        f = {
            "A": f'=IF({SNr("sub")}{r}="","",{SNr("sub")}{r})',
            "B": f'=IF($A{r}="","",{SNr("ntype")}{r})',
            "C": f'=IF($A{r}="","",{SNr("country")}{r})',
            "D": f'=IF($A{r}="","",IFERROR(IF(INDEX({KO("B")},{pos})="","",INDEX({KO("B")},{pos})),""))',
            "E": f'=IF($A{r}="","",IFERROR(IF(INDEX({KO("C")},{pos})="","",INDEX({KO("C")},{pos})),""))',
            "F": f'=IF($A{r}="","",IFERROR(INDEX({KO("D")},{pos})&"",""))',
            "G": f'=IF(OR($D{r}="",$E{r}=""),NA(),{_U(f"$E{r}", f"$D{r}")})',
            "H": f'=IF(OR($D{r}="",$E{r}=""),NA(),{_V(f"$E{r}", f"$D{r}")})',
            "I": f'=IF($A{r}="","",IF(K_View="Withdrawal",{SNr("lw")}{r},{SNr("lf")}{r}))',
        }
        for letter, name in (("J", "Red"), ("K", "Amber"), ("L", "Green"), ("M", "Grey")):
            show = ',K_ShowGrey="Show"' if name == "Grey" else ""
            f[letter] = f'=IF(AND({SNr("infilter")}{r}=1,$I{r}="{name}",ISNUMBER($H{r}){show}),$H{r},NA())'
        write_formulas(ws, r, f, {"D": "0.0000", "E": "0.0000", "G": "0.000", "H": "0.000", "J": "0.000", "K": "0.000", "L": "0.000", "M": "0.000"})
    # --- country outlines (fixed lon/lat, projected by formulas)
    for i, (code, lon, lat) in enumerate(_outline_rows()):
        r = R0 + i
        if code:
            ws[f"O{r}"], ws[f"P{r}"], ws[f"Q{r}"] = code, lon, lat
            for c in "OPQ":
                ws[f"{c}{r}"].font = BLUE_FONT
        write_formulas(ws, r, {"R": f'=IF($P{r}="",NA(),{_U(f"$P{r}", f"$Q{r}")})', "S": f'=IF($P{r}="",NA(),{_V(f"$P{r}", f"$Q{r}")})',
                               "T": f'=IF(AND(K_Country<>"All",$O{r}=K_Country,ISNUMBER($S{r})),$S{r},NA())'}, {"R": "0.000", "S": "0.000", "T": "0.000"})
    # --- graticule
    for i, (lon, lat) in enumerate(_graticule_rows()):
        r = R0 + i
        if lon is not None:
            ws[f"BS{r}"], ws[f"BT{r}"] = lon, lat
            ws[f"BS{r}"].font = ws[f"BT{r}"].font = BLUE_FONT
        write_formulas(ws, r, {"BU": f'=IF($BS{r}="",NA(),{_U(f"$BS{r}", f"$BT{r}")})', "BV": f'=IF($BS{r}="",NA(),{_V(f"$BS{r}", f"$BT{r}")})'}, {"BU": "0.000", "BV": "0.000"})
    # --- legend texts, projection constants and view parameters
    for ref, name, rng in (("V5", "Red, exhausted", "J"), ("V6", "Amber, tight", "K"), ("V7", "Green, free", "L"), ("V8", "Grey, no data", "M")):
        ws[ref] = f'="{name} ("&COUNT(${rng}${R0}:${rng}${n})&")"'
        color_formula(ws[ref])
    ws["V8"] = f'=IF(K_ShowGrey="Show","Grey, no data ("&COUNT($M${R0}:$M${n})&")","No-data substations hidden")'
    views = ["All"] + [c for c, _ in CORE] + list(REGIONS) + [FOUND]          # zoom windows: whole region, countries, regions, window around a chosen substation
    vlast = 5 + len(views)
    VW = lambda c: f"=INDEX(${c}$6:${c}${vlast},IFERROR(MATCH(K_Zoom,$AK$6:$AK${vlast},0),1))"
    params = [("V10", "Earth radius (km)", "W10", 6371, True), ("V11", "Central meridian of the projection (°E)", "W11", 10, True), ("V12", "Standard parallel of the projection (°N)", "W12", 52, True),
              ("V13", "Sine of the standard parallel", "W13", "=SIN(RADIANS(W12))", False), ("V14", "Cosine of the standard parallel", "W14", "=COS(RADIANS(W12))", False),
              ("V15", "Chart width (units)", "W15", MAP_W, True), ("V16", "Chart height (units)", "W16", MAP_H, True),
              ("V17", "View window X from (km, zoom of the sheet Map)", "W17", VW("BN"), False),
              ("V18", "View window X to (km)", "W18", VW("BO"), False),
              ("V19", "View window Y from (km)", "W19", VW("BP"), False),
              ("V20", "View window Y to (km)", "W20", VW("BQ"), False),
              ("V21", "Centre X of the window (km)", "W21", "=(W17+W18)/2", False), ("V22", "Centre Y of the window (km)", "W22", "=(W19+W20)/2", False),
              ("V23", "Scale: chart units per km (fits the window with a 6 % margin)", "W23", "=0.94*MIN(W15/(W18-W17),W16/(W20-W19))", False),
              ("V24", "Substations in the selection (counter for the Dashboard)", "W24", f'=COUNTIFS(Substations!${SN.L("infilter")}${R0}:${SN.L("infilter")}${n},1)', False)]
    params += [("V25", "Zoom window: 'Selection' follows the country filter of the Dashboard (cell C3 of the sheet Map)", "W25",
                '=IF(OR(Map!$C$3="",Map!$C$3="Selection"),K_Country,Map!$C$3)', False),
               ("V26", "Scale bar: length (km), about a fifth of the map width", "W26", "=IFERROR(INDEX($W$28:$W$34,MATCH(0.2*K_W/K_S,$W$28:$W$34,1)),$W$28)", False),
               ("V27", "Scale bar: label", "W27", '=W26&" km"', False),
               ("V28", "Scale bar: possible lengths (km), ascending", "W28", 5, True)]
    params += [(None, None, f"W{29 + i}", v_, True) for i, v_ in enumerate((10, 20, 50, 100, 200, 500))]
    params += [("V35", "Row of the substation chosen in the sheet Map (Find substation)", "W35", f'=IF(K_Find="","",IFERROR(MATCH(K_Find,$A${R0}:$A${n},0),""))', False),
               ("V36", "Longitude of that substation", "W36", f'=IF($W$35="","",INDEX($E${R0}:$E${n},$W$35))', False),
               ("V37", "Latitude of that substation", "W37", f'=IF($W$35="","",INDEX($D${R0}:$D${n},$W$35))', False)]
    for lab, text, cell, val, is_input in params:
        if lab:
            ws[lab] = text
        ws[cell] = val
        if is_input:
            ws[cell].font = BLUE_FONT
            ws[cell].fill = fill(L_GOLD)
        else:
            color_formula(ws[cell])
        ws[cell].number_format = "0.0000" if cell == "W23" else ("0.000" if cell in ("W13", "W14") else "General")
    for name, cell in (("K_R", "W10"), ("K_L0", "W11"), ("K_P1", "W12"), ("K_S1", "W13"), ("K_C1", "W14"), ("K_W", "W15"), ("K_H", "W16"), ("K_Xc", "W21"), ("K_Yc", "W22"), ("K_S", "W23"), ("K_Total", "W24"), ("K_Zoom", "W25"), ("K_BarKm", "W26"), ("K_FindRow", "W35")):
        wb.defined_names[name] = DefinedName(name, attr_text=f"Map_Data!${cell[0]}${cell[1:]}")
    # --- country chart table
    UWr = lambda k: f"Substations!${SN.L(k)}${R0}:${SN.L(k)}${n}"
    for i, (code, name) in enumerate(CORE):
        r = 6 + i
        ws[f"Y{r}"] = code
        ws[f"Y{r}"].font = BLUE_FONT
        for letter in ("Z", "AA", "AB", "AC"):
            one = lambda lc: f'COUNTIFS({UWr("country")},$Y{r},{UWr("ntype")},"Core node",{UWr(lc)},{letter}$5)'
            ws[f"{letter}{r}"] = f'=IF(K_View="Withdrawal",{one("lw")},{one("lf")})'
            color_formula(ws[f"{letter}{r}"])
    for letter, h_ in zip(("Z", "AA", "AB", "AC"), ("Red", "Amber", "Green", "Grey")):
        ws[f"{letter}5"] = h_
        ws[f"{letter}5"].font = font(bold=True)
    ws["Y5"] = "Country"
    for i, (t, c) in enumerate(tsos.items()):
        ws[f"AE{6 + i}"], ws[f"AF{6 + i}"] = t, c
        ws[f"AE{6 + i}"].font = ws[f"AF{6 + i}"].font = BLUE_FONT
    # --- planned corridors (three rows per project: from, to, gap)
    for i in range(SZ["exp"]):
        rl, base = R0 + i, R0 + 3 * i
        for k, (lat_c, lon_c) in enumerate((("H", "I"), ("K", "L"), (None, None))):
            r = base + k
            if lat_c:
                lo, la = f"D_Expansion!${lon_c}{rl}", f"D_Expansion!${lat_c}{rl}"
                ws[f"AH{r}"] = f'=IF(OR({la}="",{lo}=""),NA(),{_U(lo, la)})'
                ws[f"AI{r}"] = f'=IF(OR({la}="",{lo}=""),NA(),{_V(lo, la)})'
            else:
                ws[f"AH{r}"], ws[f"AI{r}"] = "=NA()", "=NA()"
            color_formula(ws[f"AH{r}"])
            color_formula(ws[f"AI{r}"])
            ws[f"AH{r}"].number_format = ws[f"AI{r}"].number_format = "0.000"
    # --- view windows, projected corners and extents
    ws["AK5"] = "Selection"
    ws["AK5"].font = BLUE_FONT
    for i, code in enumerate(views):
        r = 6 + i
        ws[f"AK{r}"] = code
        if code == FOUND:                                                   # window around the substation chosen in the sheet Map (whole region if none is chosen)
            hw, hh = FOUND_HALF
            for c, fml in (("AL", f"=IF(ISNUMBER($W$36),$W$36-{hw},$AL$6)"), ("AM", f"=IF(ISNUMBER($W$36),$W$36+{hw},$AM$6)"),
                           ("AN", f"=IF(ISNUMBER($W$37),$W$37-{hh},$AN$6)"), ("AO", f"=IF(ISNUMBER($W$37),$W$37+{hh},$AO$6)")):
                ws[f"{c}{r}"] = fml
        else:
            ws[f"AL{r}"], ws[f"AM{r}"], ws[f"AN{r}"], ws[f"AO{r}"] = VIEW.get(code) or REGIONS[code]
        if code in LABEL:
            ws[f"AP{r}"], ws[f"AQ{r}"] = LABEL[code]
        for c in ("AK", "AL", "AM", "AN", "AO", "AP", "AQ"):
            ws[f"{c}{r}"].font = BLUE_FONT
            color_formula(ws[f"{c}{r}"])
        mlon, mlat = f"($AL{r}+$AM{r})/2", f"($AN{r}+$AO{r})/2"
        pts = [(f"$AL{r}", f"$AN{r}"), (f"$AM{r}", f"$AN{r}"), (f"$AL{r}", f"$AO{r}"), (f"$AM{r}", f"$AO{r}"), (mlon, f"$AN{r}"), (mlon, f"$AO{r}"), (f"$AL{r}", mlat), (f"$AM{r}", mlat)]
        for k_, (plon, plat) in enumerate(pts):
            ws[f"{get_column_letter(49 + k_)}{r}"] = f"={_PX(plon, plat)}"
            ws[f"{get_column_letter(57 + k_)}{r}"] = f"={_PY(plon, plat)}"
            color_formula(ws[f"{get_column_letter(49 + k_)}{r}"])
            color_formula(ws[f"{get_column_letter(57 + k_)}{r}"])
        for c, fml in (("BN", f"=MIN(AW{r}:BD{r})"), ("BO", f"=MAX(AW{r}:BD{r})"), ("BP", f"=MIN(BE{r}:BL{r})"), ("BQ", f"=MAX(BE{r}:BL{r})")):
            ws[f"{c}{r}"] = fml
            color_formula(ws[f"{c}{r}"])
            ws[f"{c}{r}"].number_format = "0"
    for j, (code, _) in enumerate(CORE):
        r, vr = 6 + j, 7 + j
        ws[f"AS{r}"] = f'=AK{vr}&IF(Z{r}+AA{r}+AB{r}+AC{r}=0,"",CHAR(10)&ROUND((Z{r}+AA{r}+AB{r})/(Z{r}+AA{r}+AB{r}+AC{r})*100,0)&" %")'
        ws[f"AT{r}"] = f"={_U(f'$AP{vr}', f'$AQ{vr}')}"
        ws[f"AU{r}"] = f"={_V(f'$AP{vr}', f'$AQ{vr}')}"
        for c in ("AS", "AT", "AU"):
            color_formula(ws[f"{c}{r}"])
        ws[f"AT{r}"].number_format = ws[f"AU{r}"].number_format = "0.000"
    # scale bar (two points) and marker of the substation chosen in the sheet Map
    extra = {"BX5": "=0.03*K_W", "BY5": "=0.045*K_H", "BX6": "=BX5+K_BarKm*K_S", "BY6": "=BY5",
             "BX8": f'=IF($W$35="",NA(),INDEX($G${R0}:$G${n},$W$35))', "BY8": f'=IF($W$35="",NA(),INDEX($H${R0}:$H${n},$W$35))'}
    for ref_, fml in extra.items():
        ws[ref_] = fml
        color_formula(ws[ref_])
        ws[ref_].number_format = "0.000"
    wb.defined_names["L_Zoom"] = DefinedName("L_Zoom", attr_text=f"Map_Data!$AK$5:$AK${vlast}")
    wb.defined_names["L_Substations"] = DefinedName("L_Substations", attr_text=f"Substations!${SN.L('sub')}${R0}:${SN.L('sub')}${n}")
    wb.defined_names["K_Find"] = DefinedName("K_Find", attr_text="Map!$G$3")
    wb.defined_names["L_Countries"] = DefinedName("L_Countries", attr_text=f"Map_Data!$Y${MD_CORE_ROWS[0]}:$Y${MD_CORE_ROWS[1]}")
    wb.defined_names["L_TSOs"] = DefinedName("L_TSOs", attr_text=f"Map_Data!$AE${MD_TSO_ROWS[0]}:$AE${MD_TSO_ROWS[0] + len(tsos) - 1}")
    ws.freeze_panes = "B5"
    _fit_width(ws, title_rows="3:4")


def build_map_lines(wb):
    ws = wb["Map_Lines"]
    seg = SZ["seg"]
    ws["A1"] = "Map_Lines – helper sheet: network lines for the map (three rows per line: start, end, gap)"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = ("Each line of the sheet Lines is drawn as a straight segment between the map positions of its two substations (only where both are located). Lines inside the Dashboard selection "
                "(country and TSO) are grey, amber or red by status; all other lines turn light grey. The third row (NA) separates the segments. Column A is the row of the line in the sheet Lines.")
    ws["A2"].font = font(italic=True, size=9, color="595959")
    ws.merge_cells("A2:I2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 40
    band(ws, "A", "D", 3, "END POINT AND MAP POSITION", "data")
    band(ws, "F", "I", 3, "LINE COLOUR (values for the chart)", "calc")
    for letter, text in {"A": "Row in Lines", "B": "Position in Map_Data", "C": "Map X", "D": "Map Y", "F": "Y outside selection", "G": "Y grey", "H": "Y amber", "I": "Y red"}.items():
        header(ws[f"{letter}4"], "calc")
        ws[f"{letter}4"].value = text
    ws.row_dimensions[4].height = 34
    set_widths(ws, {"A": 11, "B": 11, "C": 9, "D": 9, "E": 3, "F": 11, "G": 9, "H": 9, "I": 9})
    n = last("subs")
    st, inf = f"Lines!${LN.L('status')}", f"Lines!${LN.L('infilter')}"
    for i in range(seg):
        rl = R0 + i
        base = R0 + 3 * i
        for k, src in enumerate((LN.L("sub1"), LN.L("sub2"), None)):
            r = base + k
            if src:
                ws[f"A{r}"] = rl
                f = {"B": f'=IF(Lines!${src}{rl}="","",IFERROR(MATCH(Lines!${src}{rl},Map_Data!$A${R0}:$A${n},0),""))',
                     "C": f'=IF($B{r}="",NA(),INDEX(Map_Data!$G${R0}:$G${n},$B{r}))', "D": f'=IF($B{r}="",NA(),INDEX(Map_Data!$H${R0}:$H${n},$B{r}))',
                     "F": f'=IF(AND(ISNUMBER($D{r}),{inf}{rl}=0),$D{r},NA())',
                     "G": f'=IF(AND(ISNUMBER($D{r}),{inf}{rl}=1,{st}{rl}<>"Highly loaded",{st}{rl}<>"Bottleneck"),$D{r},NA())',
                     "H": f'=IF(AND(ISNUMBER($D{r}),{inf}{rl}=1,{st}{rl}="Highly loaded"),$D{r},NA())',
                     "I": f'=IF(AND(ISNUMBER($D{r}),{inf}{rl}=1,{st}{rl}="Bottleneck"),$D{r},NA())'}
            else:
                f = {"B": '=""', "C": "=NA()", "D": "=NA()", "F": "=NA()", "G": "=NA()", "H": "=NA()", "I": "=NA()"}
            write_formulas(ws, r, f, {"C": "0.000", "D": "0.000", "F": "0.000", "G": "0.000", "H": "0.000", "I": "0.000"})
    ws.freeze_panes = "A5"
    _fit_width(ws, title_rows="3:4")


def _axis_hidden(ax, lo, hi):
    ax.scaling.min, ax.scaling.max = lo, hi
    ax.delete = False
    ax.majorGridlines = None
    ax.tickLblPos = "none"
    ax.majorTickMark = "none"
    ax.minorTickMark = "none"
    ax.number_format = ";;;"          # no numbers even where tickLblPos is ignored
    ax.spPr = GraphicalProperties(ln=LineProperties(noFill=True))


def add_map(wb, ws, anchor, width_cm, marker=6):
    """Scatter chart: network map of the Core region; zooms on the window chosen in the sheet Map (formula-driven).

    The plot area fills the whole chart: no title, no legend and no axis labels inside the chart (title and legend are cells of the sheet). The proportions of the map
    therefore depend on one thing only, the size of the chart object: width : height = MAP_W : MAP_H, so one chart unit is the same distance in both directions.
    Background: the first version set the plot area through plot_area.layout. openpyxl overwrites that attribute when it saves (ChartBase._write), the file contained no
    layout, Excel sized the plot area itself between title and legend, and the map was squeezed. The layout now sits on chart.layout and the aspect ratio of the chart
    object is locked (connections.patch_map_charts).
    """
    kd, kl = wb["Map_Data"], wb["Map_Lines"]
    n, seg_last, n_out, n_grat = last("subs"), R0 + 3 * SZ["seg"] - 1, len(_outline_rows()), len(_graticule_rows())
    exp_last = R0 + 3 * SZ["exp"] - 1
    ref = lambda sh, c, r1, r2: Reference(sh, min_col=c, min_row=r1, max_row=r2)
    ch = ScatterChart()
    ch.scatterStyle = "lineMarker"
    ch.title = None
    ch.legend = None
    ch.roundedCorners = False
    ch.width, ch.height = width_cm, round(width_cm * MAP_H / MAP_W, 2)

    def line_series(xs, ys, color, width, name, dash=None):
        s = Series(ys, xs)
        s.tx = SeriesLabel(v=name)
        s.marker.symbol = "none"
        s.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.width = width
        if dash:
            s.graphicalProperties.line.dashStyle = dash
        s.smooth = False
        return s

    def point_series(c_y, color, label_cell):
        s = Series(ref(kd, c_y, R0, n), ref(kd, 7, R0, n))
        s.tx = SeriesLabel(strRef=StrRef(f"'Map_Data'!{label_cell}"))
        s.marker.symbol = "circle"
        s.marker.size = marker
        s.marker.graphicalProperties = GraphicalProperties(solidFill=color)
        s.marker.graphicalProperties.line.solidFill = "FFFFFF"
        s.graphicalProperties.line.noFill = True
        s.smooth = False
        return s

    def label_series(c_x, c_y, row, label_cell, position):
        s = Series(ref(kd, c_y, row, row), ref(kd, c_x, row, row))
        s.tx = SeriesLabel(strRef=StrRef(f"'Map_Data'!{label_cell}"))
        s.marker.symbol = "none"
        s.graphicalProperties.line.noFill = True
        s.dLbls = DataLabelList()
        s.dLbls.showSerName = True
        for a_ in ("showVal", "showCatName", "showLegendKey", "showPercent"):
            setattr(s.dLbls, a_, False)
        s.dLbls.position = position
        return s

    ox, oe = ref(kd, 18, R0, R0 + n_out - 1), R0 + n_out - 1
    lx = ref(kl, 3, R0, seg_last)
    ch.series.append(line_series(ref(kd, 73, R0, R0 + n_grat - 1), ref(kd, 74, R0, R0 + n_grat - 1), "D3E3F3", 6350, "Graticule"))
    ch.series.append(line_series(ox, ref(kd, 19, R0, oe), "7B8FB5", 9525, "Country borders"))
    ch.series.append(line_series(ox, ref(kd, 20, R0, oe), "0B4BFF", 22225, "Selected country"))
    ch.series.append(line_series(lx, ref(kl, 6, R0, seg_last), "DAD8D3", 6350, "Lines outside the selection"))
    ch.series.append(line_series(lx, ref(kl, 7, R0, seg_last), "9E9B96", 9525, "Lines"))
    ch.series.append(line_series(lx, ref(kl, 8, R0, seg_last), "F4B400", 19050, "Lines highly loaded"))
    ch.series.append(line_series(lx, ref(kl, 9, R0, seg_last), "C53532", 19050, "Lines bottleneck"))
    ch.series.append(line_series(ref(kd, 34, R0, exp_last), ref(kd, 35, R0, exp_last), "0B4BFF", 22225, "Planned corridors", "dash"))
    for j in range(len(CORE)):                                              # country codes with the share of substations that have data
        ch.series.append(label_series(46, 47, 6 + j, f"$AS${6 + j}", "ctr"))
    ch.series.append(point_series(13, "B9B6B1", "$V$8"))
    ch.series.append(point_series(12, "6ABF30", "$V$7"))
    ch.series.append(point_series(11, "F4B400", "$V$6"))
    ch.series.append(point_series(10, "C53532", "$V$5"))
    ch.series.append(line_series(ref(kd, 76, R0, R0 + 1), ref(kd, 77, R0, R0 + 1), NAVY, 25400, "Scale bar"))
    ch.series.append(label_series(76, 77, R0 + 1, "$W$27", "r"))
    found = Series(ref(kd, 77, R0 + 3, R0 + 3), ref(kd, 76, R0 + 3, R0 + 3))    # ring around the substation chosen in the sheet Map
    found.tx = SeriesLabel(v="Found substation")
    found.marker.symbol = "circle"
    found.marker.size = 17
    found.marker.graphicalProperties = GraphicalProperties(noFill=True)
    found.marker.graphicalProperties.line.solidFill = "0B4BFF"
    found.marker.graphicalProperties.line.width = 28575
    found.graphicalProperties.line.noFill = True
    ch.series.append(found)
    for ax, hi in ((ch.x_axis, MAP_W), (ch.y_axis, MAP_H)):
        _axis_hidden(ax, 0, hi)
        ax.delete = True                                                    # no axis at all: nothing next to the plot area can shift it
    ch.layout = Layout(manualLayout=ManualLayout(layoutTarget="inner", xMode="edge", yMode="edge", x=0.0, y=0.0, w=1.0, h=1.0))
    ch.graphical_properties = GraphicalProperties(ln=LineProperties(solidFill="B9B6B1", w=6350))
    ch.plot_area.graphicalProperties = GraphicalProperties(solidFill="EAF5FF", ln=LineProperties(noFill=True))
    ws.add_chart(ch, anchor)


def _legend(ws, row, col_idx, glyph, color, text):
    """Legend entry in two cells: coloured symbol and text (a legend inside the chart would take room from the map and shift its proportions)."""
    g = ws.cell(row, col_idx, glyph)
    g.font = font(bold=True, size=11, color=color)
    g.alignment = Alignment(horizontal="center", vertical="center")
    t = ws.cell(row, col_idx + 1, text)
    t.font = font(size=9, color="404040")
    t.alignment = Alignment(vertical="center")


def _chart_width_cm(ws, first_col, last_col):
    """Width of a column range in cm (column width in characters -> pixels at 96 dpi, as Excel does for the default font)."""
    px = sum(int(ws.column_dimensions[col(j)].width * 7 + 5) for j in range(first_col, last_col + 1))
    return round(px / 96 * 2.54, 2)


LEGEND_POINTS = [("●", "C53532", "=Map_Data!$V$5"), ("●", "F4B400", "=Map_Data!$V$6"), ("●", "6ABF30", "=Map_Data!$V$7"), ("●", "B9B6B1", "=Map_Data!$V$8")]
LEGEND_LINES = [("▬", "C53532", "Line: bottleneck"), ("▬", "F4B400", "Line: highly loaded"), ("▬", "9E9B96", "Line in the selection"), ("- - -", "0B4BFF", "Planned corridor (schematic)")]


def build_map_sheet(wb, tsos: dict):
    """Large map with zoom, substation search, legend and the quality of the locations per country."""
    ws = wb["Map"]
    n = last("subs")
    widths = {"M": 2, "N": 24, "O": 13, "P": 13, "Q": 13, "R": 13}
    for i in range(6):
        widths[col(2 * i + 1)], widths[col(2 * i + 2)] = 3, 23
    set_widths(ws, widths)
    ws["A1"] = "Map – transmission grid of the Core region with traffic lights"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = ("Each point is a substation, each line a circuit between two substations (drawn straight, not along the real route). Colours follow the filters of the Dashboard. "
                "Gold cells: choose the zoom window and, if you like, a substation to mark on the map.")
    ws["A2"].font = font(italic=True, size=9, color="595959")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:L2")
    ws.row_dimensions[2].height = 28
    for ref_, text in (("B3", "Zoom to"), ("F3", "Find substation")):
        ws[ref_] = text
        ws[ref_].font = font(size=9, bold=True, color="7B7974")
        ws[ref_].alignment = Alignment(horizontal="right", vertical="center")
    for ref_, merged, val in (("C3", "C3:D3", "Selection"), ("G3", "G3:H3", None)):
        ws[ref_] = val
        for cell in ws[merged][0]:
            cell.fill = fill(L_GOLD)
            cell.border = BORDER
        ws[ref_].font = font(color="0B4BFF", bold=True)
        ws[ref_].alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(merged)
    dv_zoom = DataValidation(type="list", formula1="L_Zoom", allow_blank=False)
    dv_find = DataValidation(type="list", formula1="L_Substations", allow_blank=True, showErrorMessage=False)       # any text may be typed; unknown names show 'not found'
    for dv, ref_ in ((dv_zoom, "C3"), (dv_find, "G3")):
        ws.add_data_validation(dv)
        dv.add(ws[ref_])
    ws["J3"] = "Filters (view, country, TSO): Dashboard"
    ws["J3"].hyperlink = "#'Dashboard'!D3"
    ws["J3"].font = font(size=9, color="0B4BFF", underline="single")
    ws["J3"].alignment = Alignment(vertical="center")
    ws.row_dimensions[3].height = 24
    ws["B4"] = ('="Shown: view "&K_View&", country "&K_Country&", TSO "&K_TSO&", substations without data "&IF(K_ShowGrey="Show","shown","hidden")&". Zoom window: "&K_Zoom&"."')
    ws["B4"].font = font(size=8, color="7B7974")
    ws.merge_cells("B4:L4")
    ws.row_dimensions[4].height = 15
    for i, (g, c, t) in enumerate(LEGEND_POINTS + [("◯", "0B4BFF", "Found substation"), ("▬", NAVY, '=Map_Data!$W$27&" (scale bar)"')]):
        _legend(ws, 5, 2 * i + 1, g, c, t)
    for i, (g, c, t) in enumerate(LEGEND_LINES[:3] + [("▬", "DAD8D3", "Line outside the selection"), LEGEND_LINES[3], ("▬", "0B4BFF", "Border of the selected country")]):
        _legend(ws, 6, 2 * i + 1, g, c, t)
    ws.row_dimensions[5].height = ws.row_dimensions[6].height = 18
    ws.row_dimensions[7].height = 6
    add_map(wb, ws, "A8", _chart_width_cm(ws, 1, 12), marker=7)

    # --- side panel: the chosen substation
    band(ws, "N", "R", 3, "Selected substation", "result")
    idx = lambda k: f'=IF(K_FindRow="","",INDEX(Substations!${SN.L(k)}${R0}:${SN.L(k)}${n},K_FindRow))'
    rows = [("Substation", '=IF(K_Find="","choose in cell G3",IF(K_FindRow="","not found: "&K_Find,K_Find))', None, 16),
            ("Country", idx("country"), None, 16), ("TSO", idx("tso"), None, 16), ("Light feed-in", idx("lf"), None, 16), ("Light withdrawal", idx("lw"), None, 16),
            ("Highest utilization", idx("umax"), "0%", 16), ("Reason", idx("reason"), None, 44),
            ("Location on the map", f'=IF(K_FindRow="","",INDEX(Map_Data!$F${R0}:$F${n},K_FindRow))', None, 30)]
    for i, (label, fml, fmt, height) in enumerate(rows):
        r = 4 + i
        ws.cell(r, 14, label).font = font(size=9, color="595959")
        ws.cell(r, 14).alignment = Alignment(vertical="top")
        c = ws.cell(r, 15, fml)
        color_formula(c)
        c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        if fmt:
            c.number_format = fmt
        ws.merge_cells(start_row=r, start_column=15, end_row=r, end_column=18)
        for j in range(14, 19):
            ws.cell(r, j).border = BORDER
        ws.row_dimensions[r].height = height
    ws["O4"].font = font(bold=True, color=NAVY)
    add_light_cf(ws, "O7:O8")

    # --- side panel: quality of the locations per country
    r0 = 13
    band(ws, "N", "R", r0, "Location of the substations per country", "result")
    _tbl_header(ws, r0 + 1, ["Country", "Core substations", "Exact", "Approximate", "Not on the map"], first_col=14)
    for i, (code, name) in enumerate(CORE):
        r = r0 + 2 + i
        ws.cell(r, 14, code).font = font(color=NAVY)
        f = {"O": f'=COUNTIFS({KD("country")},$N{r},{KD("ntype")},"Core node")',
             "P": f'=COUNTIFS({KD("country")},$N{r},{KD("ntype")},"Core node",{KD("acc")},"exact*")',
             "Q": f'=SUMPRODUCT(({KD("country")}=$N{r})*({KD("ntype")}="Core node")*ISNUMBER({KD("x")}))-P{r}',
             "R": f"=O{r}-P{r}-Q{r}"}
        write_formulas(ws, r, f, {k: "#,##0" for k in "OPQR"})
        for c in "NOPQR":
            ws[f"{c}{r}"].border = BORDER
            ws[f"{c}{r}"].alignment = Alignment(horizontal="center")
    rt = r0 + 2 + len(CORE)
    ws.cell(rt, 14, "Total").font = font(bold=True, color=NAVY)
    ws.cell(rt, 14).alignment = Alignment(horizontal="center")
    for c in "OPQR":
        cell = ws[f"{c}{rt}"]
        cell.value = f"=SUM({c}{r0 + 2}:{c}{rt - 1})"
        cell.font = font(bold=True, color=NAVY)
        cell.number_format = "#,##0"
        cell.alignment = Alignment(horizontal="center")
        cell.border = Border(top=Side(style="thin", color="000F47"))
    ws.cell(rt + 1, 14, "Exact: OpenStreetMap or TSO data. Approximate: place of the same-named locality or estimate from the neighbouring substations.").font = font(size=8, color="7B7974")
    ws.cell(rt + 1, 14).alignment = WRAP_TOP
    ws.merge_cells(start_row=rt + 1, start_column=14, end_row=rt + 1, end_column=18)
    ws.row_dimensions[rt + 1].height = 26

    # --- side panel: how to read the map
    rh = rt + 3
    band(ws, "N", "R", rh, "How to read the map", "result")
    notes = ["A line without coloured points is a circuit without JAO utilization data. No data does not mean uncritical.",
             "Lines are straight connections between two substations. Planned corridors are schematic, their endpoints approximate places.",
             "Proportions are fixed: the chart keeps its ratio of width to height when it is resized. The scale bar shows the distance.",
             "Borders: " + _STATE["borders_source"] + ".",
             "Map with a real background (roads, towns): open network_map.html from the GitHub release in a browser."]
    for i, text in enumerate(notes):
        r = rh + 1 + i
        ws.cell(r, 14, text).font = font(size=9)
        ws.cell(r, 14).alignment = WRAP_TOP
        ws.merge_cells(start_row=r, start_column=14, end_row=r, end_column=18)
        ws.row_dimensions[r].height = max(28, row_height(text, 76 * 1.05, line_pt=12))
    ws.sheet_view.zoomScale = 85
    _fit_width(ws)


# --------------------------------------------------------------------------- Dashboard
def build_dashboard(wb, data, tsos: dict):
    ws = wb["Dashboard"]
    set_widths(ws, {"A": 8, "B": 26, "C": 9, "D": 17, "E": 15, "F": 11, "G": 12, "H": 15, "I": 12, "J": 20, "K": 3, "L": 2,
                    "M": 3, "N": 21, "O": 3, "P": 21, "Q": 3, "R": 21, "S": 3, "T": 21})
    n = last("subs")
    UW = lambda k: f"Substations!${SN.L(k)}${R0}:${SN.L(k)}${n}"
    LT = lambda k: f"Lines!${LN.L(k)}${R0}:${LN.L(k)}${last('lines')}"
    TR = lambda k: f"Transformers!${TN.L(k)}${R0}:${TN.L(k)}${last('trafos')}"
    wb.defined_names["K_View"] = DefinedName("K_View", attr_text="Dashboard!$B$3")
    wb.defined_names["K_Country"] = DefinedName("K_Country", attr_text="Dashboard!$D$3")
    wb.defined_names["K_TSO"] = DefinedName("K_TSO", attr_text="Dashboard!$F$3")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    codes = [c for c, _ in CORE]

    # --- 1 title, key message, selection, data basis
    ws["A1"] = "Dashboard – How full is the grid?"
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    ws["A2"] = ('=IFERROR(IF(AND(K_Country="All",K_TSO="All"),"",IF(K_Country="All","",K_Country)&IF(AND(K_Country<>"All",K_TSO<>"All"),", ","")&IF(K_TSO="All","",K_TSO)&": ")'
                '&A7&" of "&(A7+C7+E7)&" assessed substations exhausted, "&C7&" tight, "&G7&" without data"&IF(I7>0,", highest utilization "&ROUND(I7*100,0)&" % at "&B15,""),"No data for this selection")')
    ws["A2"].font = font(bold=True, size=12, color=NAVY)
    ws["A2"].alignment = Alignment(vertical="center")
    ws.merge_cells("A2:J2")
    ws.row_dimensions[2].height = 26
    for ref, txt, al in (("A3", "View", "left"), ("C3", "Country", "right"), ("E3", "TSO", "right")):
        ws[ref] = txt
        ws[ref].font = font(size=9, bold=True, color="7B7974")
        ws[ref].alignment = Alignment(vertical="center", horizontal=al)
    for ref, val in (("B3", PRESET["view"]), ("D3", PRESET["country"]), ("F3", PRESET["tso"])):
        ws[ref] = val
        ws[ref].fill = fill(L_GOLD)
        ws[ref].font = font(color="0B4BFF", bold=True)
        ws[ref].border = BORDER
        ws[ref].alignment = Alignment(horizontal="center", vertical="center")
    ws["G3"].fill = fill(L_GOLD)
    ws.merge_cells("F3:G3")
    dvs = [(DataValidation(type="list", formula1='"Feed-in,Withdrawal"', allow_blank=False), "B3"),
           (DataValidation(type="list", formula1='"All,' + ",".join(codes) + '"', allow_blank=False), "D3"),
           (DataValidation(type="list", formula1='"All,' + ",".join(tsos) + '"', allow_blank=False), "F3")]
    for dv, ref in dvs:
        ws.add_data_validation(dv)
        dv.add(ws[ref])
    ws["H3"] = "No-data nodes"
    ws["H3"].font = font(size=9, bold=True, color="7B7974")
    ws["H3"].alignment = Alignment(vertical="center", horizontal="right")
    ws["I3"] = PRESET["grey"]
    ws["I3"].fill = fill(L_GOLD)
    ws["I3"].font = font(color="0B4BFF", bold=True)
    ws["I3"].border = BORDER
    ws["I3"].alignment = Alignment(horizontal="center", vertical="center")
    ws["J3"].fill = fill(L_GOLD)
    ws.merge_cells("I3:J3")
    dv_g = DataValidation(type="list", formula1='"Hide,Show"', allow_blank=False)
    ws.add_data_validation(dv_g)
    dv_g.add(ws["I3"])
    wb.defined_names["K_ShowGrey"] = DefinedName("K_ShowGrey", attr_text="Dashboard!$I$3")
    ws.row_dimensions[3].height = 26
    ws["A4"] = ('=IFERROR("Window "&MONTH(P_From)&"/"&YEAR(P_From)&" to "&MONTH(P_To)&"/"&YEAR(P_To)&", scenario "&LOWER(P_Scenario)&", data as of "&'
                + meta_ref("created_utc") + '&" UTC, network model "&' + meta_ref("sgm_release") + ',"No utilization data in the window")')
    ws["A4"].font = font(size=8, color="7B7974")
    ws.merge_cells("A4:J4")
    ws.row_dimensions[4].height = 16
    ws.row_dimensions[5].height = 6

    # --- 2 KPI tiles (follow view, country and TSO)
    def lightcount(name):
        return (f'=IF(K_View="Withdrawal",COUNTIFS({UW("infilter")},1,{UW("lw")},"{name}"),COUNTIFS({UW("infilter")},1,{UW("lf")},"{name}"))')

    tiles = [("A", "B", "Red", lightcount("Red"), "Red", "0", "exhausted"), ("C", "D", "Amber", lightcount("Amber"), "Amber", "0", "tight"),
             ("E", "F", "Green", lightcount("Green"), "Green", "0", "free"), ("G", "H", "Grey", lightcount("Grey"), "Grey", "0", "no data"),
             ("I", "J", "Highest utilization", f'=IFERROR(_xlfn.MAXIFS({UW("umax")},{UW("infilter")},1),0)', None, "0%", None)]
    white = Side(style="thick", color="FFFFFF")
    for c1, c2, cap, val, light, fmt, word in tiles:
        i1, i2 = column_index_from_string(c1), column_index_from_string(c2)
        for rr in (6, 7, 8, 9):
            for jj in range(i1, i2 + 1):
                cell = ws.cell(rr, jj)
                cell.fill = fill(L_BLUE)
                cell.border = Border(left=white, right=white, top=Side(style="thick", color=AMPEL[light][0]) if (light and rr == 6) else None)
        ws.cell(6, i1, cap).font = font(bold=True, size=9, color=NAVY)
        ws.cell(7, i1, val).font = font(bold=True, size=26, color=NAVY)
        ws.cell(7, i1).number_format = fmt
        if light == "Grey":
            sub = '=IF(K_Total=0,"","no data, "&ROUND(G7/K_Total*100,0)&" % of "&K_Total&" substations")'
        elif light:
            sub = f'=IF(A7+C7+E7=0,"","{word}, "&ROUND({c1}7/(A7+C7+E7)*100,1)&" % of "&(A7+C7+E7)&" assessed")'
        else:
            sub = '=IF(B15="","",B15&", "&C15)'
        ws.cell(9, i1, sub)
        ws.cell(9, i1).font = font(size=8, color="595959")
        for rr in (6, 7, 9):
            ws.cell(rr, i1).alignment = center
        for r1, r2 in ((6, 6), (7, 8), (9, 9)):
            ws.merge_cells(start_row=r1, start_column=i1, end_row=r2, end_column=i2)
    for rr, hh in ((6, 20), (7, 24), (8, 24), (9, 18)):
        ws.row_dimensions[rr].height = hh
    ws["A10"] = f'=IFERROR(IF({meta_ref("note")}="","",{meta_ref("note")}),"")'
    ws["A10"].font = font(bold=True, color="C53532", size=9)
    ws.merge_cells("A10:J10")
    ws["A10"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[10].height = 24
    ws["A11"] = ('="Rules: red from "&ROUND(P_RedShare*100,0)&" % of hours above 100 % utilization, amber from "&ROUND(P_AmberShare*100,0)&" % of hours above "'
                 '&ROUND(P_AmberUtil*100,0)&" %, green below, grey means no data (not uncritical). Each substation takes the worse of its most heavily loaded network element and the connection status its TSO publishes."')
    ws["A11"].font = font(size=8, color="7B7974")
    ws["A11"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A11:J11")
    ws.row_dimensions[11].height = 24
    ws.row_dimensions[12].height = 8

    # --- 3 ranking (full width)
    band(ws, "A", "J", 13, "The ten most heavily loaded substations", "result")
    _tbl_header(ws, 14, ["Rank", "Substation", "Country", "TSO", "Highest utilization", "Light", "Bottleneck elements", "Highly loaded elements", "Elements with data", "Rest capacity (MW)"])
    for k in range(1, 11):
        r = 14 + k
        ws.cell(r, 1, k).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(r, 1).font = font(color=NAVY)
        pos = f'MATCH($A{r},{UW("rank")},0)'
        for c, fml, fmt in (("B", f'=IFERROR(INDEX({UW("sub")},{pos}),"")', None), ("C", f'=IFERROR(INDEX({UW("country")},{pos}),"")', None),
                            ("D", f'=IFERROR(INDEX({UW("tso")},{pos}),"")', None), ("E", f'=IFERROR(INDEX({UW("umax")},{pos}),"")', "0%"),
                            ("F", f'=IFERROR(IF(K_View="Withdrawal",INDEX({UW("lw")},{pos}),INDEX({UW("lf")},{pos})),"")', None),
                            ("G", f'=IFERROR(INDEX({UW("nbott")},{pos}),"")', "0"), ("H", f'=IFERROR(INDEX({UW("nhigh")},{pos}),"")', "0"),
                            ("I", f'=IFERROR(INDEX({UW("nass")},{pos}),"")', "0"), ("J", f'=IFERROR(INDEX({UW("rest")},{pos}),"")', "#,##0")):
            cell = ws[f"{c}{r}"]
            cell.value = fml
            color_formula(cell)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="left" if c in ("B", "D", "E") else "center", vertical="center")
            if fmt:
                cell.number_format = fmt
        ws[f"B{r}"].font = font(bold=True, color=NAVY)
        ws.row_dimensions[r].height = 26
    add_light_cf(ws, "F15:F24")
    ws.conditional_formatting.add("E15:E24", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1.4, color="82BAFF", showValue=True))
    ws.conditional_formatting.add("E15:E24", CellIsRule(operator="greaterThanOrEqual", formula=["1"], font=Font(color="C53532", bold=True)))

    # --- 4 details (collapsed)
    band(ws, "A", "J", 27, "Details", "result")
    d0 = 29
    _tbl_header(ws, d0, ["Status", "", "Lines", "Tie-lines", "Transformers"])
    ws.merge_cells(f"A{d0}:B{d0}")
    for i, name in enumerate(["Bottleneck", "Highly loaded", "Uncritical", "Too little data", "No data"]):
        r = d0 + 1 + i
        ws.cell(r, 1, name).border = BORDER
        ws.merge_cells(f"A{r}:B{r}")
        ws[f"C{r}"] = f'=COUNTIFS({LT("status")},$A{r},{LT("type")},"<>Tie-line")'
        ws[f"D{r}"] = f'=COUNTIFS({LT("status")},$A{r},{LT("type")},"Tie-line")'
        ws[f"E{r}"] = f'=COUNTIF({TR("status")},$A{r})'
        for c in "CDE":
            color_formula(ws[f"{c}{r}"])
            ws[f"{c}{r}"].border = BORDER
    _sum_row(ws, d0 + 6, d0 + 1, d0 + 5, ["C", "D", "E"])
    add_status_cf(ws, f"A{d0 + 1}:A{d0 + 5}")

    r2 = d0 + 9
    _tbl_header(ws, r2, ["Country", "", "Lines", "Tie-lines", "Transformers", "Substations", "Elements with data", "Share with data", "Bottleneck", "Highly loaded"])
    ws.merge_cells(f"A{r2}:B{r2}")
    for i, (code, name) in enumerate(CORE):
        r = r2 + 1 + i
        ws.cell(r, 1, code).font = font(color=NAVY)
        ws.merge_cells(f"A{r}:B{r}")
        ws[f"C{r}"] = f'=COUNTIFS({LT("country")},$A{r},{LT("type")},"<>Tie-line")'
        ws[f"D{r}"] = f'=COUNTIFS({LT("country")},$A{r},{LT("type")},"Tie-line")'
        ws[f"E{r}"] = f'=COUNTIF({TR("country")},$A{r})'
        ws[f"F{r}"] = f'=COUNTIFS({UW("country")},$A{r},{UW("ntype")},"Core node")'
        ws[f"G{r}"] = f'=SUMIFS({LT("assessed")},{LT("country")},$A{r})+SUMIFS({TR("assessed")},{TR("country")},$A{r})'
        ws[f"H{r}"] = f'=IF(C{r}+D{r}+E{r}=0,"",G{r}/(C{r}+D{r}+E{r}))'
        ws[f"I{r}"] = f'=COUNTIFS({LT("country")},$A{r},{LT("status")},"Bottleneck")+COUNTIFS({TR("country")},$A{r},{TR("status")},"Bottleneck")'
        ws[f"J{r}"] = f'=COUNTIFS({LT("country")},$A{r},{LT("status")},"Highly loaded")+COUNTIFS({TR("country")},$A{r},{TR("status")},"Highly loaded")'
        for c in "CDEFGHIJ":
            color_formula(ws[f"{c}{r}"])
            ws[f"{c}{r}"].border = BORDER
            ws[f"{c}{r}"].number_format = "0%" if c == "H" else "#,##0"
    e2 = r2 + len(CORE)
    _sum_row(ws, e2 + 1, r2 + 1, e2, ["C", "D", "E", "F", "G", "I", "J"])

    r3 = e2 + 4
    _tbl_header(ws, r3, ["TSO", "", "Country", "Lines", "Transformers", "Substations", "Elements with data", "Share with data", "Bottleneck", "Highly loaded"])
    ws.merge_cells(f"A{r3}:B{r3}")
    for i, (tso, cc) in enumerate(tsos.items()):
        r = r3 + 1 + i
        ws.cell(r, 1, tso).font = font(color=NAVY)
        ws.merge_cells(f"A{r}:B{r}")
        ws[f"C{r}"] = cc
        ws[f"D{r}"] = f'=COUNTIF({LT("tso")},$A{r})'
        ws[f"E{r}"] = f'=COUNTIF({TR("tso")},$A{r})'
        ws[f"F{r}"] = f'=COUNTIFS({UW("tso")},$A{r},{UW("ntype")},"Core node")'
        ws[f"G{r}"] = f'=SUMIFS({LT("assessed")},{LT("tso")},$A{r})+SUMIFS({TR("assessed")},{TR("tso")},$A{r})'
        ws[f"H{r}"] = f'=IF(D{r}+E{r}=0,"",G{r}/(D{r}+E{r}))'
        ws[f"I{r}"] = f'=COUNTIFS({LT("tso")},$A{r},{LT("status")},"Bottleneck")+COUNTIFS({TR("tso")},$A{r},{TR("status")},"Bottleneck")'
        ws[f"J{r}"] = f'=COUNTIFS({LT("tso")},$A{r},{LT("status")},"Highly loaded")+COUNTIFS({TR("tso")},$A{r},{TR("status")},"Highly loaded")'
        ws[f"C{r}"].font = BLUE_FONT
        for c in "CDEFGHIJ":
            ws[f"{c}{r}"].border = BORDER
            if c != "C":
                color_formula(ws[f"{c}{r}"])
                ws[f"{c}{r}"].number_format = "0%" if c == "H" else "#,##0"
    e3 = r3 + len(tsos)
    _sum_row(ws, e3 + 1, r3 + 1, e3, ["D", "E", "F", "G", "I", "J"])

    # grid expansion: planned and under-construction projects (BBPlG), shown on the map as dashed corridors
    r4 = e3 + 4
    _tbl_header(ws, r4, ["Grid expansion project (Europe)", "", "Countries", "TSO(s)", "Capacity (MW)", "Status", "Planned year", "Built", "Grid today at start", "Grid today at end"])
    ws.merge_cells(f"A{r4}:B{r4}")
    ws.row_dimensions[r4].height = 32
    d = "D_Expansion"

    def light(link_col, rd):
        return (f'=IF({d}!$C{rd}="","",IF({d}!${link_col}{rd}="","n/a",IFERROR(IF(K_View="Withdrawal",INDEX({UW("lw")},MATCH({d}!${link_col}{rd},{UW("sub")},0)),'
                f'INDEX({UW("lf")},MATCH({d}!${link_col}{rd},{UW("sub")},0))),"n/a")))')

    for i in range(SZ["exp"]):
        r, rd = r4 + 1 + i, R0 + i
        f = {"A": f'=IF({d}!C{rd}="","",{d}!C{rd})', "C": f'=IF($A{r}="","",SUBSTITUTE({d}!Y{rd},";",", "))', "D": f'=IF($A{r}="","",{d}!F{rd}&"")',
             "E": f'=IF(OR($A{r}="",{d}!O{rd}=""),"",{d}!O{rd})', "F": f'=IF($A{r}="","",{d}!S{rd}&"")', "G": f'=IF(OR($A{r}="",{d}!T{rd}=""),"",{d}!T{rd})',
             "H": f'=IF(OR($A{r}="",{d}!Q{rd}="",{d}!R{rd}=""),"",{d}!R{rd}/{d}!Q{rd})', "I": light("M", rd), "J": light("N", rd)}
        write_formulas(ws, r, f, {"E": "#,##0", "G": "0", "H": "0%"})
        ws.merge_cells(f"A{r}:B{r}")
        for c in "ACDEFGHIJ":
            ws[f"{c}{r}"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="left" if c in "ACD" else "center")
        ws.row_dimensions[r].height = 28
    e4 = r4 + SZ["exp"]
    add_light_cf(ws, f"I{r4 + 1}:J{e4}")
    for text, bg in (("Under construction", "DDF0CC"), ("Permitting", "FBEDBF"), ("Planning", "EDEDED"), ("Listed", "F6F6F6")):
        ws.conditional_formatting.add(f"F{r4 + 1}:F{e4}", CellIsRule(operator="equal", formula=[f'"{text}"'], fill=fill(bg)))

    r5 = e4 + 3
    _tbl_header(ws, r5, ["Map coverage", "", "Core substations", "With map location", "Share"])
    ws.merge_cells(f"A{r5}:B{r5}")
    for i, (code, name) in enumerate(CORE):
        r = r5 + 1 + i
        ws.cell(r, 1, code).font = font(color=NAVY)
        ws.merge_cells(f"A{r}:B{r}")
        ws[f"C{r}"] = f'=COUNTIFS({KD("country")},$A{r},{KD("ntype")},"Core node")'
        ws[f"D{r}"] = f'=SUMPRODUCT(({KD("country")}=$A{r})*({KD("ntype")}="Core node")*ISNUMBER({KD("x")}))'
        ws[f"E{r}"] = f'=IF(C{r}=0,"",D{r}/C{r})'
        for c in "CDE":
            color_formula(ws[f"{c}{r}"])
            ws[f"{c}{r}"].border = BORDER
            ws[f"{c}{r}"].number_format = "0%" if c == "E" else "#,##0"
    _sum_row(ws, r5 + len(CORE) + 1, r5 + 1, r5 + len(CORE), ["C", "D"])
    r6 = r5 + len(CORE) + 4
    _tbl_header(ws, r6, ["Light of the substations per country", "", "Red", "Amber", "Green", "Grey"])
    ws.merge_cells(f"A{r6}:B{r6}")
    for i, (code, name) in enumerate(CORE):
        r = r6 + 1 + i
        ws.cell(r, 1, code).font = font(color=NAVY)
        ws.merge_cells(f"A{r}:B{r}")
        for c, src in zip("CDEF", ("Z", "AA", "AB", "AC")):
            ws[f"{c}{r}"] = f"=Map_Data!{src}{6 + i}"
            color_formula(ws[f"{c}{r}"])
            ws[f"{c}{r}"].border = BORDER
            ws[f"{c}{r}"].number_format = "#,##0"
    _sum_row(ws, r6 + len(CORE) + 1, r6 + 1, r6 + len(CORE), ["C", "D", "E", "F"])
    ws.row_dimensions.group(d0 - 1, r6 + len(CORE) + 2, outline_level=1, hidden=True)
    ws.sheet_properties.outlinePr = Outline(summaryBelow=False)
    ws.sheet_format.outlineLevelRow = 1
    # --- 5 map on the right: title and legend are cells, the chart contains the map only (fixed proportions)
    ws["M1"] = "Network map"
    ws["M1"].font = font(bold=True, size=12, color=NAVY)
    ws["M1"].alignment = Alignment(vertical="bottom")
    for i, (g, c, t) in enumerate(LEGEND_POINTS):
        _legend(ws, 2, 13 + 2 * i, g, c, t)
    for i, (g, c, t) in enumerate(LEGEND_LINES):
        _legend(ws, 3, 13 + 2 * i, g, c, t)
    ws["M4"] = "Labels: share of substations with data per country. Zoom, substation search and a larger map: sheet Map."
    ws["M4"].hyperlink = "#'Map'!C3"
    ws["M4"].font = font(size=8, color="0B4BFF", underline="single")
    ws.merge_cells("M4:T4")
    add_map(wb, ws, "M5", _chart_width_cm(ws, 13, 20), marker=5)
    _fit_width(ws)
    ws.sheet_view.zoomScale = 85


# --------------------------------------------------------------------------- theme, M files, assembly
def collapse_columns(ws, ranges):
    """Collapse detail columns (outline): they stay calculated, the view becomes calmer."""
    for first, last_ in ranges:
        for c in range(column_index_from_string(first), column_index_from_string(last_) + 1):
            cd = ws.column_dimensions[get_column_letter(c)]
            cd.outlineLevel = 1
            cd.hidden = True
    ws.sheet_format.outlineLevelCol = 1


def apply_theme(wb):
    """Final touches: titles as 'Topic | message' (Georgia), no gridlines on display sheets."""
    for ws in wb.worksheets:
        if not ws.title.startswith(HIDDEN):
            ws.sheet_view.showGridLines = False
        c = ws["A1"]
        v = c.value
        if isinstance(v, str) and not v.startswith("=") and c.font is not None and c.font.b and (c.font.sz or 10) >= 14:
            if " – " in v:
                topic, rest = v.split(" – ", 1)
                c.value = CellRichText(TextBlock(InlineFont(rFont=FONT_TITLE, b=True, sz=18, color=NAVY), topic + " | "),
                                       TextBlock(InlineFont(rFont=FONT_TITLE, sz=18, color=NAVY), rest))
            else:
                c.font = font(bold=True, size=18, color=NAVY, name=FONT_TITLE)
            ws.row_dimensions[1].height = 34


def write_m_files(root: Path) -> list[Path]:
    """Write the Power Query code as .m files into the repository (excel/power_query)."""
    from . import content as C
    out_dir = root / "excel" / "power_query"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.m"):
        old.unlink()
    paths = []
    for name, filename, types in C.M_QUERIES:
        p = out_dir / f"{name}.m"
        p.write_text("// Power Query query " + name + " - loads " + filename + "\n" + "\n".join(C.m_code(name, filename, types)) + "\n", encoding="utf-8")
        paths.append(p)
    param = out_dir / "GitHubBaseUrl.m"
    param.write_text('// Parameter (type text): base link of the CSV files in the repository (with trailing slash)\n'
                     '"https://raw.githubusercontent.com/<ORG>/<REPO>/main/data/processed/" '
                     'meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n', encoding="utf-8")
    paths.append(param)
    return paths


def load_borders(root: Path):
    """Country borders for the map: data/static/borders.csv (Natural Earth, written by scripts/update_geodata.py; columns country, ring, lon, lat).
    Returns (rows, source text) or (None, text) if the file is missing: the map then uses the schematic outlines of outline.py."""
    f = root / "data" / "static" / "borders.csv"
    if not f.exists():
        return None, "schematic outlines drawn by hand (run the GitHub action 'Update map geodata' for real borders)"
    df = _read(f)
    rows = []
    for _key, g in df.groupby(["country", "ring"], sort=False):
        rows += [(c, float(x), float(y)) for c, x, y in zip(g["country"], g["lon"], g["lat"])]
        rows.append(("", None, None))
    note = root / "data" / "static" / "borders_source.txt"
    return rows, (note.read_text(encoding="utf-8").strip() if note.exists() else "data/static/borders.csv")


def build_workbook(root: Path, out_path: Path, base_url: str | None = None, connections: bool = True, preset: dict | None = None) -> Path:
    """Build the model. connections=True builds one data connection per raw data sheet (address: base_url)."""
    import yaml
    PRESET.update(preset or {})
    data = load_inputs(root)
    tsos = yaml.safe_load((root / "config" / "config.yml").read_text(encoding="utf-8"))["region"]["tsos"]
    _set_sizes(data)
    _STATE["connections"], _STATE["specs"] = connections, []
    _STATE["borders"], _STATE["borders_source"] = load_borders(root)
    base_url = base_url or f"https://raw.githubusercontent.com/{conn.PLACEHOLDER}/main/data/processed/"
    wb = Workbook()
    wb.remove(wb.active)
    for name in SHEETS:
        ws = wb.create_sheet(name)
        if name in TAB:
            ws.sheet_properties.tabColor = TAB[name]
    build_landing_sheets(wb, data)
    build_parameters(wb)
    build_lines(wb)
    build_transformers(wb)
    build_substations(wb)
    build_map_data(wb, tsos)
    build_map_lines(wb)
    build_dashboard(wb, data, tsos)
    build_map_sheet(wb, tsos)
    build_checks(wb, base_url if connections else None)
    from .guide import build_guide
    build_guide(wb, base_url if connections else None, _STATE["borders_source"])
    for n_ in ("Substations", "Lines", "Transformers"):
        wb[n_].row_dimensions[3].height = 20
    collapse_columns(wb["Substations"], [(SN.L("nlines"), SN.last)])
    collapse_columns(wb["Lines"], [(LN.L("neigh"), LN.L("len")), (LN.L("key"), LN.L("key")), (LN.L("hhigh"), LN.L("hover")), (LN.L("fmax"), LN.L("fmax")),
                                   (LN.L("dup"), LN.L("infilter"))])
    collapse_columns(wb["Transformers"], [(TN.L("kvs"), TN.L("kvs")), (TN.L("key"), TN.L("key")), (TN.L("hhigh"), TN.L("hover")), (TN.L("fmax"), TN.L("fmax")),
                                          (TN.L("assessed"), TN.L("assessed"))])
    pw = wb["Parameters"]
    pw.cell(pw.max_row + 2, 2, "Hidden sheets: raw data (D_…) and map helpers (Map_…). Unhide: right-click a sheet tab.").font = font(size=9, italic=True, color="595959")
    apply_theme(wb)
    for name in SHEETS:
        if name.startswith(HIDDEN):
            wb[name].sheet_state = "hidden"
    wb.properties.title = "Core capacity model, utilization of the transmission grid (13 countries, base case)"
    wb.properties.subject = "Traffic-light model for grid utilization and connection capacity based on public data"
    wb.properties.creator = "Project team capacity model"
    wb.calculation.fullCalcOnLoad = True
    wb.active = SHEETS.index("Dashboard")          # the file opens on the Dashboard; the Guide is the first tab to its left
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    if connections:
        conn.inject(str(out_path), _STATE["specs"], base_url)
    conn.patch_scatter_na_as_blank(str(out_path))
    conn.patch_map_charts(str(out_path))
    return out_path
