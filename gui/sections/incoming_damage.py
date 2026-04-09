"""
IncomingDamageSection — incoming damage step breakdown (mob → player or PvP attacker → player).

Physical/Magic toggle switches which pipeline's steps are shown.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from core.models.damage import DamageResult, DamageStep
from gui.section import Section
from gui.widgets import NoWheelCombo, NoWheelSpin

_ELEMENTS = [
    (0, "Neutral"),
    (1, "Water"),
    (2, "Earth"),
    (3, "Fire"),
    (4, "Wind"),
    (5, "Poison"),
    (6, "Holy"),
    (7, "Dark"),
    (8, "Ghost"),
    (9, "Undead"),
]

_DASH = "—"
_COL_STEP   = 0
_COL_DAMAGE = 1
_COL_SOURCE = 2

# QTableWidgetItem foreground colors — cannot be controlled via QSS
_COLOR_PLACEHOLDER = QColor("#4a5060")   # dim grey for "No data" placeholder
_COLOR_SOURCE      = QColor("#6b7480")   # muted grey for Hercules source refs


def _fmt_step(step: DamageStep) -> str:
    if step.max_value == 0 or step.min_value == step.max_value:
        return str(step.value)
    return f"{step.min_value}–{step.value}–{step.max_value}"


class IncomingDamageSection(Section):
    """
    Incoming damage step breakdown (mob → player, or PvP attacker → player).

    Physical / Magic toggle switches which pipeline's steps are shown.
    No crit column — mob attacks have no crit pipeline.
    compact_mode="hidden" — hidden when the panel is compact.
    """

    config_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        # ── WIP warning ───────────────────────────────────────────────────
        wip_lbl = QLabel("⚠ Heavy WIP, do not use")
        self.add_content_widget(wip_lbl)

        # ── Summary row ───────────────────────────────────────────────────
        summary_widget = QWidget()
        summary_row = QHBoxLayout(summary_widget)
        summary_row.setContentsMargins(0, 0, 0, 4)
        summary_row.setSpacing(16)

        phys_lbl = QLabel("Physical:")
        phys_lbl.setObjectName("incoming_label")
        self._phys_summary = QLabel(_DASH)
        self._phys_summary.setObjectName("incoming_value")

        magic_lbl = QLabel("Magic:")
        magic_lbl.setObjectName("incoming_label")
        self._magic_summary = QLabel(_DASH)
        self._magic_summary.setObjectName("incoming_value")

        summary_row.addWidget(phys_lbl)
        summary_row.addWidget(self._phys_summary)
        summary_row.addSpacing(8)
        summary_row.addWidget(magic_lbl)
        summary_row.addWidget(self._magic_summary)
        summary_row.addStretch()
        self.add_content_widget(summary_widget)

        # ── Toggle + Source buttons ────────────────────────────────────────
        ctrl_widget = QWidget()
        ctrl_row = QHBoxLayout(ctrl_widget)
        ctrl_row.setContentsMargins(0, 0, 0, 4)
        ctrl_row.setSpacing(4)

        self._phys_btn = QPushButton("Physical")
        self._phys_btn.setCheckable(True)
        self._phys_btn.setChecked(True)
        self._phys_btn.setMinimumWidth(80)
        self._phys_btn.toggled.connect(self._on_mode_toggled)

        self._magic_btn = QPushButton("Magic")
        self._magic_btn.setCheckable(True)
        self._magic_btn.setMinimumWidth(80)
        self._magic_btn.toggled.connect(self._on_mode_toggled)

        self._steps_btn = QPushButton("Steps")
        self._steps_btn.setCheckable(True)
        self._steps_btn.setChecked(False)
        self._steps_btn.toggled.connect(self._on_steps_toggled)

        self._source_btn = QPushButton("Show Source")
        self._source_btn.setCheckable(True)
        self._source_btn.setMinimumWidth(100)
        self._source_btn.toggled.connect(self._on_source_toggled)

        ctrl_row.addWidget(self._phys_btn)
        ctrl_row.addWidget(self._magic_btn)
        ctrl_row.addWidget(self._steps_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self._source_btn)
        self.add_content_widget(ctrl_widget)

        # ── Incoming config row ────────────────────────────────────────────
        cfg_widget = QWidget()
        cfg_row = QHBoxLayout(cfg_widget)
        cfg_row.setContentsMargins(0, 0, 0, 4)
        cfg_row.setSpacing(8)

        self._ranged_chk = QCheckBox("Ranged")
        self._ranged_chk.toggled.connect(self.config_changed)

        cfg_row.addWidget(self._ranged_chk)
        cfg_row.addSpacing(16)

        magic_ele_lbl = QLabel("Ele:")
        magic_ele_lbl.setObjectName("incoming_label")
        self._magic_ele_combo = NoWheelCombo()
        self._magic_ele_combo.addItem("Mob natural", None)
        for ele_id, ele_name in _ELEMENTS:
            self._magic_ele_combo.addItem(ele_name, ele_id)
        self._magic_ele_combo.currentIndexChanged.connect(self.config_changed)

        ratio_lbl = QLabel("Ratio:")
        ratio_lbl.setObjectName("incoming_label")
        self._ratio_spin = NoWheelSpin()
        self._ratio_spin.setRange(0, 1000)
        self._ratio_spin.setSingleStep(5)
        self._ratio_spin.setValue(0)
        self._ratio_spin.setSuffix("%")
        self._ratio_spin.setFixedWidth(72)
        self._ratio_spin.valueChanged.connect(self.config_changed)

        cfg_row.addWidget(magic_ele_lbl)
        cfg_row.addWidget(self._magic_ele_combo)
        cfg_row.addSpacing(8)
        cfg_row.addWidget(ratio_lbl)
        cfg_row.addWidget(self._ratio_spin)
        cfg_row.addStretch()
        self.add_content_widget(cfg_widget)

        # ── Step table ────────────────────────────────────────────────────
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Step", "Damage", "Source"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(_COL_STEP,   210)
        self._table.setColumnWidth(_COL_DAMAGE, 120)
        self._table.setColumnHidden(_COL_SOURCE, True)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._table.setVisible(False)
        self.add_content_widget(self._table)

        self._physical_result: Optional[DamageResult] = None
        self._magic_result:    Optional[DamageResult] = None
        self._showing_magic = False

        self._set_placeholder()

    # ── Public API ────────────────────────────────────────────────────────

    def get_incoming_config(
        self,
    ) -> tuple[bool, Optional[int], Optional[int]]:
        """Return (is_ranged, ele_override, ratio_override).

        ele_override: None = use mob natural; int 0-9 = element ID override.
        ratio_override: None = use skill ratio; int > 0 = manual % override.
        """
        is_ranged = self._ranged_chk.isChecked()
        ele_override: Optional[int] = self._magic_ele_combo.currentData()
        ratio_val = self._ratio_spin.value()
        ratio_override: Optional[int] = ratio_val if ratio_val > 0 else None
        return is_ranged, ele_override, ratio_override

    # ── Mode / source toggles ──────────────────────────────────────────────

    def _on_mode_toggled(self, checked: bool) -> None:
        sender = self.sender()
        if not checked:
            # Prevent both buttons from being unchecked simultaneously
            sender.setChecked(True)
            return
        switching_to_magic = (sender is self._magic_btn)
        if switching_to_magic == self._showing_magic:
            return
        self._showing_magic = switching_to_magic
        self._phys_btn.blockSignals(True)
        self._magic_btn.blockSignals(True)
        self._phys_btn.setChecked(not switching_to_magic)
        self._magic_btn.setChecked(switching_to_magic)
        self._phys_btn.blockSignals(False)
        self._magic_btn.blockSignals(False)
        self._repopulate()

    def _on_steps_toggled(self, checked: bool) -> None:
        self._table.setVisible(checked)

    def _on_source_toggled(self, checked: bool) -> None:
        self._table.setColumnHidden(_COL_SOURCE, not checked)
        self._source_btn.setText("Hide Source" if checked else "Show Source")

    # ── Table population ──────────────────────────────────────────────────

    def _set_placeholder(self) -> None:
        self._table.setRowCount(1)
        item = QTableWidgetItem("No data yet")
        item.setForeground(_COLOR_PLACEHOLDER)
        self._table.setItem(0, _COL_STEP, item)
        self._table.setItem(0, _COL_DAMAGE, QTableWidgetItem(""))
        self._table.setItem(0, _COL_SOURCE, QTableWidgetItem(""))

    def _repopulate(self) -> None:
        result = self._magic_result if self._showing_magic else self._physical_result
        if result is None:
            self._set_placeholder()
            return

        steps = result.steps
        self._table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            name_item = QTableWidgetItem(step.name)
            tooltip = step.note
            if step.formula:
                tooltip += f"\n\nFormula: {step.formula}"
            name_item.setToolTip(tooltip)
            self._table.setItem(row, _COL_STEP, name_item)

            dmg_item = QTableWidgetItem(_fmt_step(step))
            dmg_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, _COL_DAMAGE, dmg_item)

            src_item = QTableWidgetItem(step.hercules_ref)
            src_item.setForeground(_COLOR_SOURCE)
            self._table.setItem(row, _COL_SOURCE, src_item)

        self._table.resizeRowsToContents()

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(
        self,
        physical: Optional[DamageResult],
        magic: Optional[DamageResult],
    ) -> None:
        """Update both pipeline results and redisplay the active tab."""
        self._physical_result = physical
        self._magic_result    = magic

        if physical is not None:
            self._phys_summary.setText(
                f"{physical.min_damage}–{physical.avg_damage}–{physical.max_damage}"
            )
        else:
            self._phys_summary.setText(_DASH)

        if magic is not None:
            self._magic_summary.setText(
                f"{magic.min_damage}–{magic.avg_damage}–{magic.max_damage}"
            )
        else:
            self._magic_summary.setText(_DASH)

        self._repopulate()
