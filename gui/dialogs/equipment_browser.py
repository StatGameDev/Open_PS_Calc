"""
EquipmentBrowserDialog — filterable item/card picker for a single equipment slot.

Module-level constants define per-slot item types (_SLOT_ITEM_TYPE), valid equip
locations (_SLOT_EQP), display labels (_SLOT_LABELS), and visible columns (_SLOT_COLUMNS).
Items are sourced from DataLoader (core/data_loader.py).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from core.data_loader import loader

# Scraped VanillaData identification line present on every item — stripped from display.
_IDENTIFICATION_LINE = "Unknown Item, can be identified by using a Magnifier."

# IT_CARD items whose description DB entry lacks a "compound_on" value are
# mechanics/placeholder items (e.g. named stat cards used by the engine).
# Only show cards that have a compound_on entry in item_descriptions.json,
# OR are PS-custom cards (explicitly typed IT_CARD in ps_item_manual.json —
# those are real equippable cards even without a vanilla description entry).
def _has_compound_on(item_id: int) -> bool:
    desc = loader.get_item_description(item_id)
    if desc is not None and desc.get('compound_on') is not None:
        return True
    return loader._load_ps_item_manual().get(str(item_id), {}).get("type") == "IT_CARD"


# Which item_db type to pull for each equipment slot key.
_SLOT_ITEM_TYPE: dict[str, str] = {
    "right_hand": "IT_WEAPON",
    "left_hand":  "IT_ARMOR",   # shields are IT_ARMOR
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

# Items matching a slot must have any of these EQP tags in their loc list.
# EQP_WEAPON = 1H weapons; EQP_ARMS = 2H weapons (both go in right hand).
_SLOT_EQP: dict[str, set[str]] = {
    "right_hand": {"EQP_WEAPON", "EQP_ARMS"},
    "left_hand":  {"EQP_SHIELD"},  # base: shields only; Assassin gets 1H weapons added at runtime
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

_SLOT_LABELS: dict[str, str] = {
    "right_hand": "R. Hand",
    "left_hand":  "L. Hand",
    "ammo":       "Ammo",
    "armor":      "Armor",
    "garment":    "Garment",
    "footwear":   "Footwear",
    "acc_l":      "Acc. L",
    "acc_r":      "Acc. R",
    "head_top":   "Head Top",
    "head_mid":   "Head Mid",
    "head_low":   "Head Low",
}

# Column sets per slot — only the columns meaningful for that slot type.
_SLOT_COLUMNS: dict[str, list[str]] = {
    "right_hand": ["Name", "ATK", "Type", "Slots"],
    "left_hand":  ["Name", "ATK", "DEF", "Slots"],  # mixed shields + 1H weapons
    "ammo":       ["Name", "ATK", "Type"],
    "armor":      ["Name", "DEF", "Slots"],
    "garment":    ["Name", "DEF", "Slots"],
    "footwear":   ["Name", "DEF", "Slots"],
    "acc_l":      ["Name", "DEF", "Slots"],
    "acc_r":      ["Name", "DEF", "Slots"],
    "head_top":   ["Name", "DEF", "Slots"],
    "head_mid":   ["Name", "DEF", "Slots"],
    "head_low":   ["Name", "DEF", "Slots"],
}
_CARD_COLUMNS: list[str] = ["Name", "Effect"]
_DEFAULT_COLUMNS: list[str] = ["Name", "ATK", "DEF", "Type", "Slots"]


def _item_row(item: dict, columns: list[str]) -> list[str]:
    """Return display strings matching the given column list."""
    itype = item.get("type", "")
    values: dict[str, str] = {
        "Name":   item.get("name") or item.get("aegis_name", ""),
        "ATK":    str(item.get("atk", 0)) if itype in ("IT_WEAPON", "IT_AMMO") else "—",
        "DEF":    str(item.get("def", 0)) if itype == "IT_ARMOR" else "—",
        "Type":   (item.get("weapon_type", "") if itype == "IT_WEAPON"
                   else item.get("subtype", "").replace("A_", "")),
        "Slots":  str(item.get("slots", 0)),
        "Effect": "—",  # simplified: card effects shown only in the description pane, not in table columns
    }
    return [values.get(col, "") for col in columns]


class EquipmentBrowserDialog(QDialog):
    """
    Filterable item browser for a single equipment slot.
    Returns the selected item_id or None (slot cleared).
    """

    def __init__(
        self,
        slot_key: str,
        current_item_id: Optional[int] = None,
        job_id: int = 0,
        item_type_override: Optional[str] = None,
        eqp_override: Optional[set] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        slot_label = _SLOT_LABELS.get(slot_key, slot_key)
        if item_type_override == "IT_CARD":
            title_suffix = f"{slot_label} — Cards"
        else:
            title_suffix = slot_label
        self.setWindowTitle(f"Select Item — {title_suffix}")
        self.setMinimumSize(680, 600)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._result: Optional[int] = current_item_id
        self._job_id: int = job_id
        # Cards have no meaningful job restrictions — always show all.
        self._job_filter_applies: bool = item_type_override != "IT_CARD"

        # Determine column set for this slot/mode
        if item_type_override == "IT_CARD":
            self._columns = _CARD_COLUMNS
        else:
            self._columns = _SLOT_COLUMNS.get(slot_key, _DEFAULT_COLUMNS)

        # Load and filter items for this slot.
        item_type = item_type_override if item_type_override else _SLOT_ITEM_TYPE.get(slot_key, "IT_ARMOR")
        valid_eqp = eqp_override if eqp_override is not None else _SLOT_EQP.get(slot_key, set())
        all_items = loader.get_items_by_type(item_type)
        self._items: list = [
            it for it in all_items
            if set(it.get("loc", [])) & valid_eqp
        ]
        # Filter out mechanics/placeholder cards (no compound_on in description DB).
        # Pinned convenience cards are separated into _pinned_items and held out of
        # the regular sorted list so they always appear at the top of the card browser.
        if item_type_override == "IT_CARD":
            self._items = [it for it in self._items if _has_compound_on(it["id"])]
            self._pinned_items: list = [it for it in self._items if it.get("_pinned")]
            self._items = [it for it in self._items if not it.get("_pinned")]
        else:
            self._pinned_items = []

        # Assassin/Assassin Cross (job 12/4013) can also equip 1H weapons in left hand.
        # Merge in IT_WEAPON items with EQP_WEAPON (1H only — EQP_ARMS/2H excluded).
        # Not applicable when browsing cards.
        if slot_key == "left_hand" and job_id in (12, 4013) and not item_type_override:
            weapons_1h = [
                it for it in loader.get_items_by_type("IT_WEAPON")
                if "EQP_WEAPON" in it.get("loc", [])
            ]
            seen_ids = {it["id"] for it in self._items}
            self._items = self._items + [it for it in weapons_1h if it["id"] not in seen_ids]

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Item name…")
        search_row.addWidget(self._search, stretch=1)
        self._all_jobs_chk = QCheckBox("All Jobs")
        self._all_jobs_chk.setChecked(not self._job_filter_applies)
        self._all_jobs_chk.setVisible(self._job_filter_applies)
        search_row.addWidget(self._all_jobs_chk)
        self._show_hidden_chk = QCheckBox("Show Hidden Items")
        search_row.addWidget(self._show_hidden_chk)
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, stretch=1)

        # Description pane — starts at single-line height; grows via _fit_desc_box().
        self._desc_box = QTextEdit()
        self._desc_box.setReadOnly(True)
        self._desc_box.setObjectName("desc_box")
        self._desc_box.setFixedHeight(28)
        self._desc_box.setPlaceholderText("Select an item to see its description.")
        layout.addWidget(self._desc_box)

        btn_box = QDialogButtonBox()
        self._ok_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Ok)
        self._clear_btn = btn_box.addButton("Clear", QDialogButtonBox.ButtonRole.ResetRole)
        self._hide_btn = btn_box.addButton("Hide", QDialogButtonBox.ButtonRole.ActionRole)
        self._hide_btn.setEnabled(False)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._ok_btn.setEnabled(False)
        layout.addWidget(btn_box)

        self._search.textChanged.connect(self._apply_filters)
        self._all_jobs_chk.toggled.connect(self._apply_filters)
        self._show_hidden_chk.toggled.connect(self._apply_filters)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(lambda r, c: self._accept_selected())
        self._ok_btn.clicked.connect(self._accept_selected)
        self._clear_btn.clicked.connect(self._clear)
        self._hide_btn.clicked.connect(self._on_hide_clicked)
        btn_box.rejected.connect(self.reject)

        self._apply_filters()

        if current_item_id is not None:
            self._select_row(current_item_id)
            self._update_desc(current_item_id)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _make_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        return item

    def _populate(self, pinned: list, regular: list) -> None:
        regular_sorted = sorted(regular, key=lambda x: (x.get("name") or x.get("aegis_name", "")).lower())
        all_items = pinned + regular_sorted
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(all_items))
        for row, it in enumerate(all_items):
            row_data = _item_row(it, self._columns)
            name_item = self._make_item(row_data[0])
            name_item.setData(Qt.ItemDataRole.UserRole, it.get("id"))
            self._table.setItem(row, 0, name_item)
            for col, text in enumerate(row_data[1:], 1):
                self._table.setItem(row, col, self._make_item(text))
        self._table.resizeColumnsToContents()
        # Sorting left disabled — preserves pinned-first order.

    def _select_row(self, item_id: int) -> None:
        for row in range(self._table.rowCount()):
            cell = self._table.item(row, 0)
            if cell and cell.data(Qt.ItemDataRole.UserRole) == item_id:
                self._table.selectRow(row)
                self._table.scrollToItem(cell)
                break

    # ── Slots ──────────────────────────────────────────────────────────────

    def _apply_filters(self, *_) -> None:
        query = self._search.text().strip().lower()
        use_job_filter = (
            self._job_filter_applies
            and not self._all_jobs_chk.isChecked()
            and self._job_id != 0
        )
        show_hidden = self._show_hidden_chk.isChecked()
        filtered_regular = [
            it for it in self._items
            if (not query or query in (it.get("name") or it.get("aegis_name", "")).lower())
            and (not use_job_filter or not it.get("job") or self._job_id in it["job"])
            and (show_hidden or not loader.is_item_hidden(it["id"]))
        ]
        # Pinned cards: only name-filtered; always visible regardless of job/hidden filters.
        pinned_filtered = [
            it for it in self._pinned_items
            if not query or query in (it.get("name") or "").lower()
        ]
        self._populate(pinned_filtered, filtered_regular)

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        has_sel = bool(rows)
        self._ok_btn.setEnabled(has_sel)
        if has_sel:
            cell = self._table.item(rows[0].row(), 0)
            item_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
            self._update_desc(item_id)
            if item_id is not None:
                is_hidden = loader.is_item_hidden(item_id)
                self._hide_btn.setText("Unhide" if is_hidden else "Hide")
                self._hide_btn.setEnabled(True)
            else:
                self._hide_btn.setEnabled(False)
        else:
            self._desc_box.clear()
            self._hide_btn.setText("Hide")
            self._hide_btn.setEnabled(False)

    def _on_hide_clicked(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        cell = self._table.item(rows[0].row(), 0)
        item_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if item_id is None:
            return
        if loader.is_item_hidden(item_id):
            loader.unhide_item(item_id)
        else:
            loader.hide_item(item_id)
        self._apply_filters()

    def _fit_desc_box(self) -> None:
        """Resize desc_box to its document height and grow the dialog if needed."""
        doc = self._desc_box.document()
        w = self._desc_box.viewport().width()
        if w < 10:
            w = max(self.width() - 40, 200)
        doc.setTextWidth(w)
        h = int(doc.size().height()) + 6  # 6px for frame margins
        self._desc_box.setFixedHeight(max(h, 36))
        new_h = self.sizeHint().height()
        if new_h > self.height():
            self.resize(self.width(), new_h)

    def _update_desc(self, item_id: int | None) -> None:
        """Populate the description pane, stripping the VanillaData identification line."""
        if item_id is None:
            self._desc_box.clear()
            self._fit_desc_box()
            return
        desc_entry = loader.get_item_description(item_id)
        if desc_entry and desc_entry.get('description'):
            text = desc_entry['description'].replace(_IDENTIFICATION_LINE, "").strip()
            self._desc_box.setPlainText(text if text else "(No description available)")
        else:
            self._desc_box.setPlainText("(No description available)")
        self._fit_desc_box()

    def _accept_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        cell = self._table.item(rows[0].row(), 0)
        self._result = cell.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _clear(self) -> None:
        self._result = None
        self.accept()

    # ── Public API ─────────────────────────────────────────────────────────

    def selected_item_id(self) -> Optional[int]:
        return self._result
