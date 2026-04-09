"""
StepBreakdownSection — full pipeline step table for a calculated result.

Displays Normal and Crit columns side-by-side with an optional Hercules source column.
Hidden entirely in builder-focused compact mode; the StepsBar in panel.py handles
compact-state step display instead.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models.damage import BattleResult, DamageStep
from gui.section import Section

_DASH = "—"
_COL_NAME = 0
_COL_NORMAL = 1
_COL_CRIT = 2
_COL_SOURCE = 3

# QTableWidgetItem foreground colors — cannot be controlled via QSS
_COLOR_PLACEHOLDER = QColor("#4a5060")   # dim grey for "No data" placeholder
_COLOR_CRIT        = QColor("#f0a020")   # amber for crit values
_COLOR_SOURCE      = QColor("#6b7480")   # muted grey for Hercules source refs


def _fmt_step(step: Optional[DamageStep]) -> str:
    if step is None:
        return _DASH
    if step.max_value == 0 or step.min_value == step.max_value:
        return str(step.value)
    return f"{step.min_value}–{step.value}–{step.max_value}"


class StepBreakdownSection(Section):
    """
    Full pipeline table (combat focused only).
    compact_mode="hidden": section is completely hidden when builder is focused.
    The StepsBar in Panel (gui/panel.py) handles compact-state step display.
    """

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        # ── Controls row ──────────────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 4)

        self._show_source_btn = QPushButton("Show Source")
        self._show_source_btn.setCheckable(True)
        self._show_source_btn.setMinimumWidth(100)
        self._show_source_btn.toggled.connect(self._on_source_toggled)
        ctrl_row.addWidget(self._show_source_btn)
        ctrl_row.addStretch()

        ctrl_widget = QWidget()
        ctrl_widget.setLayout(ctrl_row)
        self.add_content_widget(ctrl_widget)

        # ── Table ─────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Step", "Normal", "Crit", "Source"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(_COL_NAME, 180)
        self._table.setColumnWidth(_COL_NORMAL, 120)
        self._table.setColumnWidth(_COL_CRIT, 120)
        self._table.setColumnHidden(_COL_SOURCE, True)
        self._table.setWordWrap(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.setMinimumHeight(320)
        self.add_content_widget(self._table)
        self._show_source_btn.setChecked(True)

        self._set_placeholder()

    # ── Source toggle ──────────────────────────────────────────────────────

    def _on_source_toggled(self, checked: bool) -> None:
        self._table.setColumnHidden(_COL_SOURCE, not checked)
        self._show_source_btn.setText("Hide Source" if checked else "Show Source")

    # ── Table population ──────────────────────────────────────────────────

    def _set_placeholder(self) -> None:
        self._table.setRowCount(1)
        item = QTableWidgetItem("Select a target to see results")
        item.setForeground(_COLOR_PLACEHOLDER)
        self._table.setItem(0, _COL_NAME, item)
        for col in (_COL_NORMAL, _COL_CRIT, _COL_SOURCE):
            self._table.setItem(0, col, QTableWidgetItem(""))

    def _populate_table(self, result: BattleResult) -> None:
        normal_steps = result.normal.steps
        crit_by_name: dict[str, DamageStep] = {}
        crit_only_steps: list[DamageStep] = []
        if result.crit is not None:
            normal_names = {s.name for s in normal_steps}
            for s in result.crit.steps:
                if s.name in normal_names:
                    crit_by_name[s.name] = s
                else:
                    crit_only_steps.append(s)

        rows = list(normal_steps) + crit_only_steps
        self._table.setRowCount(len(rows))

        for row_idx, step in enumerate(rows):
            is_crit_only = step not in normal_steps

            name_item = QTableWidgetItem(step.name)
            tooltip = step.note
            if step.formula:
                tooltip += f"\n\nFormula: {step.formula}"
            name_item.setToolTip(tooltip)
            self._table.setItem(row_idx, _COL_NAME, name_item)

            if is_crit_only:
                normal_item = QTableWidgetItem(_DASH)
                crit_item = QTableWidgetItem(_fmt_step(step))
            else:
                normal_item = QTableWidgetItem(_fmt_step(step))
                crit_step = crit_by_name.get(step.name)
                crit_item = QTableWidgetItem(_fmt_step(crit_step))

            normal_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            crit_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if result.crit is not None:
                crit_item.setForeground(_COLOR_CRIT)

            self._table.setItem(row_idx, _COL_NORMAL, normal_item)
            self._table.setItem(row_idx, _COL_CRIT, crit_item)

            src_item = QTableWidgetItem(step.hercules_ref)
            src_item.setForeground(_COLOR_SOURCE)
            self._table.setItem(row_idx, _COL_SOURCE, src_item)

        self._table.resizeRowsToContents()

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self, result: Optional[BattleResult]) -> None:
        if result is None:
            self._set_placeholder()
        else:
            self._populate_table(result)
