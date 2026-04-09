"""
app_config — UI scale, font sizing, and QSS loading.

Provides the effective DPI scale factor, per-widget font size map, and helpers
for applying scaled fonts across the widget tree. Also owns settings.json
persistence for the user's scale override.

Input:  QApplication must exist before this module is imported (UI_SCALE reads
        the primary screen DPI at import time).
Output: scale accessors (scale_override, effective_scale), font factories
        (make_font, app_font), QSS loader (load_qss / raw_qss), and
        rescale_all_fonts() for live scale changes.
"""
import json

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Must be imported AFTER QApplication(sys.argv) is constructed in main.py.
UI_SCALE: float = QApplication.primaryScreen().logicalDotsPerInch() / 96.0
THEME_PATH: str = "gui/themes/dark.qss"
SAVES_DIR: str = "saves"

_SETTINGS_PATH = "settings.json"
_SCALE_MIN = 0.7
_SCALE_MAX = 1.5
_SCALE_STEP = 0.1

# objectName → base pixel size at 1.0 scale.
# Widgets at 13px (the application font default) are omitted — they inherit.
_SIZE_MAP: dict[str, int] = {
    "app_title":              15,
    "section_arrow":           9,
    "section_title":          12,
    "stat_points_label":      11,
    "stat_col_header":        11,
    "stat_sub_header":        11,
    "flat_bonus_label":       11,
    "compact_stat_label":     11,
    "derived_stat_label":     11,
    "derived_stat_value":     12,
    "equip_slot_label":       11,
    "equip_inline_combo":     11,
    "equip_edit_btn":         11,
    "compact_equip_summary":  11,
    "active_items_note":      11,
    "passive_sub_header":     11,
    "passive_placeholder":    11,
    "passive_sub_separator":  10,
    "passive_mastery_label":  11,
    "passive_compact_summary":11,
    "combat_field_label":     11,
    "combat_env_placeholder": 11,
    "summary_label":          11,
    "summary_col_header":     10,
    "summary_crit_pct":       12,
    "summary_hit_pct":        12,
    "compact_step_name":      11,
    "compact_step_val":       11,
    "target_stat_label":      11,
    "target_stat_value":      12,
    "target_section_header":  10,
    "target_compact_summary": 11,
    "incoming_value":         12,
    "subgroup_arrow":          8,
    "subgroup_title":         11,
    "scale_toast":            12,
}

_raw_qss: str = ""


def _load_override() -> float:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return float(json.load(f).get("ui_scale_override", 1.0))
    except Exception:
        return 1.0


_ui_scale_override: float = _load_override()


def scale_override() -> float:
    return _ui_scale_override


def effective_scale() -> float:
    return UI_SCALE * _ui_scale_override


def set_scale_override(value: float) -> None:
    global _ui_scale_override
    _ui_scale_override = max(_SCALE_MIN, min(_SCALE_MAX, round(value, 2)))
    try:
        existing: dict = {}
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        existing["ui_scale_override"] = _ui_scale_override
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except OSError:
        pass


def make_font(base_px: int) -> QFont:
    """Return a QFont at base_px scaled by the current effective scale."""
    f = QFont()
    f.setPixelSize(max(8, round(base_px * effective_scale())))
    return f


def app_font() -> QFont:
    """Application base font (13px scaled). Set on QApplication at startup and on scale change."""
    return make_font(13)


def load_qss() -> None:
    """Read the raw QSS from disk; must be called once after QApplication exists."""
    global _raw_qss
    try:
        with open(THEME_PATH, "r", encoding="utf-8") as f:
            _raw_qss = f.read()
    except FileNotFoundError:
        _raw_qss = ""


def raw_qss() -> str:
    return _raw_qss


def rescale_all_fonts(root) -> None:
    """Apply scaled fonts to all named widgets and class-typed widgets under root.

    Called after every scale change instead of re-applying the stylesheet.
    QApplication.setFont(app_font()) must be called first to update inheriting widgets.
    """
    from PySide6.QtWidgets import QHeaderView, QListWidget, QTableWidget, QWidget

    for w in root.findChildren(QWidget):
        name = w.objectName()
        if name in _SIZE_MAP:
            w.setFont(make_font(_SIZE_MAP[name]))

    for cls, px in ((QTableWidget, 12), (QListWidget, 12), (QHeaderView, 11)):
        for w in root.findChildren(cls):
            w.setFont(make_font(px))
