"""
TargetStateSection — debuffs and ailments the player applies to the target.

Holds three sub-panels: Applied Debuffs, Status Ailments, and Monster State.
Two pipeline API methods:
  apply_to_target(target)           — writes pipeline-level effects to the resolved Target.
  collect_target_player_scs()       — returns stat-cascade SCs for the PvP path.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.models.build import PlayerBuild
from core.models.target import Target
from gui.section import Section
from gui.widgets import LevelWidget, NoWheelCombo, NoWheelSpin
from gui.widgets.layout_helpers import make_side_by_side_row

# Hercules element indices (ele_name order in db/const.hpp)
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


class TargetStateSection(Section):
    """
    Debuffs/ailments applied by the player to the target.

    Two-method pipeline API:
      collect_target_player_scs()    — returns stat-cascade SCs as a dict for player
                                       targets. Merged into pvp_eff.player_active_scs
                                       before StatusCalculator runs on the pvp build.
      apply_to_target(target)        — writes ALL debuff flags to target.target_active_scs
                                       plus element overrides and DEF strip. Called after
                                       target resolution. No element restore needed —
                                       target is re-resolved each pipeline run.

    Persistence API:
      collect_into(build)            — writes persisted debuffs to build.target_debuffs.
      load_build(build)              — restores widget state from build.target_debuffs.

    Mob path:  apply_to_target() → target_utils.apply_mob_scs() (core/calculators/target_utils.py)
    PvP path:  collect_target_player_scs() → pvp_eff.player_active_scs (main_window.py)
               → StatusCalculator → player_build_to_target() → apply_to_target()

    Widget sizing note: NoWheelSpin instances in this section require setFixedWidth()
    set ~8px wider than the Qt default or they truncate in the dark theme.  Apply to
    every new NoWheelSpin added here regardless of whether it has a prefix.
    """

    state_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        # ── Left column: Applied Debuffs ──────────────────────────────────
        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        debuff_lbl = QLabel("Applied Debuffs")
        debuff_lbl.setObjectName("sub_group_title")
        left_layout.addWidget(debuff_lbl)

        debuff_grid = QGridLayout()
        debuff_grid.setHorizontalSpacing(8)
        debuff_grid.setVerticalSpacing(4)
        debuff_grid.setColumnStretch(2, 1)

        row = 0
        debuff_grid.addWidget(_lbl("Eternal Chaos"), row, 0)
        self._chk_chaos = QCheckBox()
        debuff_grid.addWidget(self._chk_chaos, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Lex Aeterna"), row, 0)
        self._chk_lex = QCheckBox()
        debuff_grid.addWidget(self._chk_lex, row, 1)
        row += 1

        # Damage-taken debuffs: +10% each, multiplicative with each other and Lex Aeterna.
        # Mailbreaker does NOT apply to bosses; Venom Dust and Raided apply to all.
        debuff_grid.addWidget(_lbl("Mailbreaker"), row, 0)
        self._chk_mailbreaker = QCheckBox()
        debuff_grid.addWidget(self._chk_mailbreaker, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Venom Dust"), row, 0)
        self._chk_venom_dust = QCheckBox()
        debuff_grid.addWidget(self._chk_venom_dust, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Raided"), row, 0)
        self._chk_raided = QCheckBox()
        debuff_grid.addWidget(self._chk_raided, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Blessing Debuff"), row, 0)
        self._chk_blessing = QCheckBox()
        debuff_grid.addWidget(self._chk_blessing, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Provoke"), row, 0)
        self._lw_provoke = LevelWidget(10, include_off=True, item_prefix="Lv ")
        debuff_grid.addWidget(self._lw_provoke, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Decrease AGI"), row, 0)
        self._lw_decagi = LevelWidget(10, include_off=True, item_prefix="Lv ")
        debuff_grid.addWidget(self._lw_decagi, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Quagmire"), row, 0)
        self._lw_quagmire = LevelWidget(5, include_off=True, item_prefix="Lv ")
        debuff_grid.addWidget(self._lw_quagmire, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Don't Forget Me"), row, 0)
        self._lw_dontforgetme = LevelWidget(10, include_off=True, item_prefix="Lv ")
        self._sb_dfm_agi = NoWheelSpin()
        self._sb_dfm_agi.setRange(0, 999)
        self._sb_dfm_agi.setPrefix("AGI ")
        self._sb_dfm_agi.setFixedWidth(80)  # +8px vs default — see class docstring
        _dfm_row = QHBoxLayout()
        _dfm_row.setSpacing(4)
        _dfm_row.setContentsMargins(0, 0, 0, 0)
        _dfm_row.addWidget(self._lw_dontforgetme)
        _dfm_row.addWidget(self._sb_dfm_agi)
        _dfm_container = QWidget()
        _dfm_container.setLayout(_dfm_row)
        debuff_grid.addWidget(_dfm_container, row, 1)
        row += 1

        debuff_grid.addWidget(_lbl("Mind Breaker"), row, 0)
        self._lw_mindbreaker = LevelWidget(5, include_off=True, item_prefix="Lv ")
        debuff_grid.addWidget(self._lw_mindbreaker, row, 1)
        row += 1

        # GS_FLING: coin count thrown (1–5).  Vanilla: def_percent -= 5*coins.
        # PS: def_ -= 3*coins (flat hard DEF reduction).
        # Source: status.c:8356-8357, sc_config.conf:5721-5725 (no NoBoss flag).
        debuff_grid.addWidget(_lbl("Fling"), row, 0)
        self._lw_fling = LevelWidget(5, include_off=True, item_prefix="Lv ")
        debuff_grid.addWidget(self._lw_fling, row, 1)

        left_layout.addLayout(debuff_grid)

        # ── Middle column: Status Ailments ────────────────────────────────
        mid_col = QWidget()
        mid_layout = QVBoxLayout(mid_col)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(6)

        ailment_lbl = QLabel("Status Ailments")
        ailment_lbl.setObjectName("sub_group_title")
        mid_layout.addWidget(ailment_lbl)

        ailment_grid = QGridLayout()
        ailment_grid.setHorizontalSpacing(8)
        ailment_grid.setVerticalSpacing(4)
        ailment_grid.setColumnStretch(2, 1)

        row = 0
        ailment_grid.addWidget(_lbl("Stunned"), row, 0)
        self._chk_stun = QCheckBox()
        ailment_grid.addWidget(self._chk_stun, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Frozen"), row, 0)
        self._chk_freeze = QCheckBox()
        ailment_grid.addWidget(self._chk_freeze, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Petrified"), row, 0)
        self._chk_stone = QCheckBox()
        ailment_grid.addWidget(self._chk_stone, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Poisoned"), row, 0)
        self._chk_poison = QCheckBox()
        ailment_grid.addWidget(self._chk_poison, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Blind"), row, 0)
        self._chk_blind = QCheckBox()
        ailment_grid.addWidget(self._chk_blind, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Cursed"), row, 0)
        self._chk_curse = QCheckBox()
        ailment_grid.addWidget(self._chk_curse, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Asleep"), row, 0)
        self._chk_sleep = QCheckBox()
        ailment_grid.addWidget(self._chk_sleep, row, 1)
        row += 1

        ailment_grid.addWidget(_lbl("Hypothermia"), row, 0)
        self._chk_hypothermia = QCheckBox()
        ailment_grid.addWidget(self._chk_hypothermia, row, 1)

        mid_layout.addLayout(ailment_grid)

        # ── Right column: Monster State (hidden for player targets) ───────
        self._monster_state_widget = QWidget()
        ms_layout = QVBoxLayout(self._monster_state_widget)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_layout.setSpacing(6)

        ms_lbl = QLabel("Monster State")
        ms_lbl.setObjectName("sub_group_title")
        ms_layout.addWidget(ms_lbl)

        ms_grid = QGridLayout()
        ms_grid.setHorizontalSpacing(8)
        ms_grid.setVerticalSpacing(4)
        ms_grid.setColumnStretch(2, 1)

        ms_row = 0
        ms_grid.addWidget(_lbl("Element"), ms_row, 0)
        ele_row_w = QWidget()
        ele_row = QHBoxLayout(ele_row_w)
        ele_row.setContentsMargins(0, 0, 0, 0)
        ele_row.setSpacing(4)
        self._ele_combo = NoWheelCombo()
        self._ele_combo.addItem("(default)", -1)
        for idx, name in _ELEMENTS:
            self._ele_combo.addItem(name, idx)
        ele_row.addWidget(self._ele_combo)
        ele_row.addWidget(QLabel("Lv"))
        self._ele_lv = LevelWidget(4, include_off=False, item_prefix="")
        self._ele_lv.setEnabled(False)
        ele_row.addWidget(self._ele_lv)
        ele_row.addStretch()
        ms_grid.addWidget(ele_row_w, ms_row, 1)
        ms_row += 1

        ms_grid.addWidget(_lbl("Strip"), ms_row, 0)
        strip_w = QWidget()
        strip_row = QHBoxLayout(strip_w)
        strip_row.setContentsMargins(0, 0, 0, 0)
        strip_row.setSpacing(8)
        self._chk_strip_weapon = QCheckBox("Weapon")
        self._chk_strip_armor  = QCheckBox("Armor")
        self._chk_strip_shield = QCheckBox("Shield")
        self._chk_strip_helm   = QCheckBox("Helm")
        for chk in (self._chk_strip_weapon, self._chk_strip_armor,
                    self._chk_strip_shield, self._chk_strip_helm):
            strip_row.addWidget(chk)
        strip_row.addStretch()
        ms_grid.addWidget(strip_w, ms_row, 1)
        ms_row += 1

        ms_grid.addWidget(_lbl("Signum Crucis"), ms_row, 0)
        self._lw_crucis = LevelWidget(10, include_off=True, item_prefix="Lv ")
        ms_grid.addWidget(self._lw_crucis, ms_row, 1)

        ms_layout.addLayout(ms_grid)

        self.add_content_widget(make_side_by_side_row([left_col, mid_col, self._monster_state_widget], equal_width=False))

        # ── Connections ───────────────────────────────────────────────────
        self._chk_chaos.stateChanged.connect(self._emit)
        self._lw_provoke.valueChanged.connect(self._emit)
        self._lw_decagi.valueChanged.connect(self._emit)
        self._chk_lex.stateChanged.connect(self._emit)
        self._lw_quagmire.valueChanged.connect(self._emit)
        self._chk_hypothermia.stateChanged.connect(self._emit)
        self._lw_dontforgetme.valueChanged.connect(self._emit)
        self._sb_dfm_agi.valueChanged.connect(self._emit)
        self._lw_mindbreaker.valueChanged.connect(self._emit)
        self._chk_mailbreaker.stateChanged.connect(self._emit)
        self._chk_venom_dust.stateChanged.connect(self._emit)
        self._chk_raided.stateChanged.connect(self._emit)
        self._lw_fling.valueChanged.connect(self._emit)
        self._chk_stun.stateChanged.connect(self._emit)
        self._chk_freeze.stateChanged.connect(self._on_freeze_changed)
        self._chk_stone.stateChanged.connect(self._on_stone_changed)
        self._chk_poison.stateChanged.connect(self._emit)
        self._chk_blind.stateChanged.connect(self._emit)
        self._chk_curse.stateChanged.connect(self._emit)
        self._chk_sleep.stateChanged.connect(self._emit)
        self._ele_combo.currentIndexChanged.connect(self._on_ele_changed)
        self._ele_lv.valueChanged.connect(self._emit)
        self._chk_strip_weapon.stateChanged.connect(self._emit)
        self._chk_strip_armor.stateChanged.connect(self._emit)
        self._chk_strip_shield.stateChanged.connect(self._emit)
        self._chk_strip_helm.stateChanged.connect(self._emit)
        self._lw_crucis.valueChanged.connect(self._emit)
        self._chk_blessing.stateChanged.connect(self._emit)

    # ── Signal helpers ────────────────────────────────────────────────────

    def _emit(self, *_) -> None:
        self.state_changed.emit()

    def _on_freeze_changed(self, state: int) -> None:
        if state and self._chk_stone.isChecked():
            self._chk_stone.blockSignals(True)
            self._chk_stone.setChecked(False)
            self._chk_stone.blockSignals(False)
        self.state_changed.emit()

    def _on_stone_changed(self, state: int) -> None:
        if state and self._chk_freeze.isChecked():
            self._chk_freeze.blockSignals(True)
            self._chk_freeze.setChecked(False)
            self._chk_freeze.blockSignals(False)
        self.state_changed.emit()

    def _on_ele_changed(self) -> None:
        self._ele_lv.setEnabled(self._ele_combo.currentData() != -1)
        self.state_changed.emit()

    # ── Public API ────────────────────────────────────────────────────────

    def set_target_type(self, is_player: bool) -> None:
        """Show/hide monster-specific controls when target type changes."""
        self._monster_state_widget.setVisible(not is_player)

    def set_is_boss(self, is_boss: bool) -> None:
        """Disable boss-immune SCs when target is a boss."""
        boss_blocked = [
            self._chk_stun, self._chk_freeze, self._chk_stone,
            self._chk_sleep, self._chk_poison, self._chk_blind, self._chk_curse,
            self._lw_provoke, self._lw_decagi, self._chk_hypothermia,
        ]
        for w in boss_blocked:
            w.setEnabled(not is_boss)
            if is_boss:
                if hasattr(w, 'setChecked'):
                    w.setChecked(False)
                else:
                    w.setValue(0)

    def collect_into(self, build: PlayerBuild) -> None:
        """Persist deliberate target debuffs to build.target_debuffs.
        Also clears these keys from support_buffs for builds saved before they were moved to target_debuffs."""
        for key in ("SC_ETERNALCHAOS", "SC_PROVOKE", "SC_DECREASEAGI", "PR_LEXAETERNA",
                    "SC_QUAGMIRE", "SC_MINDBREAKER"):
            build.support_buffs.pop(key, None)

        td: dict = {}
        if self._chk_chaos.isChecked():
            td["SC_ETERNALCHAOS"] = 1
        prov_lv = self._lw_provoke.value()
        if prov_lv:
            td["SC_PROVOKE"] = prov_lv
        decagi_lv = self._lw_decagi.value()
        if decagi_lv:
            td["SC_DECREASEAGI"] = decagi_lv
        if self._chk_lex.isChecked():
            td["PR_LEXAETERNA"] = 1
        qua_lv = self._lw_quagmire.value()
        if qua_lv:
            td["SC_QUAGMIRE"] = qua_lv
        if self._chk_hypothermia.isChecked():
            td["SC_PS_HYPOTHERMIA"] = 1
        mb_lv = self._lw_mindbreaker.value()
        if mb_lv:
            td["SC_MINDBREAKER"] = mb_lv
        fling_lv = self._lw_fling.value()
        if fling_lv:
            td["SC_FLING"] = fling_lv
        build.target_debuffs = td

    def collect_target_player_scs(self) -> dict[str, int]:
        """Return stat-cascade SCs as a dict for player targets.

        These SCs have effects that flow through StatusCalculator (e.g. AGI → FLEE,
        LUK → BATK) and must be merged into pvp_eff.player_active_scs *before*
        StatusCalculator runs on the pvp build.  Mob targets receive the same
        effects via target_utils.apply_mob_scs() instead.

        """
        scs: dict[str, int] = {}
        decagi_lv = self._lw_decagi.value()
        if decagi_lv:
            scs["SC_DECREASEAGI"] = decagi_lv
        if self._chk_blind.isChecked():
            scs["SC_BLIND"] = 1
        if self._chk_curse.isChecked():
            scs["SC_CURSE"] = 1
        if self._chk_sleep.isChecked():
            scs["SC_SLEEP"] = 1
        qua_lv = self._lw_quagmire.value()
        if qua_lv:
            scs["SC_QUAGMIRE"] = qua_lv
        if self._chk_hypothermia.isChecked():
            scs["SC_PS_HYPOTHERMIA"] = 1
        mb_lv = self._lw_mindbreaker.value()
        if mb_lv:
            scs["SC_MINDBREAKER"] = mb_lv
        if self._chk_chaos.isChecked():
            scs["SC_ETERNALCHAOS"] = 1
        prov_lv = self._lw_provoke.value()
        if prov_lv:
            scs["SC_PROVOKE"] = prov_lv
        fling_lv = self._lw_fling.value()
        if fling_lv:
            scs["SC_FLING"] = fling_lv
        return scs

    def apply_to_target(self, target: Target) -> None:
        """Write pipeline-level effects directly to the resolved Target.

        Sets target_active_scs flags (force-hit, DEF-halving), element overrides,
        and DEF strip.  Stat-cascade effects (agi, luk, mdef_ mutations) are NOT
        done here — they are handled by target_utils.apply_mob_scs() for mob targets
        or StatusCalculator for player targets.

        Called in _run_battle_pipeline() after target resolution.
        No element restore needed — target is re-resolved each pipeline run.
        """
        scs: dict[str, int] = {}

        # Monster State — element override (applied first; ailments below may overwrite)
        if not target.is_pc:
            ele = self._ele_combo.currentData()
            if ele != -1:
                target.element = ele
                target.element_level = self._ele_lv.value()

        # Status ailments → target_active_scs flags + element override for Freeze/Stone.
        # Stat mutations (agi, luk, etc.) are intentionally absent here — see docstring.
        if self._chk_stun.isChecked():
            scs["SC_STUN"] = 1

        if self._chk_freeze.isChecked():
            scs["SC_FREEZE"] = 1
            target.element = 1        # Ele_Water (status.c:5880-5881, 5901-5902)
            target.element_level = 1

        if self._chk_stone.isChecked():
            scs["SC_STONE"] = 1
            target.element = 2        # Ele_Earth (status.c:5882-5883, 5901-5903)
            target.element_level = 1

        if self._chk_poison.isChecked():
            scs["SC_POISON"] = 1
        if self._chk_blind.isChecked():
            scs["SC_BLIND"] = 1
        if self._chk_curse.isChecked():
            scs["SC_CURSE"] = 1
        if self._chk_sleep.isChecked():
            scs["SC_SLEEP"] = 1

        decagi_lv = self._lw_decagi.value()
        if decagi_lv:
            scs["SC_DECREASEAGI"] = decagi_lv
        qua_lv = self._lw_quagmire.value()
        if qua_lv:
            scs["SC_QUAGMIRE"] = qua_lv
        if self._chk_hypothermia.isChecked():
            scs["SC_PS_HYPOTHERMIA"] = 1
        dfm_lv = self._lw_dontforgetme.value()
        if dfm_lv:
            scs["SC_DONTFORGETME"] = dfm_lv
            scs["SC_DONTFORGETME_agi"] = self._sb_dfm_agi.value()
        mb_lv = self._lw_mindbreaker.value()
        if mb_lv:
            scs["SC_MINDBREAKER"] = mb_lv

        if self._chk_chaos.isChecked():
            scs["SC_ETERNALCHAOS"] = 1
        prov_lv = self._lw_provoke.value()
        if prov_lv:
            scs["SC_PROVOKE"] = prov_lv
        fling_lv = self._lw_fling.value()
        if fling_lv:
            scs["SC_FLING"] = fling_lv
        if self._chk_lex.isChecked():
            scs["PR_LEXAETERNA"] = 1
        if self._chk_mailbreaker.isChecked() and not target.is_boss:
            target.mailbreaker = True
        if self._chk_venom_dust.isChecked():
            target.venom_dust = True
        if self._chk_raided.isChecked():
            target.raided = True

        # Monster-only SCs
        if not target.is_pc:
            crucis_lv = self._lw_crucis.value()
            if crucis_lv:
                scs["SC_CRUCIS"] = crucis_lv
            if self._chk_blessing.isChecked():
                scs["SC_BLESSING"] = 1
            # Strip flags — stat mutations applied in apply_mob_scs() with server branching.
            # Weapon ATK reduction consumed by incoming_physical_pipeline via main_window.py.
            # INT reduction also consumed by incoming_magic_pipeline via main_window.py.
            if self._chk_strip_weapon.isChecked():
                scs["SC_NOEQUIPWEAPON"] = 1
            if self._chk_strip_shield.isChecked():
                scs["SC_NOEQUIPSHIELD"] = 1
            if self._chk_strip_armor.isChecked():
                scs["SC_NOEQUIPARMOR"] = 1
            if self._chk_strip_helm.isChecked():
                scs["SC_NOEQUIPHELM"] = 1

        target.target_active_scs = scs

    def load_build(self, build: PlayerBuild) -> None:
        """Restore persisted debuff levels from build.target_debuffs.
        Ailments and Monster State are session-only and always reset."""
        td = build.target_debuffs
        all_widgets = [
            self._chk_chaos, self._lw_provoke, self._lw_decagi, self._chk_lex,
            self._lw_quagmire, self._chk_hypothermia,
            self._lw_dontforgetme, self._sb_dfm_agi, self._lw_mindbreaker,
            self._chk_mailbreaker, self._chk_venom_dust, self._chk_raided, self._lw_fling,
            self._chk_stun, self._chk_freeze, self._chk_stone, self._chk_poison,
            self._chk_blind, self._chk_curse, self._chk_sleep,
            self._ele_combo, self._ele_lv,
            self._chk_strip_weapon, self._chk_strip_armor,
            self._chk_strip_shield, self._chk_strip_helm,
            self._lw_crucis, self._chk_blessing,
        ]
        for w in all_widgets:
            w.blockSignals(True)

        # Persisted debuffs
        self._chk_chaos.setChecked(bool(td.get("SC_ETERNALCHAOS", False)))
        self._lw_provoke.setValue(int(td.get("SC_PROVOKE", 0)))
        self._lw_decagi.setValue(int(td.get("SC_DECREASEAGI", 0)))
        self._chk_lex.setChecked(bool(td.get("PR_LEXAETERNA", False)))
        self._lw_quagmire.setValue(int(td.get("SC_QUAGMIRE", 0)))
        self._chk_hypothermia.setChecked(bool(td.get("SC_PS_HYPOTHERMIA", False)))
        self._lw_mindbreaker.setValue(int(td.get("SC_MINDBREAKER", 0)))
        self._lw_fling.setValue(int(td.get("SC_FLING", 0)))

        # Session-only — always reset on build load
        self._lw_dontforgetme.setValue(0)
        self._sb_dfm_agi.setValue(0)
        self._chk_mailbreaker.setChecked(False)
        self._chk_venom_dust.setChecked(False)
        self._chk_raided.setChecked(False)
        self._chk_stun.setChecked(False)
        self._chk_freeze.setChecked(False)
        self._chk_stone.setChecked(False)
        self._chk_poison.setChecked(False)
        self._chk_blind.setChecked(False)
        self._chk_curse.setChecked(False)
        self._chk_sleep.setChecked(False)
        self._ele_combo.setCurrentIndex(0)   # (default)
        self._ele_lv.setValue(1)
        self._ele_lv.setEnabled(False)
        self._chk_strip_weapon.setChecked(False)
        self._chk_strip_armor.setChecked(False)
        self._chk_strip_shield.setChecked(False)
        self._chk_strip_helm.setChecked(False)
        self._lw_crucis.setValue(0)
        self._chk_blessing.setChecked(False)

        for w in all_widgets:
            w.blockSignals(False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("combat_field_label")
    return lbl


def _hline() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setObjectName("section_separator")
    return sep
