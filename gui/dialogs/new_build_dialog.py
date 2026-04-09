"""
new_build_dialog — NewBuildDialog.

Dialog for creating a blank PlayerBuild: name, job, base level, and job level.
Saves the build to disk via BuildManager on accept and exposes created_build_name()
so the caller can load it.
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from core.build_manager import BuildManager
from core.models.build import PlayerBuild
from gui.widgets import NoWheelCombo, NoWheelSpin

# Matches the list in build_header.py exactly.
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


# Max job level per job group (exp_group_db.conf pre-re).
# Default = 50 (first class + non-trans second class).
_JOB_MAX_JOB_LV: dict[int, int] = {
    0:    10,   # Novice
    23:   99,   # Super Novice
    24:   70,   # Gunslinger (NinjaAndGunslinger MaxLevel:70)
    25:   70,   # Ninja
    4008: 70, 4009: 70, 4010: 70, 4011: 70, 4012: 70, 4013: 70,
    4015: 70, 4016: 70, 4017: 70, 4018: 70, 4019: 70, 4020: 70, 4021: 70,
}


def _max_job_level(job_id: int) -> int:
    return _JOB_MAX_JOB_LV.get(job_id, 50)


class NewBuildDialog(QDialog):
    """Create a blank PlayerBuild and save it. Returns created_build_name() on accept."""

    def __init__(self, saves_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Build")
        self.setMinimumWidth(340)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._saves_dir = saves_dir
        self._created_name: Optional[str] = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. my_knight")
        form.addRow("Name:", self._name_edit)

        self._job_combo = NoWheelCombo()
        for job_id, job_name in _JOB_NAMES:
            self._job_combo.addItem(job_name, userData=job_id)
        form.addRow("Job:", self._job_combo)

        self._level_spin = NoWheelSpin()
        self._level_spin.setRange(1, 99)
        self._level_spin.setValue(99)
        form.addRow("Base Level:", self._level_spin)

        self._job_level_spin = NoWheelSpin()
        # _on_job_changed updates range and value whenever the job selection changes.
        self._job_level_spin.setRange(1, 10)
        self._job_level_spin.setValue(10)
        form.addRow("Job Level:", self._job_level_spin)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        layout.addWidget(btn_box)

        self._name_edit.textChanged.connect(self._on_name_changed)
        self._job_combo.currentIndexChanged.connect(self._on_job_changed)
        self._ok_btn.clicked.connect(self._create_build)
        btn_box.rejected.connect(self.reject)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_name_changed(self, text: str) -> None:
        self._ok_btn.setEnabled(bool(text.strip()))

    def _on_job_changed(self) -> None:
        job_id = self._job_combo.currentData()
        max_lv = _max_job_level(job_id)
        self._job_level_spin.setRange(1, max_lv)
        self._job_level_spin.setValue(max_lv)

    def _create_build(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            return
        job_id = self._job_combo.currentData()
        level = self._level_spin.value()
        job_level = self._job_level_spin.value()
        build = PlayerBuild(name=name, job_id=job_id, base_level=level, job_level=job_level)
        path = os.path.join(self._saves_dir, f"{name}.json")
        BuildManager.save_build(build, path)
        self._created_name = name
        self.accept()

    # ── Public API ─────────────────────────────────────────────────────────

    def created_build_name(self) -> Optional[str]:
        return self._created_name
