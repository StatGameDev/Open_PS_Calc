"""
BuildHeaderSection — build name, job, base level, and job level inputs.

Top section of the player panel. Emits build_name_changed, job_changed, and
level_changed signals; main_window.py connects these to recalculation triggers.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from core.models.build import PlayerBuild
from gui.section import Section
from gui.widgets import NoWheelCombo, NoWheelSpin

# Pre-renewal job IDs — Hercules constants.conf Job_* values.
_JOB_NAMES: list[tuple[int, str]] = [
    (0,    "Novice"),
    (1,    "Swordman"),
    (2,    "Mage"),
    (3,    "Archer"),
    (4,    "Acolyte"),
    (5,    "Merchant"),
    (6,    "Thief"),
    (7,    "Knight"),
    (8,    "Priest"),
    (9,    "Wizard"),
    (10,   "Blacksmith"),
    (11,   "Hunter"),
    (12,   "Assassin"),
    (14,   "Crusader"),
    (15,   "Monk"),
    (16,   "Sage"),
    (17,   "Rogue"),
    (18,   "Alchemist"),
    (19,   "Bard"),
    (20,   "Dancer"),
    (23,   "Super Novice"),
    (24,   "Gunslinger"),
    (25,   "Ninja"),
    (4008, "Lord Knight"),
    (4009, "High Priest"),
    (4010, "High Wizard"),
    (4011, "Mastersmith"),
    (4012, "Sniper"),
    (4013, "Assassin Cross"),
    (4015, "Paladin"),
    (4016, "Champion"),
    (4017, "Scholar"),
    (4018, "Stalker"),
    (4019, "Creator"),
    (4020, "Clown"),
    (4021, "Gypsy"),
]



class BuildHeaderSection(Section):
    """Build name, job, base level, and job level input section."""

    build_name_changed = Signal(str)
    job_changed = Signal(int)
    level_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        # ── Name row ──────────────────────────────────────────────────────
        name_row = QWidget()
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)
        name_layout.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Build name…")
        self._name_edit.textChanged.connect(self.build_name_changed)
        name_layout.addWidget(self._name_edit, stretch=1)
        self.add_content_widget(name_row)

        # ── Job / Level row ───────────────────────────────────────────────
        job_row = QWidget()
        job_layout = QHBoxLayout(job_row)
        job_layout.setContentsMargins(0, 0, 0, 0)
        job_layout.setSpacing(6)

        job_layout.addWidget(QLabel("Job:"))
        self._job_combo = NoWheelCombo()
        for job_id, job_name in _JOB_NAMES:
            self._job_combo.addItem(job_name, job_id)
        self._job_combo.currentIndexChanged.connect(self._emit_job_changed)
        job_layout.addWidget(self._job_combo, stretch=1)

        job_layout.addSpacing(8)
        job_layout.addWidget(QLabel("Base Lv:"))
        self._base_lv = NoWheelSpin()
        self._base_lv.setRange(1, 99)
        self._base_lv.setFixedWidth(55)
        self._base_lv.valueChanged.connect(self.level_changed)
        job_layout.addWidget(self._base_lv)

        job_layout.addSpacing(8)
        job_layout.addWidget(QLabel("Job Lv:"))
        self._job_lv = NoWheelSpin()
        self._job_lv.setRange(1, 70)
        self._job_lv.setFixedWidth(55)
        self._job_lv.valueChanged.connect(self.level_changed)
        job_layout.addWidget(self._job_lv)

        self.add_content_widget(job_row)

    # ── Internal ──────────────────────────────────────────────────────────

    def _emit_job_changed(self) -> None:
        self.job_changed.emit(self._job_combo.currentData() or 0)

    # ── Public API ────────────────────────────────────────────────────────

    def load_build(self, build: PlayerBuild) -> None:
        """Populate all widgets from build without emitting change signals."""
        for w in (self._name_edit, self._job_combo, self._base_lv, self._job_lv):
            w.blockSignals(True)
        self._name_edit.setText(build.name)
        idx = self._job_combo.findData(build.job_id)
        if idx >= 0:
            self._job_combo.setCurrentIndex(idx)
        self._base_lv.setValue(build.base_level)
        self._job_lv.setValue(build.job_level)
        for w in (self._name_edit, self._job_combo, self._base_lv, self._job_lv):
            w.blockSignals(False)

    def collect_into(self, build: PlayerBuild) -> None:
        """Write section state into an existing PlayerBuild in-place."""
        build.name = self._name_edit.text()
        build.job_id = self._job_combo.currentData() or 0
        build.base_level = self._base_lv.value()
        build.job_level = self._job_lv.value()
