"""Gemeinsame Formatierung im Stil der Oliver-Wyman-Folien (Arial, Titel in Georgia, Navy und Hellblau)."""
from __future__ import annotations

import math

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
FONT_TITLE = "Georgia"          # Ersatz für die Hausschrift Marsh Serif der Oliver-Wyman-Folien

# Farben (Hex ohne #) nach den Folien: Navy, Hellblau, warme Grautöne
NAVY, NAVY2, GREY, GREEN_D, GOLD = "000F47", "001A5C", "7B7974", "000F47", "0B4BFF"   # GREY = Rohdaten, GREEN_D = Ergebnis, GOLD = Steuerung
BLUE_TAB, INPUT_BLUE = "82BAFF", "0B4BFF"
L_GREY, L_BLUE, L_GREEN, L_GOLD, L_RED, L_YELLOW, L_GREY2 = "F5F3F0", "CEECFF", "EBE7E2", "D3DCFF", "F6D3D2", "FBEDBF", "D1CEC9"
AMPEL = {"Red": ("C53532", "FFFFFF"), "Amber": ("F4B400", "000F47"), "Green": ("6ABF30", "FFFFFF"), "Grey": ("B9B6B1", "000F47")}

THIN = Side(style="thin", color="D1CEC9")
BORDER = Border(bottom=THIN)                       # nur feine waagerechte Linien, wie in den Folientabellen
WHITE_SEP = Side(style="thin", color="FFFFFF")


def font(bold=False, size=10, color="000000", italic=False, name=FONT, underline=None):
    return Font(name=name, bold=bold, size=size, color=color, italic=italic, underline=underline)


def fill(hex_):
    return PatternFill(start_color=hex_, end_color=hex_, fill_type="solid")


def header(cell, kind="calc", wrap=True):
    """Kopfzeile: kind = data (warmes Grau) | calc (Navy) | result (Navy) | input (Hellblau) | info (Navy)."""
    colors = {"data": (GREY, "FFFFFF"), "calc": (NAVY2, "FFFFFF"), "result": (NAVY, "FFFFFF"),
              "input": ("82BAFF", NAVY), "info": (NAVY, "FFFFFF")}
    bg, fg = colors[kind]
    cell.fill = fill(bg)
    cell.font = font(bold=True, color=fg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=wrap)
    cell.border = Border(left=WHITE_SEP, right=WHITE_SEP)


def title(ws, text, sub=None, width_cols=8):
    ws["A1"] = text
    ws["A1"].font = font(bold=True, size=14, color=NAVY)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = font(italic=True, size=9, color="595959")


def set_widths(ws, widths: dict):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def lines_needed(text: str, chars_per_line: float) -> int:
    if not text:
        return 1
    total = 0
    for part in str(text).split("\n"):
        total += max(1, math.ceil(len(part) / max(chars_per_line, 1)))
    return total


def row_height(text: str, width_chars: float, line_pt: float = 13.0, minimum: float = 15.0) -> float:
    return max(minimum, lines_needed(text, width_chars * 1.05) * line_pt + 3)


def color_formula(cell):
    """Formeln in dunklem Navy (Eingaben sind blau)."""
    v = cell.value
    if isinstance(v, str) and v.startswith("="):
        cell.font = font(color=NAVY, size=cell.font.size or 10, bold=cell.font.bold, italic=cell.font.italic)


def col(n: int) -> str:
    return get_column_letter(n)


WRAP_TOP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
