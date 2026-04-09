"""
player_target_browser — PlayerTargetBrowserDialog.

Filterable table of saved player builds for use as PvP targets. Reads build JSON
files from the saves directory and displays name, job, level, HP, DEF, and MDEF.
Returns the selected build stem (filename without .json), or None if cancelled.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_COLUMNS = ["Name", "Job", "Lv", "HP", "DEF", "MDEF"]
_NUMERIC_COLS = {2, 3, 4, 5}  # Lv, HP, DEF, MDEF


class _NumericItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return int(self.text()) < int(other.text())
        except ValueError:
            return super().__lt__(other)


class PlayerTargetBrowserDialog(QDialog):
    """Select a saved player build as the PvP target. Returns the build stem or None."""

    def __init__(self, saves_dir: str, current_stem: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Player Target")
        self.setMinimumSize(560, 420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._result: Optional[str] = current_stem
        self._rows: list[tuple[str, str, str, str, str, str, str]] = []  # (stem, name, job, lv, hp, def_, mdef)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Build name…")
        search_row.addWidget(self._search, stretch=1)
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, stretch=1)

        btn_box = QDialogButtonBox()
        self._ok_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Ok)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._ok_btn.setEnabled(False)
        layout.addWidget(btn_box)

        self._search.textChanged.connect(self._on_filter)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(lambda r, c: self._accept_selected())
        self._ok_btn.clicked.connect(self._accept_selected)
        btn_box.rejected.connect(self.reject)

        self._load_builds(saves_dir)
        self._populate(self._rows)

        if current_stem is not None:
            self._select_stem(current_stem)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _load_builds(self, saves_dir: str) -> None:
        if not os.path.isdir(saves_dir):
            return
        for fname in sorted(os.listdir(saves_dir)):
            if not fname.endswith(".json"):
                continue
            stem = fname[:-5]
            path = os.path.join(saves_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            cd = data.get("cached_display", {})
            name = data.get("name", stem) or stem
            job_name = cd.get("job_name", "?")
            level = str(data.get("base_level", "?"))
            hp = str(cd.get("hp", "?"))
            def_ = str(cd.get("def_", "?"))
            mdef = str(cd.get("mdef", "?"))
            self._rows.append((stem, name, job_name, level, hp, def_, mdef))

    def _make_item(self, text: str, numeric: bool = False) -> QTableWidgetItem:
        item = _NumericItem(text) if numeric else QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        return item

    def _populate(self, rows: list) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row, (stem, name, job_name, level, hp, def_, mdef) in enumerate(rows):
            name_item = self._make_item(name)
            name_item.setData(Qt.ItemDataRole.UserRole, stem)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, self._make_item(job_name))
            self._table.setItem(row, 2, self._make_item(level, numeric=True))
            self._table.setItem(row, 3, self._make_item(hp,    numeric=True))
            self._table.setItem(row, 4, self._make_item(def_,  numeric=True))
            self._table.setItem(row, 5, self._make_item(mdef,  numeric=True))
        self._table.resizeColumnsToContents()
        self._table.setSortingEnabled(True)

    def _select_stem(self, stem: str) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == stem:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                break

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_filter(self, text: str) -> None:
        query = text.strip().lower()
        filtered = self._rows if not query else [
            r for r in self._rows if query in r[1].lower()  # r[1] = display name
        ]
        self._populate(filtered)

    def _on_selection_changed(self) -> None:
        self._ok_btn.setEnabled(bool(self._table.selectedItems()))

    def _accept_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        item = self._table.item(rows[0].row(), 0)
        self._result = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    # ── Public API ─────────────────────────────────────────────────────────

    def selected_build_stem(self) -> Optional[str]:
        return self._result
