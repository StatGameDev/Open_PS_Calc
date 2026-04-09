"""
ConsumablesSection — stat foods, ASPD potions, ATK/MATK items, and combat stat consumables.

All widgets write to build.consumable_buffs.
Routing is handled by compute_consumable_bonuses() in build_applicator.py.

SC conflict routing (status.c:7362-7363): max() per SC slot.
Per-stat food, all-stat food, and Grilled Corn share SC_FOOD_STR/AGI/INT slots.
SC_PLUSMAGICPOWER (matk_item) and SC_MATKFOOD (matk_food) are separate slots — they stack.
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
from gui.widgets import NoWheelCombo


class ConsumablesSection(Section):

    changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        row = 0

        # ── Stat Foods row — 6 inline small dropdowns ─────────────────────
        # Each combo: first item = stat name (value 0 = off)
        grid.addWidget(_lbl("Stat Foods"), row, 0)
        stat_food_row = QWidget()
        stat_food_layout = QHBoxLayout(stat_food_row)
        stat_food_layout.setContentsMargins(0, 0, 0, 0)
        stat_food_layout.setSpacing(3)

        _stat_names = ("STR", "AGI", "VIT", "INT", "DEX", "LUK")
        _stat_keys  = ("food_str", "food_agi", "food_vit", "food_int", "food_dex", "food_luk")
        self._stat_combos: dict[str, NoWheelCombo] = {}
        for stat, key in zip(_stat_names, _stat_keys):
            cb = NoWheelCombo()
            cb.setFixedWidth(52)
            cb.addItem(stat, userData=0)
            for v in range(1, 11):
                cb.addItem(f"+{v}", userData=v)
            if key == "food_luk":
                # Lucky Potion (+15), Charm Of Luck (+20), Lucky Rice Cake (+21)
                cb.addItem("+15", userData=15)
                cb.addItem("+20", userData=20)
                cb.addItem("+21", userData=21)
            self._stat_combos[key] = cb
            stat_food_layout.addWidget(cb)

        stat_food_layout.addStretch()
        grid.addWidget(stat_food_row, row, 1)
        row += 1

        # ── All-Stats Food ─────────────────────────────────────────────────
        grid.addWidget(_lbl("All-Stats Food"), row, 0)
        self._cb_food_all = NoWheelCombo()
        self._cb_food_all.addItem("No All-Stats Food", userData=0)
        self._cb_food_all.addItem("Halo-Halo / Luxurious Western Food (+3 all)", userData=3)
        self._cb_food_all.addItem("Manchu-Han Imperial Feast (+6 all)", userData=6)
        self._cb_food_all.addItem("Charm Of Happiness (+10 all)", userData=10)
        grid.addWidget(self._cb_food_all, row, 1)
        row += 1

        # ── Grilled Corn ───────────────────────────────────────────────────
        self._chk_grilled_corn = QCheckBox("Grilled Corn")
        self._chk_grilled_corn.setToolTip("+2 STR, +2 AGI, +2 INT (SC_FOOD_*; conflicts with higher stat food)")
        grid.addWidget(self._chk_grilled_corn, row, 0, 1, 2)
        row += 1

        # ── ASPD Potion ────────────────────────────────────────────────────
        grid.addWidget(_lbl("ASPD Potion"), row, 0)
        self._cb_aspd_potion = NoWheelCombo()
        self._cb_aspd_potion.addItem("No ASPD Potion", userData=0)
        self._cb_aspd_potion.addItem("Concentration Potion (+10% ASPD)", userData=1)
        self._cb_aspd_potion.addItem("Awakening Potion (+15% ASPD)", userData=2)
        self._cb_aspd_potion.addItem("Berserk Potion (+20% ASPD) — Berserk Potion Pitcher", userData=3)
        grid.addWidget(self._cb_aspd_potion, row, 1)
        row += 1

        # ── HIT Food ───────────────────────────────────────────────────────
        grid.addWidget(_lbl("HIT Food"), row, 0)
        self._cb_hit_food = NoWheelCombo()
        self._cb_hit_food.addItem("HIT Food", userData=0)
        self._cb_hit_food.addItem("+10 HIT  (Schwartzwald Pine Jubilee)", userData=10)
        self._cb_hit_food.addItem("+20 HIT  (Schwartzwald Pine Jubilee tier 2)", userData=20)
        self._cb_hit_food.addItem("+30 HIT  (Grilled Skewer / Sesame Pastry / Concentration Scroll)", userData=30)
        self._cb_hit_food.addItem("+33 HIT  (Military Ration B)", userData=33)
        self._cb_hit_food.addItem("+100 HIT  (Phreeoni Scroll)", userData=100)
        grid.addWidget(self._cb_hit_food, row, 1)
        row += 1

        # ── FLEE Food ──────────────────────────────────────────────────────
        grid.addWidget(_lbl("FLEE Food"), row, 0)
        self._cb_flee_food = NoWheelCombo()
        self._cb_flee_food.addItem("FLEE Food", userData=0)
        self._cb_flee_food.addItem("+10 FLEE  (Spray of Flowers)", userData=10)
        self._cb_flee_food.addItem("+20 FLEE  (Schwartzwald Pine Jubilee)", userData=20)
        self._cb_flee_food.addItem("+30 FLEE  (Citron / Honey Pastry / Evasion Scroll)", userData=30)
        self._cb_flee_food.addItem("+33 FLEE  (Military Ration C)", userData=33)
        grid.addWidget(self._cb_flee_food, row, 1)
        row += 1

        # ── CRI Food ───────────────────────────────────────────────────────
        self._chk_cri_food = QCheckBox("Arunafeltz Desert Sandwich")
        self._chk_cri_food.setToolTip("+7 CRI (SC_FOOD_CRITICALSUCCESSVALUE; status.c:4751)")
        grid.addWidget(self._chk_cri_food, row, 0, 1, 2)
        row += 1

        # ── ATK Items ──────────────────────────────────────────────────────
        # SC_PLUSATTACKPOWER: batk += val1 (status.c:4476, #ifndef RENEWAL)
        grid.addWidget(_lbl("ATK Item"), row, 0)
        self._cb_atk_item = NoWheelCombo()
        self._cb_atk_item.addItem("ATK Food", userData=0)
        self._cb_atk_item.addItem("Rune Strawberry Cake (+5)", userData=5)
        self._cb_atk_item.addItem("Durian / Chewy Ricecake / Rainbow Cake (+10)", userData=10)
        self._cb_atk_item.addItem("Tasty Pink Ration (+15)", userData=15)
        self._cb_atk_item.addItem("Box of Resentment / Tyr's Blessing (+20)", userData=20)
        self._cb_atk_item.addItem("Distilled Fighting Spirit (+30)", userData=30)
        grid.addWidget(self._cb_atk_item, row, 1)
        row += 1

        # ── MATK Items ─────────────────────────────────────────────────────
        # SC_PLUSMAGICPOWER: matk += val1 (status.c:4635-4636)
        grid.addWidget(_lbl("MATK Item"), row, 0)
        self._cb_matk_item = NoWheelCombo()
        self._cb_matk_item.addItem("MATK Food", userData=0)
        self._cb_matk_item.addItem("Rune Strawberry Cake (+5)", userData=5)
        self._cb_matk_item.addItem("Durian / Oriental Pastry / Rainbow Cake (+10)", userData=10)
        self._cb_matk_item.addItem("Tasty White Ration (+15)", userData=15)
        self._cb_matk_item.addItem("Box of Drowsiness / Tyr's Blessing (+20)", userData=20)
        self._cb_matk_item.addItem("Herb of Incantation (+30)", userData=30)
        grid.addWidget(self._cb_matk_item, row, 1)
        row += 1

        # ── MATK Food (Rainbow Cake / SC_MATKFOOD) ─────────────────────────
        # SC_MATKFOOD (item 12124): separate SC slot, stacks with SC_PLUSMAGICPOWER
        self._chk_matk_food = QCheckBox("Rainbow Cake (SC_MATKFOOD, stacks)")
        self._chk_matk_food.setToolTip("+10 MATK flat, stacks with MATK Items above. Source: status.c:4637-4638")
        grid.addWidget(self._chk_matk_food, row, 0, 1, 2)

        container = QWidget()
        container.setLayout(grid)
        self.add_content_widget(container)

        # ── Connections ───────────────────────────────────────────────────
        for cb in self._stat_combos.values():
            cb.currentIndexChanged.connect(self._emit)
        self._cb_food_all.currentIndexChanged.connect(self._emit)
        self._chk_grilled_corn.stateChanged.connect(self._emit)
        self._cb_aspd_potion.currentIndexChanged.connect(self._emit)
        self._cb_hit_food.currentIndexChanged.connect(self._emit)
        self._cb_flee_food.currentIndexChanged.connect(self._emit)
        self._chk_cri_food.stateChanged.connect(self._emit)
        self._cb_atk_item.currentIndexChanged.connect(self._emit)
        self._cb_matk_item.currentIndexChanged.connect(self._emit)
        self._chk_matk_food.stateChanged.connect(self._emit)

    def _emit(self, *_) -> None:
        self._update_summary()
        self.changed.emit()

    def _update_summary(self) -> None:
        """Build a concise header summary of active consumables."""
        parts: list[str] = []
        for key, cb in self._stat_combos.items():
            v = cb.currentData()
            if v:
                stat = key.replace("food_", "").upper()
                parts.append(f"+{v} {stat}")
        food_all = self._cb_food_all.currentData()
        if food_all:
            parts.append(f"+{food_all} All")
        if self._chk_grilled_corn.isChecked():
            parts.append("+2 STR/AGI/INT")
        aspd = self._cb_aspd_potion.currentData()
        if aspd:
            _pct = (0, 10, 15, 20)[aspd]
            parts.append(f"+{_pct}% ASPD")
        hit = self._cb_hit_food.currentData()
        if hit:
            parts.append(f"+{hit} HIT")
        flee = self._cb_flee_food.currentData()
        if flee:
            parts.append(f"+{flee} FLEE")
        if self._chk_cri_food.isChecked():
            parts.append("+7 CRI")
        atk = self._cb_atk_item.currentData()
        if atk:
            parts.append(f"+{atk} ATK")
        matk = self._cb_matk_item.currentData()
        matk_food = self._chk_matk_food.isChecked()
        matk_total = matk + (10 if matk_food else 0)
        if matk_total:
            parts.append(f"+{matk_total} MATK")
        self.set_header_summary(", ".join(parts) if parts else "")

    # ── Public API ─────────────────────────────────────────────────────────

    def load_build(self, build: PlayerBuild) -> None:
        cb = build.consumable_buffs
        all_widgets: list = list(self._stat_combos.values()) + [
            self._cb_food_all, self._chk_grilled_corn,
            self._cb_aspd_potion, self._cb_hit_food, self._cb_flee_food,
            self._chk_cri_food, self._cb_atk_item, self._cb_matk_item,
            self._chk_matk_food,
        ]
        for w in all_widgets:
            w.blockSignals(True)

        for key, combo in self._stat_combos.items():
            v = int(cb.get(key, 0))
            idx = combo.findData(v)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        food_all = int(cb.get("food_all", 0))
        idx = self._cb_food_all.findData(food_all)
        self._cb_food_all.setCurrentIndex(idx if idx >= 0 else 0)

        self._chk_grilled_corn.setChecked(bool(cb.get("grilled_corn", False)))

        aspd_potion = int(cb.get("aspd_potion", 0))
        idx = self._cb_aspd_potion.findData(aspd_potion)
        self._cb_aspd_potion.setCurrentIndex(idx if idx >= 0 else 0)

        hit_food = int(cb.get("hit_food", 0))
        idx = self._cb_hit_food.findData(hit_food)
        self._cb_hit_food.setCurrentIndex(idx if idx >= 0 else 0)

        flee_food = int(cb.get("flee_food", 0))
        idx = self._cb_flee_food.findData(flee_food)
        self._cb_flee_food.setCurrentIndex(idx if idx >= 0 else 0)

        self._chk_cri_food.setChecked(bool(cb.get("cri_food", False)))

        atk_item = int(cb.get("atk_item", 0))
        idx = self._cb_atk_item.findData(atk_item)
        self._cb_atk_item.setCurrentIndex(idx if idx >= 0 else 0)

        matk_item = int(cb.get("matk_item", 0))
        idx = self._cb_matk_item.findData(matk_item)
        self._cb_matk_item.setCurrentIndex(idx if idx >= 0 else 0)

        self._chk_matk_food.setChecked(bool(cb.get("matk_food", False)))

        for w in all_widgets:
            w.blockSignals(False)

        self._update_summary()

    def collect_into(self, build: PlayerBuild) -> None:
        cons: dict[str, object] = {}

        for key, combo in self._stat_combos.items():
            v = combo.currentData()
            if v:
                cons[key] = v

        food_all = self._cb_food_all.currentData()
        if food_all:
            cons["food_all"] = food_all

        if self._chk_grilled_corn.isChecked():
            cons["grilled_corn"] = True

        aspd_potion = self._cb_aspd_potion.currentData()
        if aspd_potion:
            cons["aspd_potion"] = aspd_potion

        hit_food = self._cb_hit_food.currentData()
        if hit_food:
            cons["hit_food"] = hit_food

        flee_food = self._cb_flee_food.currentData()
        if flee_food:
            cons["flee_food"] = flee_food

        if self._chk_cri_food.isChecked():
            cons["cri_food"] = True

        atk_item = self._cb_atk_item.currentData()
        if atk_item:
            cons["atk_item"] = atk_item

        matk_item = self._cb_matk_item.currentData()
        if matk_item:
            cons["matk_item"] = matk_item

        if self._chk_matk_food.isChecked():
            cons["matk_food"] = True

        build.consumable_buffs = cons


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("combat_field_label")
    return lbl
