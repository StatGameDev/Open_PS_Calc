"""
EquipmentSection — equipment slot controls (item selection, refine, cards, forge).

One row per slot (right_hand through head_low). Inline combos for quick item selection;
Edit button opens EquipmentBrowserDialog. Card rows shown per item slot count.
Forge controls (right_hand / left_hand) appear for forgeable weapons.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.data_loader import loader
from core.models.build import PlayerBuild
from gui.section import Section
from gui.widgets import NoScrollCombo, NoWheelSpin

# Weapon types that occupy both hands (F5: disables left_hand slot).
# These use loc=EQP_ARMS in item_db and block the left hand entirely.
_TWO_HANDED_WEAPON_TYPES: frozenset[str] = frozenset({
    "2HSword", "2HSpear", "2HAxe", "2HStaff",
    "Bow", "MusicalInstrument", "Whip", "Katar", "Fuuma",
    "Revolver", "Rifle", "Gatling", "Shotgun", "Grenade",
})

# Jobs that may equip 1H weapons (dual-wield) in left hand (F6).
# All jobs can use shields; only these jobs additionally see 1H weapons in the browser.
_DUAL_WIELD_JOBS: frozenset[int] = frozenset({12, 4013})  # Assassin, Assassin Cross

# (slot_key, display_label, has_refine)
_SLOTS: list[tuple[str, str, bool]] = [
    ("right_hand", "R. Hand",  True),
    ("left_hand",  "L. Hand",  True),
    ("ammo",       "Ammo",     False),
    ("armor",      "Armor",    True),
    ("garment",    "Garment",  True),
    ("footwear",   "Footwear", True),
    ("acc_l",      "Acc. L",   False),
    ("acc_r",      "Acc. R",   False),
    ("head_top",   "Head Top", True),
    ("head_mid",   "Head Mid", False),
    ("head_low",   "Head Low", False),
]

# Element names indexed by ID 0-9 (Hercules order)
_ELEMENT_NAMES = [
    "Neutral", "Water", "Earth", "Fire", "Wind",
    "Poison", "Holy", "Dark", "Ghost", "Undead",
]

# Weapons that can be created by Blacksmith forging (base names, no slot suffix)
_FORGEABLE_WEAPON_NAMES: frozenset[str] = frozenset({
    "Knife", "Cutter", "Main Gauche", "Dirk", "Dagger", "Stiletto",
    "Gladius", "Damascus", "Sword", "Falchion", "Blade", "Rapier",
    "Scimitar", "Ring Pommel Saber", "Tsurugi", "Haedonggum", "Saber",
    "Flamberge", "Katana", "Slayer", "Bastard Sword", "Two-Handed Sword",
    "Broad Sword", "Claymore",
    "Axe", "Battle Axe", "Hammer", "Buster", "Two-Handed Axe",
    "Club", "Mace", "Smasher", "Flail", "Chain", "Morning Star",
    "Sword Mace", "Stunner",
    "Waghnak", "Knuckle Dusters", "Studded Knuckles", "Fist", "Claw", "Finger",
    "Javelin", "Spear", "Pike", "Guisarme", "Glaive", "Partizan",
    "Lance", "Trident", "Halberd",
})


def _strip_slot_suffix(name: str) -> str:
    """Strip trailing ' [N]' from item name (e.g. 'Buckler [1]' → 'Buckler')."""
    return re.sub(r'\s*\[\d+\]\s*$', '', name.strip())


def _item_stat_key(item: dict) -> tuple:
    """Hashable key of all gameplay-relevant fields except id, name, aegis_name, slots."""
    return (
        item.get("type"),
        item.get("weight", 0),
        item.get("equip_level", 0),
        tuple(sorted(item.get("loc", []))),
        item.get("upper", 0),
        tuple(sorted(item.get("job", []))),
        item.get("gender"),
        item.get("script", ""),
        item.get("on_equip", ""),
        item.get("on_unequip", ""),
        # IT_WEAPON
        item.get("atk", 0),
        item.get("level"),
        item.get("weapon_type"),
        item.get("element"),
        item.get("refineable"),
        item.get("range"),
        # IT_ARMOR
        item.get("def", 0),
        # IT_AMMO
        item.get("subtype"),
    )


def _is_forgeable_weapon(item: dict) -> bool:
    """Return True if the item is a Blacksmith-forgeable weapon."""
    if item.get("type") != "IT_WEAPON":
        return False
    name = item.get("name", item.get("aegis_name", ""))
    return _strip_slot_suffix(name) in _FORGEABLE_WEAPON_NAMES

# slot → item type + valid EQP locs (mirrors equipment_browser logic)
_SLOT_TYPE: dict[str, str] = {
    "right_hand": "IT_WEAPON",
    "left_hand":  "IT_ARMOR",
    "ammo":       "IT_AMMO",
    "armor":      "IT_ARMOR",
    "garment":    "IT_ARMOR",
    "footwear":   "IT_ARMOR",
    "acc_l":      "IT_ARMOR",
    "acc_r":      "IT_ARMOR",
    "head_top":   "IT_ARMOR",
    "head_mid":   "IT_ARMOR",
    "head_low":   "IT_ARMOR",
}

_SLOT_LOC: dict[str, set[str]] = {
    "right_hand": {"EQP_WEAPON", "EQP_ARMS"},
    "left_hand":  {"EQP_SHIELD"},
    "ammo":       {"EQP_AMMO"},
    "armor":      {"EQP_ARMOR"},
    "garment":    {"EQP_GARMENT"},
    "footwear":   {"EQP_SHOES"},
    "acc_l":      {"EQP_ACC"},
    "acc_r":      {"EQP_ACC"},
    "head_top":   {"EQP_HEAD_TOP"},
    "head_mid":   {"EQP_HEAD_MID"},
    "head_low":   {"EQP_HEAD_LOW"},
}


# ── Grouping helpers ────────────────────────────────────────────────────────

def _group_by_weapon_type(items: list[tuple[str, int]]) -> list[tuple[str, int | None]]:
    """Group (name, id) pairs by weapon_type, inserting None-id separator rows."""
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, item_id in items:
        item = loader.get_item(item_id)
        wtype = (item.get("weapon_type") or "Other") if item else "Other"
        groups[wtype].append((name, item_id))
    result: list[tuple[str, int | None]] = []
    for wtype in sorted(groups):
        result.append((f"── {wtype} ──", None))
        result.extend(groups[wtype])
    return result


def _group_left_hand(items: list[tuple[str, int]]) -> list[tuple[str, int | None]]:
    """Split shields and 1H weapons into separate groups with separators.
    Shields come first; weapons are further grouped by weapon_type."""
    shields: list[tuple[str, int]] = []
    weapons_by_type: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, item_id in items:
        item = loader.get_item(item_id)
        if item and "EQP_WEAPON" in item.get("loc", []):
            wtype = item.get("weapon_type") or "Other"
            weapons_by_type[wtype].append((name, item_id))
        else:
            shields.append((name, item_id))
    result: list[tuple[str, int | None]] = []
    if shields:
        result.append(("── Shields ──", None))
        result.extend(shields)
    for wtype in sorted(weapons_by_type):
        result.append((f"── {wtype} ──", None))
        result.extend(weapons_by_type[wtype])
    return result


def _add_items_to_combo(combo: QComboBox, items: list[tuple[str, int | None]]) -> None:
    """Add items to combo, making None-id entries non-selectable separator rows."""
    for name, item_id in items:
        if item_id is None:
            combo.addItem(name, "__sep__")
            model_item = combo.model().item(combo.count() - 1)
            model_item.setFlags(Qt.ItemFlag.NoItemFlags)
        else:
            combo.addItem(name, item_id)


def _load_slot_items(
    slot_key: str,
    job_id: Optional[int] = None,
) -> list[tuple[str, int | None]]:
    """Return [(display_name, item_id), ...] for the inline combo.

    - item_id=None means a non-selectable separator/group header row.
    - Hidden items (loader.is_item_hidden) are excluded; a stale selection
      is re-inserted as a fallback by the combo repopulation caller.
    - Weapons (right_hand) are grouped by weapon_type with separator rows.
    - Assassin left_hand groups shields first, then 1H weapons by type.
    - Slot-count-only duplicates are merged: 'Name [s1/s2]' keeping highest-slot ID.
    - job_id=None disables job filtering (used at widget construction time).
    """
    item_type = _SLOT_TYPE.get(slot_key)
    valid_locs = set(_SLOT_LOC.get(slot_key, set()))
    if item_type is None:
        return []
    # Assassin dual-wield: include 1H weapons in the left_hand combo
    if slot_key == "left_hand" and job_id in _DUAL_WIELD_JOBS:
        valid_locs |= {"EQP_WEAPON"}
        items = loader.get_items_by_type("IT_ARMOR") + loader.get_items_by_type("IT_WEAPON")
    else:
        items = loader.get_items_by_type(item_type)
    filtered = [
        it for it in items
        if any(loc in valid_locs for loc in it.get("loc", []))
        and (job_id is None or not it.get("job") or job_id in it.get("job", []))
        and not loader.is_item_hidden(it["id"])
    ]
    filtered.sort(key=lambda it: it.get("name", it.get("aegis_name", "")))

    # Group by (stripped base name, stat key) to find slot-count-only duplicates
    groups: dict[tuple, list] = defaultdict(list)
    for it in filtered:
        raw_name = it.get("name", it.get("aegis_name", f"ID {it['id']}"))
        base = _strip_slot_suffix(raw_name)
        groups[(base, _item_stat_key(it))].append(it)

    flat: list[tuple[str, int]] = []
    for (base_name, _), group in groups.items():
        if len(group) == 1:
            it = group[0]
            raw_name = it.get("name", it.get("aegis_name", f"ID {it['id']}"))
            flat.append((raw_name, it["id"]))
        else:
            best = max(group, key=lambda x: x.get("slots", 0))
            slot_variants = sorted({x.get("slots", 0) for x in group})
            slots_str = "/".join(str(s) for s in slot_variants)
            flat.append((f"{base_name} [{slots_str}]", best["id"]))

    flat.sort(key=lambda x: x[0])

    # Apply grouping for weapon-bearing slots
    if slot_key == "right_hand":
        return _group_by_weapon_type(flat)
    if slot_key == "left_hand" and job_id in _DUAL_WIELD_JOBS:
        return _group_left_hand(flat)
    return flat  # list[tuple[str, int]] is compatible with list[tuple[str, int | None]]


def _resolve_item_name(item_id: Optional[int]) -> str:
    """Return display name for a slot item ID. Falls back gracefully."""
    if item_id is None:
        return "— Empty —"
    item = loader.get_item(item_id)
    if item is None:
        return f"Unknown (ID {item_id})"
    return item.get("name", item.get("aegis_name", f"ID {item_id}"))


def _resolve_card_label(card_id: Optional[int]) -> str:
    """Return short label for a card button (truncated name or dash)."""
    if card_id is None:
        return "—"
    item = loader.get_item(card_id)
    if item is None:
        return f"#{card_id}"
    name = item.get("name", item.get("aegis_name", f"#{card_id}"))
    # Strip trailing " Card" suffix — button width handles the rest
    if name.endswith(" Card"):
        name = name[:-5]
    return name


def _resolve_card_tooltip(card_id: Optional[int]) -> str:
    """Return description tooltip text for a card slot button."""
    if card_id is None:
        return ""
    desc = loader.get_item_description(card_id)
    if desc and desc.get("description"):
        return desc["description"]
    return ""


class EquipmentSection(Section):
    """Equipment slots with item name, refine spinners, and Edit button."""

    equipment_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._compact_widget: QWidget | None = None
        self._compact_weapon_lbl: QLabel | None = None
        self._compact_summary_lbl: QLabel | None = None

        # Per-slot widget storage (keyed by slot_key)
        self._item_ids:      dict[str, Optional[int]] = {s: None for s, *_ in _SLOTS}
        self._inline_combos: dict[str, QComboBox]     = {}  # quick-select combos
        self._refine_spins:  dict[str, QSpinBox]      = {}
        self._edit_btns:     dict[str, QPushButton]   = {}
        self._current_job_id: int = 0

        # card sub-slot storage — list of card item IDs per slot (length = item's slots count)
        self._card_ids:  dict[str, list[Optional[int]]] = {s: [] for s, *_ in _SLOTS}
        self._card_btns: dict[str, list[QPushButton]]   = {s: [] for s, *_ in _SLOTS}
        # Container widgets for name+card area (col 1 of grid)
        self._name_containers: dict[str, QWidget] = {}
        self._card_rows:       dict[str, QWidget] = {}
        # Forge controls — per-slot dicts (right_hand + left_hand)
        self._forge_toggles:        dict[str, QCheckBox] = {}
        self._forge_controls_rows:  dict[str, QWidget]   = {}
        self._forge_sc_spins:       dict[str, QSpinBox]   = {}
        self._forge_ranked_chks:    dict[str, QCheckBox] = {}
        self._forge_element_combos: dict[str, QComboBox]  = {}

        # ── Slot grid ──────────────────────────────────────────────────────
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)

        for row_i, (slot_key, slot_label, has_refine) in enumerate(_SLOTS):
            slot_lbl = QLabel(slot_label)
            slot_lbl.setObjectName("equip_slot_label")
            slot_lbl.setFixedWidth(68)
            grid.addWidget(slot_lbl, row_i, 0)

            # Col 1: container with item name on top, card row below
            name_container = QWidget()
            name_col_layout = QVBoxLayout(name_container)
            name_col_layout.setContentsMargins(0, 0, 0, 0)
            name_col_layout.setSpacing(2)

            # inline quick-select combo (replaces static name label)
            combo = NoScrollCombo()
            combo.setObjectName("equip_inline_combo")
            combo.addItem("— Empty —", None)
            _add_items_to_combo(combo, _load_slot_items(slot_key))  # no job filter at construction
            combo.currentIndexChanged.connect(
                lambda _sig, k=slot_key: self._on_inline_changed(k)
            )
            self._inline_combos[slot_key] = combo
            name_col_layout.addWidget(combo)

            # Forge toggle + controls (right_hand and left_hand weapon slots)
            if slot_key in ("right_hand", "left_hand"):
                forge_toggle = QCheckBox("Forged")
                forge_toggle.setObjectName("forge_toggle_chk")
                forge_toggle.setVisible(False)  # shown only for forgeable weapons
                forge_toggle.toggled.connect(
                    lambda checked, k=slot_key: self._on_forge_toggled(k, checked)
                )
                name_col_layout.addWidget(forge_toggle)
                self._forge_toggles[slot_key] = forge_toggle

                forge_ctrl = QWidget()
                forge_layout = QHBoxLayout(forge_ctrl)
                forge_layout.setContentsMargins(0, 0, 0, 0)
                forge_layout.setSpacing(4)

                forge_layout.addWidget(QLabel("Crumbs:"))
                sc_spin = NoWheelSpin()
                sc_spin.setRange(0, 3)
                sc_spin.setFixedWidth(58)
                sc_spin.valueChanged.connect(self.equipment_changed)
                forge_layout.addWidget(sc_spin)
                self._forge_sc_spins[slot_key] = sc_spin

                ranked_chk = QCheckBox("Ranked")
                ranked_chk.toggled.connect(self.equipment_changed)
                forge_layout.addWidget(ranked_chk)
                self._forge_ranked_chks[slot_key] = ranked_chk

                forge_layout.addWidget(QLabel("Ele:"))
                ele_combo = NoScrollCombo()
                for ele_idx, ele_name in enumerate(_ELEMENT_NAMES):
                    ele_combo.addItem(ele_name, ele_idx)
                ele_combo.currentIndexChanged.connect(self.equipment_changed)
                forge_layout.addWidget(ele_combo)
                self._forge_element_combos[slot_key] = ele_combo

                forge_layout.addStretch()
                forge_ctrl.setVisible(False)
                name_col_layout.addWidget(forge_ctrl)
                self._forge_controls_rows[slot_key] = forge_ctrl

            card_row = QWidget()
            card_row_layout = QHBoxLayout(card_row)
            card_row_layout.setContentsMargins(0, 0, 0, 0)
            card_row_layout.setSpacing(3)
            card_row.setVisible(False)
            self._card_rows[slot_key] = card_row
            self._name_containers[slot_key] = name_container
            name_col_layout.addWidget(card_row)

            grid.addWidget(name_container, row_i, 1)

            if has_refine:
                refine_spin = NoWheelSpin()
                refine_spin.setRange(0, 10)
                refine_spin.setValue(0)
                refine_spin.setFixedWidth(58)
                refine_spin.setPrefix("+")
                refine_spin.valueChanged.connect(self.equipment_changed)
                self._refine_spins[slot_key] = refine_spin
                grid.addWidget(refine_spin, row_i, 2)
            else:
                placeholder = QLabel("")
                grid.addWidget(placeholder, row_i, 2)

            # Col 3: Edit button above, Configure Cards below (shown only when item has slots)
            right_col = QWidget()
            right_col_layout = QVBoxLayout(right_col)
            right_col_layout.setContentsMargins(0, 0, 0, 0)
            right_col_layout.setSpacing(2)
            right_col_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("equip_edit_btn")
            edit_btn.setFixedWidth(42)
            self._edit_btns[slot_key] = edit_btn
            edit_btn.clicked.connect(
                lambda checked=False, k=slot_key: self._open_browser(k)
            )
            right_col_layout.addWidget(edit_btn)

            grid.addWidget(right_col, row_i, 3)

        self.add_content_widget(grid_widget)

        # ── Element overrides (weapon + armor, side by side) ──────────────
        ele_override_row = QWidget()
        ele_layout = QHBoxLayout(ele_override_row)
        ele_layout.setContentsMargins(0, 4, 0, 0)
        ele_layout.setSpacing(6)

        ele_layout.addWidget(QLabel("Weapon Element Override:"))
        self._element_combo = NoScrollCombo()
        self._element_combo.addItem("From Item", None)
        for idx, name in enumerate(_ELEMENT_NAMES):
            self._element_combo.addItem(name, idx)
        self._element_combo.currentIndexChanged.connect(self.equipment_changed)
        ele_layout.addWidget(self._element_combo)

        ele_layout.addSpacing(12)

        ele_layout.addWidget(QLabel("Armor Element Override:"))
        self._armor_element_combo = NoScrollCombo()
        for idx, name in enumerate(_ELEMENT_NAMES):
            self._armor_element_combo.addItem(name, idx)
        self._armor_element_combo.currentIndexChanged.connect(self.equipment_changed)
        ele_layout.addWidget(self._armor_element_combo)

        ele_layout.addStretch()
        self.add_content_widget(ele_override_row)

    # ── Forge helpers ───────────────────────────────────────────────────────

    def _on_forge_toggled(self, slot_key: str, checked: bool) -> None:
        """Show forge controls and hide card row (or vice versa) for the given slot."""
        ctrl = self._forge_controls_rows.get(slot_key)
        if ctrl is not None:
            ctrl.setVisible(checked)
        card_row = self._card_rows.get(slot_key)
        if card_row is not None:
            if checked:
                card_row.setVisible(False)
            else:
                self._refresh_card_slots(slot_key)
        self.equipment_changed.emit()

    def _update_refine_state(self, slot_key: str) -> None:
        """Grey out the refine spinner when the equipped item has refineable=False.
        Value is intentionally preserved so swapping back to a refineable item
        restores the previous refine level without user intervention."""
        spin = self._refine_spins.get(slot_key)
        if spin is None:
            return
        item_id = self._item_ids.get(slot_key)
        if item_id is None:
            spin.setEnabled(True)
            return
        item = loader.get_item(item_id)
        spin.setEnabled(item.get("refineable", True) if item else True)

    def _update_forge_toggle_visibility(self, slot_key: str) -> None:
        """Show the forge toggle only when the equipped item is a forgeable weapon."""
        toggle = self._forge_toggles.get(slot_key)
        if toggle is None:
            return
        item_id = self._item_ids.get(slot_key)
        forgeable = False
        if item_id is not None:
            item = loader.get_item(item_id)
            if item is not None:
                forgeable = _is_forgeable_weapon(item)
        if forgeable:
            toggle.setVisible(True)
        else:
            toggle.blockSignals(True)
            toggle.setChecked(False)
            toggle.blockSignals(False)
            toggle.setVisible(False)
            ctrl = self._forge_controls_rows.get(slot_key)
            if ctrl is not None:
                ctrl.setVisible(False)

    # ── Card slot helpers ───────────────────────────────────────────────────

    def _refresh_card_slots(self, slot_key: str) -> None:
        """Rebuild card sub-slot buttons for slot_key based on equipped item's slots count.
        Each card button directly opens the card browser for its slot (G96).
        A 'Configure Cards' button at the row end opens the multi-slot CardConfigDialog.
        """
        card_row = self._card_rows[slot_key]
        layout = card_row.layout()

        # suppress card display when forge is active for this slot
        toggle = self._forge_toggles.get(slot_key)
        if toggle is not None and toggle.isChecked():
            card_row.setVisible(False)
            return

        # Remove existing card buttons
        for btn in self._card_btns[slot_key]:
            layout.removeWidget(btn)
            btn.deleteLater()
        self._card_btns[slot_key] = []

        # Also remove the Configure Cards button from previous build if present
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        item_id = self._item_ids.get(slot_key)
        num_slots = 0
        if item_id is not None:
            item = loader.get_item(item_id)
            if item is not None:
                num_slots = item.get("slots", 0)

        # Resize card_ids list to match new slot count, preserving existing values
        old_ids = self._card_ids[slot_key]
        self._card_ids[slot_key] = [
            (old_ids[i] if i < len(old_ids) else None) for i in range(num_slots)
        ]

        if num_slots == 0:
            card_row.setVisible(False)
            return

        # Rebuild card slot buttons — each opens the browser directly for that slot (G96)
        for i in range(num_slots):
            card_id = self._card_ids[slot_key][i]
            label = _resolve_card_label(card_id)
            btn = QPushButton(label)
            btn.setObjectName("card_slot_btn")
            btn.setToolTip(_resolve_card_tooltip(card_id))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(
                lambda checked=False, k=slot_key, idx=i: self._open_card_for_slot(k, idx)
            )
            layout.addWidget(btn)
            self._card_btns[slot_key].append(btn)

        # Configure Cards button — opens multi-slot CardConfigDialog for all slots at once
        cfg_btn = QPushButton("Configure Cards")
        cfg_btn.setObjectName("configure_cards_btn")
        cfg_btn.setToolTip("Edit all card slots for this item at once")
        cfg_btn.clicked.connect(
            lambda checked=False, k=slot_key: self._open_card_config(k)
        )
        layout.addWidget(cfg_btn)

        card_row.setVisible(True)

    # ── Inline combo ────────────────────────────────────────────────────────

    def _repopulate_combo(self, slot_key: str) -> None:
        """Rebuild combo items filtered for current job, preserving selection if still valid."""
        combo = self._inline_combos.get(slot_key)
        if combo is None:
            return
        current_id = combo.currentData()
        if isinstance(current_id, str):  # was on a separator — treat as None
            current_id = None
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— Empty —", None)
        _add_items_to_combo(combo, _load_slot_items(slot_key, self._current_job_id))
        idx = combo.findData(current_id)
        if idx < 0 and current_id is not None:
            combo.addItem(_resolve_item_name(current_id), current_id)
            idx = combo.count() - 1
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    def _on_inline_changed(self, slot_key: str) -> None:
        """Handle quick-select combo change (G39)."""
        combo = self._inline_combos.get(slot_key)
        if combo is None:
            return
        new_id = combo.currentData()
        if isinstance(new_id, str):  # separator row — ignore (non-selectable but guard anyway)
            return
        self._item_ids[slot_key] = new_id
        if new_id is None and slot_key in self._refine_spins:
            self._refine_spins[slot_key].setValue(0)
        self._update_refine_state(slot_key)
        if slot_key in ("right_hand", "left_hand"):
            self._update_forge_toggle_visibility(slot_key)
        self._refresh_card_slots(slot_key)
        if slot_key == "right_hand":
            self._update_left_hand_state()
        if self._compact_widget is not None:
            self._update_compact_labels()
        self.equipment_changed.emit()

    def _open_card_for_slot(self, slot_key: str, slot_index: int) -> None:
        """Open card browser directly for a single card slot (G96)."""
        from gui.dialogs.equipment_browser import EquipmentBrowserDialog

        item_id = self._item_ids.get(slot_key)
        card_ids = self._card_ids.get(slot_key, [])
        if slot_index >= len(card_ids):
            return

        # left_hand weapon (dual-wield) needs weapon-card EQP filter
        card_eqp = None
        if slot_key == "left_hand" and item_id is not None:
            lh_item = loader.get_item(item_id)
            if lh_item and "EQP_WEAPON" in lh_item.get("loc", []):
                card_eqp = {"EQP_WEAPON"}

        current = card_ids[slot_index]
        dlg = EquipmentBrowserDialog(
            slot_key, current,
            job_id=self._current_job_id,
            item_type_override="IT_CARD",
            eqp_override=card_eqp,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_id = dlg.selected_item_id()
            self._card_ids[slot_key][slot_index] = new_id
            btns = self._card_btns.get(slot_key, [])
            if slot_index < len(btns):
                btns[slot_index].setText(_resolve_card_label(new_id))
                btns[slot_index].setToolTip(_resolve_card_tooltip(new_id))
            self.equipment_changed.emit()

    def _open_card_config(self, slot_key: str) -> None:
        """Open the multi-slot card configuration dialog for the item in slot_key."""
        from gui.dialogs.card_config_dialog import CardConfigDialog

        item_id   = self._item_ids.get(slot_key)
        num_slots = len(self._card_ids[slot_key])
        if num_slots == 0:
            return

        dlg = CardConfigDialog(
            slot_key,
            item_id,
            num_slots,
            list(self._card_ids[slot_key]),
            job_id=self._current_job_id,
            parent=self,
        )

        # left_hand weapon (dual-wield) needs weapon-card EQP filter
        if slot_key == "left_hand" and item_id is not None:
            lh_item = loader.get_item(item_id)
            if lh_item is not None and "EQP_WEAPON" in lh_item.get("loc", []):
                dlg.set_eqp_override({"EQP_WEAPON"})

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_ids = dlg.result_card_ids()
            self._card_ids[slot_key] = new_ids
            # Refresh button labels and tooltips to reflect new card selections
            for i, btn in enumerate(self._card_btns[slot_key]):
                cid = new_ids[i] if i < len(new_ids) else None
                btn.setText(_resolve_card_label(cid))
                btn.setToolTip(_resolve_card_tooltip(cid))
            self.equipment_changed.emit()

    # ── Browser ────────────────────────────────────────────────────────────

    def _open_browser(self, slot_key: str) -> None:
        from gui.dialogs.equipment_browser import EquipmentBrowserDialog
        dlg = EquipmentBrowserDialog(
            slot_key, self._item_ids.get(slot_key),
            job_id=self._current_job_id, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_id = dlg.selected_item_id()
            self._item_ids[slot_key] = new_id
            combo = self._inline_combos.get(slot_key)
            if combo is not None:
                combo.blockSignals(True)
                idx = combo.findData(new_id)
                if idx < 0 and new_id is not None:
                    combo.addItem(_resolve_item_name(new_id), new_id)
                    idx = combo.count() - 1
                combo.setCurrentIndex(max(0, idx))
                combo.blockSignals(False)
            if new_id is None and slot_key in self._refine_spins:
                self._refine_spins[slot_key].setValue(0)
            if slot_key in ("right_hand", "left_hand"):
                self._update_forge_toggle_visibility(slot_key)
            self._refresh_card_slots(slot_key)
            if slot_key == "right_hand":
                self._update_left_hand_state()
            if self._compact_widget is not None:
                self._update_compact_labels()
            self.equipment_changed.emit()

    def _is_right_hand_two_handed(self) -> bool:
        rh_id = self._item_ids.get("right_hand")
        if rh_id is None:
            return False
        item = loader.get_item(rh_id)
        if item is None:
            return False
        return item.get("weapon_type", "") in _TWO_HANDED_WEAPON_TYPES

    def _update_left_hand_state(self) -> None:
        """Enable or disable the left_hand slot (F5: blocked by 2H right-hand weapon)."""
        is_2h = self._is_right_hand_two_handed()
        enabled = not is_2h

        edit_btn = self._edit_btns.get("left_hand")
        if edit_btn:
            edit_btn.setEnabled(enabled)

        combo_lh = self._inline_combos.get("left_hand")
        if combo_lh is not None:
            combo_lh.setEnabled(enabled)
            combo_lh.setItemText(0, "— Empty —" if enabled else "— Blocked (2H) —")

        # Hide LH forge controls when slot is blocked; re-check forgeability when unblocked
        if enabled:
            self._update_forge_toggle_visibility("left_hand")
        else:
            lh_forge_toggle = self._forge_toggles.get("left_hand")
            if lh_forge_toggle is not None:
                lh_forge_toggle.setVisible(False)
        lh_forge_ctrl = self._forge_controls_rows.get("left_hand")
        if lh_forge_ctrl is not None and not enabled:
            lh_forge_ctrl.setVisible(False)

        if not enabled:
            # Clear the slot when blocked by a 2H weapon
            self._item_ids["left_hand"] = None
            if combo_lh is not None:
                combo_lh.blockSignals(True)
                combo_lh.setCurrentIndex(0)
                combo_lh.blockSignals(False)
            if "left_hand" in self._refine_spins:
                self._refine_spins["left_hand"].setValue(0)

    # ── Compact API ────────────────────────────────────────────────────────

    def _build_compact_widget(self) -> None:
        w = QWidget()
        inner = QGridLayout(w)
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(3)

        self._compact_weapon_lbl = QLabel("— Empty —")
        self._compact_weapon_lbl.setObjectName("compact_equip_weapon")
        inner.addWidget(self._compact_weapon_lbl, 0, 0)

        self._compact_summary_lbl = QLabel("0/11 slots filled")
        self._compact_summary_lbl.setObjectName("compact_equip_summary")
        inner.addWidget(self._compact_summary_lbl, 1, 0)

        w.setVisible(False)
        self._compact_widget = w
        self.layout().addWidget(w)

    def _update_compact_labels(self) -> None:
        if self._compact_weapon_lbl is None:
            return
        rh_id = self._item_ids.get("right_hand")
        rh_name = _resolve_item_name(rh_id)
        rh_refine_spin = self._refine_spins.get("right_hand")
        if rh_refine_spin and rh_refine_spin.value() > 0:
            weapon_text = f"{rh_name} +{rh_refine_spin.value()}"
        else:
            weapon_text = rh_name
        self._compact_weapon_lbl.setText(weapon_text)

        filled = sum(1 for v in self._item_ids.values() if v is not None)
        self._compact_summary_lbl.setText(f"{filled}/{len(_SLOTS)} slots filled")  # type: ignore[union-attr]

    def _enter_slim(self) -> None:
        if self._compact_widget is None:
            self._build_compact_widget()
        self._update_compact_labels()
        self._compact_widget.setVisible(True)

    def _exit_slim(self) -> None:
        if self._compact_widget is not None:
            self._compact_widget.setVisible(False)

    # ── Public API ────────────────────────────────────────────────────────

    def update_for_job(self, job_id: int) -> None:
        """Repopulate inline combos filtered for the new job (G39)."""
        self._current_job_id = job_id
        for slot_key in list(self._inline_combos):
            self._repopulate_combo(slot_key)

    def load_build(self, build: PlayerBuild) -> None:
        """Populate all equipment widgets from build without emitting change signals."""
        for spin in self._refine_spins.values():
            spin.blockSignals(True)
        self._element_combo.blockSignals(True)

        self._current_job_id = build.job_id

        # restore forge state BEFORE the slot loop so _refresh_card_slots
        # already sees the correct toggle state when it runs for each slot.
        _forge_state = {
            "right_hand": (build.is_forged,    build.forge_sc_count,    build.forge_ranked,    build.forge_element),
            "left_hand":  (build.lh_is_forged, build.lh_forge_sc_count, build.lh_forge_ranked, build.lh_forge_element),
        }
        for fslot, (is_forged, sc_count, ranked, ele) in _forge_state.items():
            toggle = self._forge_toggles.get(fslot)
            if toggle is not None:
                toggle.blockSignals(True)
                toggle.setChecked(is_forged)
                toggle.blockSignals(False)
            ctrl = self._forge_controls_rows.get(fslot)
            if ctrl is not None:
                ctrl.setVisible(is_forged)
            sc_spin = self._forge_sc_spins.get(fslot)
            if sc_spin is not None:
                sc_spin.blockSignals(True)
                sc_spin.setValue(sc_count)
                sc_spin.blockSignals(False)
            ranked_chk = self._forge_ranked_chks.get(fslot)
            if ranked_chk is not None:
                ranked_chk.blockSignals(True)
                ranked_chk.setChecked(ranked)
                ranked_chk.blockSignals(False)
            ele_combo = self._forge_element_combos.get(fslot)
            if ele_combo is not None:
                ele_combo.blockSignals(True)
                fe_idx = ele_combo.findData(ele)
                ele_combo.setCurrentIndex(fe_idx if fe_idx >= 0 else 0)
                ele_combo.blockSignals(False)

        # Repopulate inline combos for the loaded job before restoring selections
        for slot_key in list(self._inline_combos):
            c = self._inline_combos[slot_key]
            c.blockSignals(True)
            c.clear()
            c.addItem("— Empty —", None)
            _add_items_to_combo(c, _load_slot_items(slot_key, build.job_id))
            c.blockSignals(False)

        for slot_key, _, has_refine in _SLOTS:
            item_id = build.equipped.get(slot_key)
            self._item_ids[slot_key] = item_id
            combo = self._inline_combos.get(slot_key)
            if combo is not None:
                combo.blockSignals(True)
                idx = combo.findData(item_id)
                if idx < 0 and item_id is not None:
                    combo.addItem(_resolve_item_name(item_id), item_id)
                    idx = combo.count() - 1
                combo.setCurrentIndex(max(0, idx))
                combo.blockSignals(False)

            if has_refine and slot_key in self._refine_spins:
                self._refine_spins[slot_key].setValue(
                    build.refine_levels.get(slot_key, 0)
                )
            self._update_refine_state(slot_key)

            # restore card IDs from build.equipped before refreshing buttons
            item = loader.get_item(item_id) if item_id is not None else None
            num_slots = item.get("slots", 0) if item is not None else 0
            self._card_ids[slot_key] = [
                build.equipped.get(f"{slot_key}_card_{i}")
                for i in range(num_slots)
            ]
            if slot_key in ("right_hand", "left_hand"):
                self._update_forge_toggle_visibility(slot_key)
            self._refresh_card_slots(slot_key)

        # Weapon element combo: None → "From Item" (index 0), else match by data
        we = build.weapon_element
        if we is None:
            self._element_combo.setCurrentIndex(0)
        else:
            idx = self._element_combo.findData(we)
            self._element_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Armor element combo: int 0-9, default 0 (Neutral)
        self._armor_element_combo.blockSignals(True)
        ae_idx = self._armor_element_combo.findData(build.armor_element)
        self._armor_element_combo.setCurrentIndex(ae_idx if ae_idx >= 0 else 0)
        self._armor_element_combo.blockSignals(False)

        for spin in self._refine_spins.values():
            spin.blockSignals(False)
        self._element_combo.blockSignals(False)

        # Apply F5 state without emitting signals (2H right-hand blocks left hand)
        is_2h = self._is_right_hand_two_handed()
        edit_btn = self._edit_btns.get("left_hand")
        combo_lh = self._inline_combos.get("left_hand")
        if edit_btn:
            edit_btn.setEnabled(not is_2h)
        if combo_lh:
            combo_lh.setEnabled(not is_2h)

        if self._compact_widget is not None:
            self._update_compact_labels()

    def collect_into(self, build: PlayerBuild) -> None:
        """Write section state into an existing PlayerBuild in-place."""
        # Base slot keys first (order matters for acc_l/acc_r round-trip stability)
        equipped: dict[str, Optional[int]] = {slot_key: self._item_ids[slot_key] for slot_key, *_ in _SLOTS}
        # append card keys in slot order: {slot}_card_0 … {slot}_card_{N-1}
        for slot_key, *_ in _SLOTS:
            for i, card_id in enumerate(self._card_ids.get(slot_key, [])):
                equipped[f"{slot_key}_card_{i}"] = card_id
        build.equipped = equipped
        build.refine_levels = {
            slot_key: self._refine_spins[slot_key].value()
            for slot_key, _, has_refine in _SLOTS
            if has_refine and slot_key in self._refine_spins
        }
        build.weapon_element = self._element_combo.currentData()  # None or int 0-9
        build.armor_element = self._armor_element_combo.currentData() or 0  # int 0-9
        # forge state — right_hand and left_hand
        def _get_forge(slot: str) -> tuple[bool, int, bool, int]:
            toggle  = self._forge_toggles.get(slot)
            sc_spin = self._forge_sc_spins.get(slot)
            ranked  = self._forge_ranked_chks.get(slot)
            ele     = self._forge_element_combos.get(slot)
            return (
                toggle.isChecked() if toggle is not None else False,
                sc_spin.value()    if sc_spin is not None else 0,
                ranked.isChecked() if ranked is not None else False,
                (ele.currentData() or 0) if ele is not None else 0,
            )
        build.is_forged,    build.forge_sc_count,    build.forge_ranked,    build.forge_element    = _get_forge("right_hand")
        build.lh_is_forged, build.lh_forge_sc_count, build.lh_forge_ranked, build.lh_forge_element = _get_forge("left_hand")
