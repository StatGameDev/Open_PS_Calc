"""
ManualAdjSection — raw numeric stat adjustments for testing or uncategorised sources.

Pure escape hatch for edge cases not covered by any other section. No source
attribution required. Known game-mechanic bonuses (gear scripts, consumables,
skill buffs) should be entered in their proper sections instead.

Adaptive grid: column count adjusts to section width via _on_width_changed().
Each column pair (label + spinner) requires at least _MIN_COL_PAIR_WIDTH pixels.

Input:  PlayerBuild.manual_adj_bonuses (via load_build / collect_into)
Output: get_bonuses() returns {stat_key: value} for non-zero entries
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from core.models.build import PlayerBuild
from gui.section import Section
from gui.widgets import NoWheelSpin

# (display_label, dict_key, min_val, max_val)
_STATS: list[tuple[str, str, int, int]] = [
    ("STR",        "str",           -99,  999),
    ("AGI",        "agi",           -99,  999),
    ("VIT",        "vit",           -99,  999),
    ("INT",        "int",           -99,  999),
    ("DEX",        "dex",           -99,  999),
    ("LUK",        "luk",           -99,  999),
    ("BATK",       "batk",        -9999, 9999),
    ("HIT",        "hit",          -500,  500),
    ("FLEE",       "flee",         -500,  500),
    ("CRI",        "cri",          -100,  100),
    ("Hard DEF",   "def",          -999,  999),
    ("Hard MDEF",  "mdef",         -999,  999),
    ("ASPD%",      "aspd_pct",     -100,  100),
    ("MaxHP",      "maxhp",       -9999, 9999),
    ("MaxSP",      "maxsp",       -9999, 9999),
    ("Crit Dmg %", "crit_dmg_pct", -200,  200),
]

# Minimum pixels per label+spinner column pair before reducing column count.
_MIN_COL_PAIR_WIDTH = 155


class ManualAdjSection(Section):

    bonuses_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        note_lbl = QLabel(
            "Raw numeric adjustments for testing or uncategorised sources.\n"
            "Use Equipment / Passives / Buffs for known bonuses."
        )
        note_lbl.setObjectName("active_items_note")
        note_lbl.setWordWrap(True)
        self.add_content_widget(note_lbl)

        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(3)

        self._spins: dict[str, QSpinBox] = {}
        self._labels: dict[str, QLabel] = {}

        for display, key_s, min_v, max_v in _STATS:
            lbl = QLabel(display + ":")
            lbl.setObjectName("flat_bonus_label")
            self._labels[key_s] = lbl

            spin = NoWheelSpin()
            spin.setRange(min_v, max_v)
            spin.setValue(0)
            spin.setFixedWidth(65)
            self._spins[key_s] = spin
            spin.valueChanged.connect(self._on_changed)

        self._current_cols: int = 0
        self._rebuild_grid(2)
        self.add_content_widget(self._grid_widget)

        source_lbl = QLabel("Source / Notes:")
        source_lbl.setObjectName("flat_bonus_label")
        self.add_content_widget(source_lbl)

        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText("e.g. Poring Coin food +10 STR")
        self._source_edit.setObjectName("active_items_source")
        self.add_content_widget(self._source_edit)

    def _rebuild_grid(self, cols: int) -> None:
        for _d, key_s, _n, _x in _STATS:
            lbl = self._labels.get(key_s)
            if lbl:
                self._grid.removeWidget(lbl)
                lbl.hide()
            spin = self._spins.get(key_s)
            if spin:
                self._grid.removeWidget(spin)
                spin.hide()

        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)

        for i, (_d, key_s, _n, _x) in enumerate(_STATS):
            row = i // cols
            col_base = (i % cols) * 2
            lbl = self._labels[key_s]
            self._grid.addWidget(lbl, row, col_base)
            lbl.show()
            spin = self._spins[key_s]
            self._grid.addWidget(spin, row, col_base + 1)
            spin.show()

        for c in range(cols):
            self._grid.setColumnStretch(c * 2, 1)

        self._current_cols = cols

    def _on_width_changed(self, width: int) -> None:
        effective = width - 20
        cols = max(1, effective // _MIN_COL_PAIR_WIDTH)
        if cols != self._current_cols:
            self._rebuild_grid(cols)

    def _on_changed(self) -> None:
        self.bonuses_changed.emit()

    # ── Public API ────────────────────────────────────────────────────────

    def load_build(self, build: PlayerBuild) -> None:
        for spin in self._spins.values():
            spin.blockSignals(True)
        bonuses = build.manual_adj_bonuses
        for key_s, spin in self._spins.items():
            spin.setValue(bonuses.get(key_s, 0))
        for spin in self._spins.values():
            spin.blockSignals(False)

    def collect_into(self, build: PlayerBuild) -> None:
        build.manual_adj_bonuses = {
            key_s: spin.value()
            for key_s, spin in self._spins.items()
            if spin.value() != 0
        }

    def get_bonuses(self) -> dict[str, int]:
        """Return current bonus dict (non-zero entries only)."""
        return {k: s.value() for k, s in self._spins.items() if s.value() != 0}
