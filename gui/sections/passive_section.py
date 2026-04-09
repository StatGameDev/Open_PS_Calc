"""
PassiveSection — passive skill levels (masteries and toggles).

Adaptive grid: column count adjusts to section width via _on_width_changed().
Skill visibility is filtered by job_id via update_job(); server profile controls
which passives are hidden for specific jobs (passive_hidden_for_jobs in server_profiles.py).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QWidget,
)

from core.data_loader import loader
from core.models.build import PlayerBuild
from core.server_profiles import get_profile
from gui.section import Section
from gui.widgets import LevelWidget

# ── Passives (masteries and other passive skills) ─────────────────────────────
# (skill_key, max_lv, source_skill)
# Display names are resolved via loader.get_skill_display_name(source_skill, profile).
# source_skill is always the real Hercules constant used for lookup; skill_key may differ
# (e.g. SM_TWOHANDSWORD is the build key but SM_TWOHAND is the constant in skill_descriptions.json).
_PASSIVES: list[tuple] = [
    ("SM_SWORD",         10, "SM_SWORD"),
    ("SM_TWOHANDSWORD",  10, "SM_TWOHAND"),
    ("KN_SPEARMASTERY",  10, "KN_SPEARMASTERY"),
    ("AM_AXEMASTERY",    10, "AM_AXEMASTERY"),
    ("PR_MACEMASTERY",   10, "PR_MACEMASTERY"),
    ("MO_IRONHAND",      10, "MO_IRONHAND"),
    ("MO_TRIPLEATTACK",  10, "MO_TRIPLEATTACK"),
    ("MO_CHAINCOMBO",     5, "MO_CHAINCOMBO"),
    ("MO_COMBOFINISH",    5, "MO_COMBOFINISH"),
    ("BA_MUSICALLESSON", 10, "BA_MUSICALLESSON"),
    ("DC_DANCINGLESSON", 10, "DC_DANCINGLESSON"),
    ("SA_ADVANCEDBOOK",  10, "SA_ADVANCEDBOOK"),
    ("TF_DOUBLE",        10, "TF_DOUBLE"),
    ("AS_KATAR",         10, "AS_KATAR"),
    ("ASC_KATAR",        10, "ASC_KATAR"),
    ("AL_DEMONBANE",     10, "AL_DEMONBANE"),
    ("HT_BEASTBANE",     10, "HT_BEASTBANE"),
    ("HT_BLITZBEAT",      5, "HT_BLITZBEAT"),
    ("HT_STEELCROW",     10, "HT_STEELCROW"),
    ("BS_HILTBINDING",    1, "BS_HILTBINDING"),
    ("SA_DRAGONOLOGY",    5, "SA_DRAGONOLOGY"),
    ("WZ_ESTIMATION",     1, "WZ_ESTIMATION"),   # PS: Fire/Water/Wind/Earth elemental damage +2%
    ("AC_OWL",           10, "AC_OWL"),
    ("CR_TRUST",         10, "CR_TRUST"),
    ("BS_WEAPONRESEARCH",10, "BS_WEAPONRESEARCH"),
    ("AC_VULTURE",       10, "AC_VULTURE"),
    ("GS_SINGLEACTION",  10, "GS_SINGLEACTION"),
    ("GS_SNAKEEYE",      10, "GS_SNAKEEYE"),
    ("GS_CHAINACTION",   10, "GS_CHAINACTION"),
    ("TF_MISS",          10, "TF_MISS"),
    ("MO_DODGE",         10, "MO_DODGE"),
    ("BS_SKINTEMPER",     5, "BS_SKINTEMPER"),
    ("AL_DP",            10, "AL_DP"),
    ("SM_RECOVERY",      10, "SM_RECOVERY"),
    ("MG_SRECOVERY",     10, "MG_SRECOVERY"),
    ("NJ_NINPOU",         4, "NJ_NINPOU"),
    ("NJ_TOBIDOUGU",     10, "NJ_TOBIDOUGU"),
    # dual-wield penalty reducers — visible only for Assassin / Assassin Cross
    ("AS_RIGHT",          5, "AS_RIGHT"),
    ("AS_LEFT",           5, "AS_LEFT"),
]


def _make_sub_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("passive_sub_header")
    return lbl


class PassiveSection(Section):
    """Passives (masteries) and toggle skills, job-filtered per update_job()."""

    passives_changed = Signal()

    # Minimum pixels required per label+widget column pair before reducing columns.
    _MIN_COL_PAIR_WIDTH: int = 200

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._current_job_id: int = 0
        self._current_server: str = "standard"

        self._mastery_combos: dict[str, LevelWidget] = {}  # max_lv > 1 → dropdown
        self._mastery_checks: dict[str, QCheckBox]  = {}  # max_lv == 1 → toggle
        self._mastery_labels: dict[str, QLabel]     = {}

        # Adaptive layout state.
        # _current_cols: last column count used in the grid; 0 means grid not yet built.
        # _visible_keys: cached by update_job(); used by _on_width_changed().
        self._current_cols: int = 0
        self._visible_keys: list[str] = [m_key for m_key, *_ in _PASSIVES]

        # ── Passives (masteries) ──────────────────────────────────────────
        mastery_widget = QWidget()
        self._mastery_grid = QGridLayout(mastery_widget)
        self._mastery_grid.setContentsMargins(0, 0, 0, 0)
        self._mastery_grid.setHorizontalSpacing(12)
        self._mastery_grid.setVerticalSpacing(3)

        # Create all widgets once; placement is handled by _rebuild_mastery_grid.
        for m_key, max_lv, source_skill in _PASSIVES:
            lbl = QLabel(loader.get_skill_display_name(source_skill, short=True))
            lbl.setObjectName("passive_mastery_label")
            self._mastery_labels[m_key] = lbl

            if max_lv == 1:
                chk = QCheckBox()
                self._mastery_checks[m_key] = chk
                chk.toggled.connect(self._on_passives_changed)
            else:
                combo = LevelWidget(max_lv, include_off=True)
                self._mastery_combos[m_key] = combo
                combo.valueChanged.connect(self._on_passives_changed)

        # Initial placement at the default column count (2). The first resizeEvent
        # will correct this once the section has a real width.
        self._rebuild_mastery_grid(self._visible_keys, cols_per_row=2)
        self.add_content_widget(mastery_widget)

        self.set_header_summary(self._build_summary())

    # ── Value helpers ──────────────────────────────────────────────────────

    def _get_mastery_value(self, m_key: str) -> int:
        if m_key in self._mastery_checks:
            return 1 if self._mastery_checks[m_key].isChecked() else 0
        combo = self._mastery_combos.get(m_key)
        return combo.value() if combo else 0

    def _set_mastery_value(self, m_key: str, value: int) -> None:
        if m_key in self._mastery_checks:
            self._mastery_checks[m_key].setChecked(value > 0)
        elif m_key in self._mastery_combos:
            self._mastery_combos[m_key].setValue(value)

    # ── Public API (job visibility) ────────────────────────────────────────

    def set_server(self, server: str) -> None:
        self._current_server = server
        self._refresh_labels()
        self.update_job(self._current_job_id)

    def _refresh_labels(self) -> None:
        """Re-resolve all mastery labels for the current server (short names)."""
        profile = get_profile(self._current_server)
        for m_key, _max_lv, source_skill in _PASSIVES:
            lbl = self._mastery_labels.get(m_key)
            if lbl is not None:
                lbl.setText(loader.get_skill_display_name(source_skill, profile, short=True))

    def update_job(self, job_id: int) -> None:
        self._current_job_id = job_id
        job_skills = loader.get_skills_for_job(job_id)

        # Reset hidden widgets (values cleared, signals suppressed).
        for m_key, _max_lv, source_skill in _PASSIVES:
            if source_skill not in job_skills:
                w = self._mastery_combos.get(m_key) or self._mastery_checks.get(m_key)
                if w is not None:
                    w.blockSignals(True)
                    if isinstance(w, QCheckBox):
                        w.setChecked(False)
                    else:
                        w.setCurrentIndex(0)
                    w.blockSignals(False)

        _profile = get_profile(self._current_server)
        self._visible_keys = [
            m_key for m_key, _max_lv, source_skill in _PASSIVES
            if source_skill in job_skills
            and job_id not in _profile.passive_hidden_for_jobs.get(source_skill, frozenset())
        ]
        self._rebuild_mastery_grid(self._visible_keys, self._current_cols or 2)

    # ── Adaptive grid ─────────────────────────────────────────────────────

    def _rebuild_mastery_grid(self, visible_keys: list[str], cols_per_row: int) -> None:
        """Clear and repopulate the mastery grid with visible_keys packed at cols_per_row pairs per row.

        Each "pair" occupies two grid columns: label (even index) + widget (odd index).
        Label columns absorb spare horizontal space; widget columns stay at natural size.
        """
        # Remove all mastery widgets from the grid (they remain parented to the container).
        for m_key in [k for k, *_ in _PASSIVES]:
            lbl = self._mastery_labels.get(m_key)
            if lbl:
                self._mastery_grid.removeWidget(lbl)
                lbl.hide()
            w = self._mastery_combos.get(m_key) or self._mastery_checks.get(m_key)
            if w:
                self._mastery_grid.removeWidget(w)
                w.hide()

        # Clear column stretch settings from the previous layout.
        for c in range(self._mastery_grid.columnCount()):
            self._mastery_grid.setColumnStretch(c, 0)

        # Re-add visible items tightly packed, left-to-right.
        for i, m_key in enumerate(visible_keys):
            row = i // cols_per_row
            col_base = (i % cols_per_row) * 2
            lbl = self._mastery_labels[m_key]
            self._mastery_grid.addWidget(lbl, row, col_base)
            lbl.show()
            w = self._mastery_combos.get(m_key) or self._mastery_checks.get(m_key)
            if w:
                self._mastery_grid.addWidget(w, row, col_base + 1)
                w.show()

        # Label columns (0, 2, 4, …) absorb spare width; widget columns stay fixed.
        for c in range(cols_per_row):
            self._mastery_grid.setColumnStretch(c * 2, 1)

        self._current_cols = cols_per_row

    def _on_width_changed(self, width: int) -> None:
        """Reflow the mastery grid when the section width changes."""
        # Subtract content frame margins (10px each side, set in Section.__init__).
        effective = width - 20
        cols = max(1, effective // self._MIN_COL_PAIR_WIDTH)
        if cols != self._current_cols:
            self._rebuild_mastery_grid(self._visible_keys, cols)

    # ── Internal ──────────────────────────────────────────────────────────

    def _on_passives_changed(self) -> None:
        self.passives_changed.emit()
        self.set_header_summary(self._build_summary())

    def _build_summary(self) -> str:
        parts: list[str] = []
        profile = get_profile(self._current_server)
        for m_key, _max_lv, source_skill in _PASSIVES:
            val = self._get_mastery_value(m_key)
            if val > 0:
                name = loader.get_skill_display_name(source_skill, profile)
                parts.append(f"{name} {val}")
        return "  ·  ".join(parts) if parts else "No active passives"

    # ── Public API ────────────────────────────────────────────────────────

    def load_build(self, build: PlayerBuild) -> None:
        all_widgets = (
            list(self._mastery_combos.values()) +
            list(self._mastery_checks.values())
        )
        for w in all_widgets:
            w.blockSignals(True)

        for m_key, *_ in _PASSIVES:
            self._set_mastery_value(m_key, build.mastery_levels.get(m_key, 0))

        for w in all_widgets:
            w.blockSignals(False)

        self._current_job_id = build.job_id
        self.update_job(build.job_id)

        self.set_header_summary(self._build_summary())

    def collect_into(self, build: PlayerBuild) -> None:
        build.mastery_levels = {
            m_key: self._get_mastery_value(m_key)
            for m_key, *_ in _PASSIVES
            if self._get_mastery_value(m_key) > 0
        }
