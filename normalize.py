"""Text and key normalisation.

Why this is needed: the JAO raw data contain element names with trailing blanks (e.g. 'Diefflen - Ensdorf ENSDF N ').
Without cleaning, a name comparison does not find these elements.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_PLACEHOLDER_EIC = {"", "nan", "none", "ohne eic", "-"}


def norm_text(value) -> str:
    """Non-breaking blanks -> normal blanks, repeated blanks -> one, trim the edges."""
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except Exception:  # pragma: no cover
        pass
    return _WS.sub(" ", str(value).replace("\xa0", " ")).strip()


def norm_eic(value) -> str:
    """Clean an EIC; placeholders ('ohne EIC', '11TDNOTAVAILABLE', ...) become empty text."""
    text = norm_text(value)
    low = text.lower()
    return "" if (low in _PLACEHOLDER_EIC or "notavailable" in low) else text


def name_key(name) -> str:
    """Comparison form of a name (case-insensitive)."""
    return norm_text(name).casefold()


def element_key(eic, name) -> str:
    """Key of a network element: EIC, otherwise 'NAME|<name>'.

    The same rule is used in the Excel model (sheets 'Lines' and 'Transformers', column 'Key').
    """
    eic_n = norm_eic(eic)
    return eic_n if eic_n else "NAME|" + norm_text(name)
