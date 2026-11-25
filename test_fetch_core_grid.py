"""Tests: structure report of the open Core grid datasets."""
import pandas as pd

from fetch_core_grid import describe


def test_describe_detects_coordinates_country_and_voltage_columns():
    df = pd.DataFrame({"bus_id": ["a", "b", "c"], "v_nom": [380, 220, 380], "x": [10.1, 11.2, 12.3], "y": [50.1, 51.2, 52.3], "country": ["DE", "DE", "AT"]})
    info = describe(df)
    assert info["rows"] == 3 and info["detected"]["lat"] == "y" and info["detected"]["lon"] == "x"
    assert info["detected"]["voltage"] == "v_nom" and info["detected"]["name"] == "bus_id" and info["countries"] == {"DE": 2, "AT": 1}


def test_describe_handles_tables_without_known_columns():
    info = describe(pd.DataFrame({"foo": [1, 2]}))
    assert info["rows"] == 2 and all(v is None for v in info["detected"].values()) and info["countries"] == {}
