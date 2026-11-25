from capmodel.normalize import element_key, name_key, norm_eic, norm_text


def test_trailing_and_nbsp_removed():
    assert norm_text("Diefflen - Ensdorf ENSDF N ") == "Diefflen - Ensdorf ENSDF N"
    assert norm_text("A\xa0B   C") == "A B C"
    assert norm_text(None) == ""
    assert norm_text(float("nan")) == ""


def test_placeholder_eics_are_missing():
    for v in ("", "ohne EIC", "nan", "11TDNOTAVAILABLE", None):
        assert norm_eic(v) == ""
    assert norm_eic(" 11T0-0000-2263-A ") == "11T0-0000-2263-A"


def test_element_key_rule():
    assert element_key("11T0-0000-2263-A", "x") == "11T0-0000-2263-A"
    assert element_key("", " Name A ") == "NAME|Name A"
    assert element_key("11TDNOTAVAILABLE", "Eichstetten C1 - C2 br") == "NAME|Eichstetten C1 - C2 br"


def test_name_key_ignores_case_and_blanks():
    assert name_key("Daxlanden - Kork RT ") == name_key("daxlanden - kork rt")
