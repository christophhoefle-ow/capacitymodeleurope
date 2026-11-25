"""Tests: reading of the JAO Core Static Grid Model (synthetic workbook with the same layout)."""
import tempfile
from pathlib import Path

from openpyxl import Workbook

from capmodel.sgm import display_name, neighbour_from_comment, node_key, pretty_name, read_lines, read_tso_coordinates, read_transformers

TSO = {"50HERTZ": "DE", "AMPRION": "DE", "APG": "AT", "CEPS": "CZ", "TENNETBV": "NL"}
LINE_HEAD = ["NE_name", "EIC_Code", "TSO", "Full_name", "Full_name", "Voltage_level(kV)", "Period 1", "Period 2", "Period 3", "Period 4", "Period 5", "Period 6", "Fixed", "DLRmin(A)",
             "DLRmax(A)", "Resistance_R(Ω)", "Reactance_X(Ω)", "Susceptance_B(μS)", "Length_(km)", "Comment"]
TRAFO_HEAD = ["Full Name", "EIC_Code", "TSO", "Min", "Max", "Fixed", "Primary", "Secondary", "Resistance_R(Ω)", "Reactance_X(Ω)", "Susceptance_B (µS)", "Conductance_G (µS)",
              "Taps used for RAO", "Theta θ (°)", "Symmetrical/Asymmetrical", "Phase Regulation δu (%)", "Angle Regulation δu (%)", "Comment"]


def _line(name, eic, tso, s1, s2, comment="", fixed=2000, length=50):
    return [name, eic, tso, s1, s2, 380, None, None, None, None, None, None, fixed, None, None, 1.0, 10.0, 100.0, length, comment]


def _workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Lines"
    ws.append(["group"] * 20)
    ws.append(LINE_HEAD)
    ws.append(_line("Alpha - Beta", "EIC-1", "50HERTZ", "Alpha", "Beta"))
    ws.append(_line("Gamma - Roehrsdorf", "EIC-2", "AMPRION", "Gamma", "Roehrsdorf"))
    ws2 = wb.create_sheet("Tielines")
    ws2.append(["group"] * 20)
    ws2.append(LINE_HEAD)
    ws2.append(_line("Beta - Hradec", "EIC-3", "50HERTZ", "Beta", "Hradec", "Tie-line to CZ (CEPS)"))
    ws2.append(_line("Hradec - Beta", "EIC-3", "CEPS", "Hradec", "Beta", "Tie-line to DE", fixed=None, length=None))        # same EIC listed by the other TSO
    ws2.append(_line("Alpha - Gamma", "EIC-4", "50HERTZ", "Alpha", "Gamma", "Internal tie-line with Amprion"))
    ws2.append(_line("Mecklar - Vieselbach", "EIC-5", "50HERTZ", "Mecklar", "Vieselbach", "Tie-line to DE (TTG)"))
    ws3 = wb.create_sheet("Transformers")
    ws3.append(["group"] * 18)
    ws3.append(TRAFO_HEAD)
    ws3.append(["TR Alpha 220/400 401", "EIC-T1", "50HERTZ", 800, 800, None, 400, 231, 0.6, 50.0, -400.0, 2.5, None, None, None, 1.3, 0, None])
    ws3.append(["PST Roehrsdorf PF4", "EIC-T2", "AMPRION", 900, 900, None, 380, 380, 0.1, 12.0, -2.4, 0.9, "-10;10", 90, "Symmetrical", 1.2, 0, None])
    wb.save(path)


def test_node_key_ignores_spelling_and_voltage_level():
    assert node_key("Röhrsdorf") == node_key("Roehrsdorf") and node_key("Győr") == node_key("Gyoer")
    assert node_key("Meeden 380") == node_key("Meeden 220") == node_key("Meeden") and display_name("Meeden 380") == "Meeden"
    assert node_key("Buers") != node_key("Buer")
    assert node_key("Ernsthofen 2") == node_key("Ernsthofen") and display_name("Pecs 1") == "Pecs" and display_name("Szombathely 1 440B") == "Szombathely 1 440B"
    assert pretty_name("WIELOPOLE") == "Wielopole" and pretty_name("Röhrsdorf") == "Röhrsdorf" and pretty_name("TEL") == "TEL" and pretty_name("MT-SAINT-MARTIN 400") == "Mt-Saint-Martin"


def test_neighbour_from_comment_tells_cross_border_from_internal():
    assert neighbour_from_comment("Tie-line to CZ (CEPS)", "DE") == "CZ" and neighbour_from_comment("Tieline between AT-DE.", "AT") == "DE"
    assert neighbour_from_comment("Tie-line to DE (TTG)", "DE") == "DE" and neighbour_from_comment("Internal tie-line with Amprion", "DE") == "DE"
    assert neighbour_from_comment("Tie-line to Netherland", "DE") == "NL" and neighbour_from_comment("Tie-line with APG", "CZ") == "AT"


def test_read_lines_dedupes_tie_lines_and_types_them():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sgm.xlsx"
        _workbook(p)
        lines = read_lines(str(p), TSO).set_index("eic")
    assert len(lines) == 5 and lines.loc["EIC-3", "tso"] == "50HERTZ" and "also listed by CEPS" in lines.loc["EIC-3", "jao_comment"]
    assert lines.loc["EIC-3", "type"] == "Tie-line" and lines.loc["EIC-3", "neighbor_country"] == "CZ"
    assert lines.loc["EIC-4", "type"] == "Internal tie-line" and lines.loc["EIC-5", "type"] == "Internal tie-line" and lines.loc["EIC-1", "type"] == "Line"
    assert lines.loc["EIC-1", "country"] == "DE" and lines.loc["EIC-1", "imax_fixed_a"] == 2000 and lines.loc["EIC-1", "length_km"] == 50


def test_read_transformers_derives_substation_and_pst():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sgm.xlsx"
        _workbook(p)
        t = read_transformers(str(p), TSO, {node_key("Alpha"): "Alpha", node_key("Roehrsdorf"): "Roehrsdorf"}).set_index("eic")
    assert t.loc["EIC-T1", "substation"] == "Alpha" and t.loc["EIC-T1", "type"] == "Transformer" and t.loc["EIC-T1", "country"] == "DE"
    assert t.loc["EIC-T2", "substation"] == "Roehrsdorf" and t.loc["EIC-T2", "type"] == "PST" and t.loc["EIC-T2", "u_primary_kv"] == 380


def test_read_tso_coordinates():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "tso.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Lines"
        ws.append(["g"] * 12)
        ws.append(["NE_name", "EIC_Code", "TSO", "Full_name", "Short_name", "Longitude", "Latitude", "Full_name", "Short_name", "Longitude", "Latitude", "Voltage_level(kV)"])
        ws.append(["A - B", "E1", "TENNETGMBH", "Alfstedt", "D2ALFS1", 9.06, 53.44, "Dollern", "D2DOLL1", 9.5, 53.53, 380])
        ws2 = wb.create_sheet("Tielines")
        ws2.append(["g"] * 12)
        ws2.append(["NE_name", "EIC_Code", "TSO", "Full_name", "Short_name", "Longitude", "Latitude", "Full_name", "Short_name", "Longitude", "Latitude", "Voltage_level(kV)"])
        wb.save(p)
        co = read_tso_coordinates(str(p), "TenneT test").set_index("substation")
    assert co.loc["Alfstedt", "latitude"] == 53.44 and co.loc["Dollern", "longitude"] == 9.5
