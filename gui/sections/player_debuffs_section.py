"""
PlayerDebuffsSection — debuffs the enemy has applied to the player.

Mirrors what TargetStateSection does for mob targets, but for the local player.
All widgets write to build.player_active_scs.

Effects by destination:
  status_calculator.py  — SC_CURSE (luk/batk), SC_BLIND (hit/flee), SC_DECREASEAGI (agi),
                          SC_QUAGMIRE (agi/dex), SC_PS_HYPOTHERMIA (dex/aspd/cast_time_penalty),
                          SC_MINDBREAKER (mdef/matk), SC_POISON (def_percent),
                          SC_PROVOKE (def_percent), SC_ETERNALCHAOS (def2=0),
                          SC_DONTFORGETME (aspd)
  build_manager.py player_build_to_target() — SC_STUN/FREEZE/STONE/SLEEP
                                               (force-hit flag + element)
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from core.models.build import PlayerBuild
from gui.section import Section
from gui.widgets import LevelWidget, NoWheelSpin


class PlayerDebuffsSection(Section):

    changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)  # label absorbs spare width; value widgets stay natural size

        row = 0

        # ── Stat debuffs ─────────────────────────────────────────────────
        grid.addWidget(_lbl("Curse"), row, 0)
        self._chk_curse = QCheckBox()
        grid.addWidget(self._chk_curse, row, 1)
        row += 1

        grid.addWidget(_lbl("Blind"), row, 0)
        self._chk_blind = QCheckBox()
        grid.addWidget(self._chk_blind, row, 1)
        row += 1

        grid.addWidget(_lbl("Decrease AGI"), row, 0)
        self._lw_decagi = LevelWidget(10, include_off=True, item_prefix="Lv ")
        grid.addWidget(self._lw_decagi, row, 1)
        row += 1

        grid.addWidget(_lbl("Quagmire"), row, 0)
        self._lw_quagmire = LevelWidget(5, include_off=True, item_prefix="Lv ")
        grid.addWidget(self._lw_quagmire, row, 1)
        row += 1

        grid.addWidget(_lbl("Hypothermia (PS)"), row, 0)
        self._chk_hypothermia = QCheckBox()
        grid.addWidget(self._chk_hypothermia, row, 1)
        row += 1

        grid.addWidget(_lbl("Mind Breaker"), row, 0)
        self._lw_mindbreaker = LevelWidget(5, include_off=True, item_prefix="Lv ")
        grid.addWidget(self._lw_mindbreaker, row, 1)
        row += 1

        grid.addWidget(_lbl("Poison"), row, 0)
        self._chk_poison = QCheckBox()
        grid.addWidget(self._chk_poison, row, 1)
        row += 1

        grid.addWidget(_lbl("Provoke"), row, 0)
        self._lw_provoke = LevelWidget(10, include_off=True, item_prefix="Lv ")
        grid.addWidget(self._lw_provoke, row, 1)
        row += 1

        grid.addWidget(_lbl("Eternal Chaos"), row, 0)
        self._chk_eternalchaos = QCheckBox()
        grid.addWidget(self._chk_eternalchaos, row, 1)
        row += 1

        grid.addWidget(_lbl("Don't Forget Me"), row, 0)
        self._lw_dontforgetme = LevelWidget(10, include_off=True, item_prefix="Lv ")
        self._sb_dfm_agi = NoWheelSpin()
        self._sb_dfm_agi.setRange(0, 999)
        self._sb_dfm_agi.setPrefix("AGI ")
        self._sb_dfm_agi.setFixedWidth(80)
        _dfm_row = QHBoxLayout()
        _dfm_row.setSpacing(4)
        _dfm_row.setContentsMargins(0, 0, 0, 0)
        _dfm_row.addWidget(self._lw_dontforgetme)
        _dfm_row.addWidget(self._sb_dfm_agi)
        _dfm_container = QWidget()
        _dfm_container.setLayout(_dfm_row)
        grid.addWidget(_dfm_container, row, 1)
        row += 1

        # ── Force-hit ailments (incoming pipeline) ────────────────────────
        grid.addWidget(_lbl("Stunned"), row, 0)
        self._chk_stun = QCheckBox()
        grid.addWidget(self._chk_stun, row, 1)
        row += 1

        grid.addWidget(_lbl("Frozen"), row, 0)
        self._chk_freeze = QCheckBox()
        grid.addWidget(self._chk_freeze, row, 1)
        row += 1

        grid.addWidget(_lbl("Petrified"), row, 0)
        self._chk_stone = QCheckBox()
        grid.addWidget(self._chk_stone, row, 1)
        row += 1

        grid.addWidget(_lbl("Asleep"), row, 0)
        self._chk_sleep = QCheckBox()
        grid.addWidget(self._chk_sleep, row, 1)
        row += 1

        # ── Damage multiplier debuffs ─────────────────────────────────────
        grid.addWidget(_lbl("Lex Aeterna"), row, 0)
        self._chk_lexaeterna = QCheckBox()
        grid.addWidget(self._chk_lexaeterna, row, 1)

        container = QWidget()
        container.setLayout(grid)
        self.add_content_widget(container)

        # ── Connections ───────────────────────────────────────────────────
        self._chk_curse.stateChanged.connect(self._emit)
        self._chk_blind.stateChanged.connect(self._emit)
        self._lw_decagi.valueChanged.connect(self._emit)
        self._lw_quagmire.valueChanged.connect(self._emit)
        self._chk_hypothermia.stateChanged.connect(self._emit)
        self._lw_mindbreaker.valueChanged.connect(self._emit)
        self._chk_poison.stateChanged.connect(self._emit)
        self._lw_provoke.valueChanged.connect(self._emit)
        self._chk_eternalchaos.stateChanged.connect(self._emit)
        self._lw_dontforgetme.valueChanged.connect(self._emit)
        self._sb_dfm_agi.valueChanged.connect(self._emit)
        self._chk_stun.stateChanged.connect(self._emit)
        self._chk_freeze.stateChanged.connect(self._on_freeze_changed)
        self._chk_stone.stateChanged.connect(self._on_stone_changed)
        self._chk_sleep.stateChanged.connect(self._emit)
        self._chk_lexaeterna.stateChanged.connect(self._emit)

    def _emit(self, *_) -> None:
        self.changed.emit()

    def _on_freeze_changed(self, state: int) -> None:
        if state and self._chk_stone.isChecked():
            self._chk_stone.blockSignals(True)
            self._chk_stone.setChecked(False)
            self._chk_stone.blockSignals(False)
        self.changed.emit()

    def _on_stone_changed(self, state: int) -> None:
        if state and self._chk_freeze.isChecked():
            self._chk_freeze.blockSignals(True)
            self._chk_freeze.setChecked(False)
            self._chk_freeze.blockSignals(False)
        self.changed.emit()

    # ── Public API ─────────────────────────────────────────────────────────

    def load_build(self, build: PlayerBuild) -> None:
        scs = build.player_active_scs
        all_widgets = [
            self._chk_curse, self._chk_blind, self._lw_decagi,
            self._lw_quagmire, self._chk_hypothermia, self._lw_mindbreaker, self._chk_poison,
            self._lw_provoke, self._chk_eternalchaos,
            self._lw_dontforgetme, self._sb_dfm_agi,
            self._chk_stun, self._chk_freeze, self._chk_stone, self._chk_sleep,
            self._chk_lexaeterna,
        ]
        for w in all_widgets:
            w.blockSignals(True)
        self._chk_curse.setChecked(bool(scs.get("SC_CURSE", False)))
        self._chk_blind.setChecked(bool(scs.get("SC_BLIND", False)))
        self._lw_decagi.setValue(int(scs.get("SC_DECREASEAGI", 0)))
        self._lw_quagmire.setValue(int(scs.get("SC_QUAGMIRE", 0)))
        self._chk_hypothermia.setChecked(bool(scs.get("SC_PS_HYPOTHERMIA", False)))
        self._lw_mindbreaker.setValue(int(scs.get("SC_MINDBREAKER", 0)))
        self._chk_poison.setChecked(bool(scs.get("SC_POISON", False)))
        self._lw_provoke.setValue(int(scs.get("SC_PROVOKE", 0)))
        self._chk_eternalchaos.setChecked(bool(scs.get("SC_ETERNALCHAOS", False)))
        self._lw_dontforgetme.setValue(int(scs.get("SC_DONTFORGETME", 0)))
        self._sb_dfm_agi.setValue(int(scs.get("SC_DONTFORGETME_agi", 0)))
        self._chk_stun.setChecked(bool(scs.get("SC_STUN", False)))
        self._chk_freeze.setChecked(bool(scs.get("SC_FREEZE", False)))
        self._chk_stone.setChecked(bool(scs.get("SC_STONE", False)))
        self._chk_sleep.setChecked(bool(scs.get("SC_SLEEP", False)))
        self._chk_lexaeterna.setChecked(bool(scs.get("PR_LEXAETERNA", False)))
        for w in all_widgets:
            w.blockSignals(False)

    def collect_into(self, build: PlayerBuild) -> None:
        scs: dict[str, int] = {}
        if self._chk_curse.isChecked():
            scs["SC_CURSE"] = 1
        if self._chk_blind.isChecked():
            scs["SC_BLIND"] = 1
        decagi_lv = self._lw_decagi.value()
        if decagi_lv:
            scs["SC_DECREASEAGI"] = decagi_lv
        qua_lv = self._lw_quagmire.value()
        if qua_lv:
            scs["SC_QUAGMIRE"] = qua_lv
        if self._chk_hypothermia.isChecked():
            scs["SC_PS_HYPOTHERMIA"] = 1
        mb_lv = self._lw_mindbreaker.value()
        if mb_lv:
            scs["SC_MINDBREAKER"] = mb_lv
        if self._chk_poison.isChecked():
            scs["SC_POISON"] = 1
        prov_lv = self._lw_provoke.value()
        if prov_lv:
            scs["SC_PROVOKE"] = prov_lv
        if self._chk_eternalchaos.isChecked():
            scs["SC_ETERNALCHAOS"] = 1
        dfm_lv = self._lw_dontforgetme.value()
        if dfm_lv:
            scs["SC_DONTFORGETME"] = dfm_lv
            scs["SC_DONTFORGETME_agi"] = self._sb_dfm_agi.value()
        if self._chk_stun.isChecked():
            scs["SC_STUN"] = 1
        if self._chk_freeze.isChecked():
            scs["SC_FREEZE"] = 1
        if self._chk_stone.isChecked():
            scs["SC_STONE"] = 1
        if self._chk_sleep.isChecked():
            scs["SC_SLEEP"] = 1
        if self._chk_lexaeterna.isChecked():
            scs["PR_LEXAETERNA"] = 1
        build.player_active_scs = scs


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("combat_field_label")
    return lbl
