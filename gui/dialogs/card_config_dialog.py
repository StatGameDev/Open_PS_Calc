"""
CardConfigDialog — edit all card slots for one equipment item in a single dialog.

Each slot has a row (slot label · card name · Browse · "-> all") followed
immediately by its own description box.  Descriptions start at single-line
height and grow to fit content when a card is selected.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.data_loader import loader

_DESC_SINGLE_LINE_H = 28  # initial height before content is loaded


class CardConfigDialog(QDialog):
    """
    Multi-slot card editor for a single equipment item.

    Parameters
    ----------
    slot_key  : equipment slot the item lives in (forwarded to card browser for EQP filter)
    item_id   : item_db ID of the equipped item (used for title)
    num_slots : number of card slots on the item
    card_ids  : current list of card item IDs (length == num_slots; None = empty slot)
    job_id    : current job ID (forwarded to card browser)
    """

    def __init__(
        self,
        slot_key: str,
        item_id: Optional[int],
        num_slots: int,
        card_ids: list[Optional[int]],
        job_id: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._slot_key      = slot_key
        self._job_id        = job_id
        self._num_slots     = num_slots
        self._eqp_override: Optional[set] = None
        # Defensive copy; pad / trim to num_slots
        self._card_ids: list[Optional[int]] = list(card_ids)[:num_slots]
        while len(self._card_ids) < num_slots:
            self._card_ids.append(None)

        item_name = "Unknown Item"
        if item_id is not None:
            item = loader.get_item(item_id)
            if item:
                item_name = item.get("name") or item.get("aegis_name", "Unknown Item")
        slot_word = "slot" if num_slots == 1 else "slots"
        self.setWindowTitle(f"Cards — {item_name}  ({num_slots} {slot_word})")
        self.setMinimumWidth(460)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # ── Layout ──────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setSpacing(4)

        self._name_labels: list[QLabel]    = []
        self._all_btns:    list[QPushButton] = []
        self._desc_boxes:  list[QTextEdit]  = []

        for i in range(num_slots):
            # Thin separator between slots (not before the first)
            if i > 0:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                root.addWidget(sep)

            # ── Slot row ────────────────────────────────────────────────────
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            slot_lbl = QLabel(f"Slot {i + 1}:")
            slot_lbl.setFixedWidth(48)
            slot_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(slot_lbl)

            clear_btn = QPushButton("Clear")
            clear_btn.clicked.connect(lambda checked=False, idx=i: self._clear_slot(idx))
            row_layout.addWidget(clear_btn)

            name_lbl = QLabel(self._card_label(i))
            name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            name_lbl.setObjectName("card_name_label")
            row_layout.addWidget(name_lbl, stretch=1)
            self._name_labels.append(name_lbl)

            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(lambda checked=False, idx=i: self._browse(idx))
            row_layout.addWidget(browse_btn)

            all_btn = QPushButton("-> all")
            all_btn.setToolTip("Copy this card to all slots")
            all_btn.clicked.connect(lambda checked=False, idx=i: self._copy_to_all(idx))
            row_layout.addWidget(all_btn)
            self._all_btns.append(all_btn)

            root.addWidget(row_widget)

            # ── Per-slot description box ─────────────────────────────────────
            desc_box = QTextEdit()
            desc_box.setReadOnly(True)
            desc_box.setObjectName("desc_box")
            desc_box.setFixedHeight(_DESC_SINGLE_LINE_H)
            root.addWidget(desc_box)
            self._desc_boxes.append(desc_box)

        self._update_all_btn_states()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

        for i in range(num_slots):
            self._show_desc(self._card_ids[i], i)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _card_label(self, slot_index: int) -> str:
        cid = self._card_ids[slot_index]
        if cid is None:
            return "—"
        item = loader.get_item(cid)
        if item is None:
            return f"#{cid}"
        name = item.get("name") or item.get("aegis_name", f"#{cid}")
        if name.endswith(" Card"):
            name = name[:-5]
        return name

    def _fit_desc_box(self, slot_index: int) -> None:
        """Resize the desc box for slot_index to its content height; grow dialog if needed."""
        box = self._desc_boxes[slot_index]
        doc = box.document()
        w = box.viewport().width()
        if w < 10:
            w = max(self.width() - 40, 200)
        doc.setTextWidth(w)
        h = int(doc.size().height()) + 6
        box.setFixedHeight(max(h, _DESC_SINGLE_LINE_H))
        new_h = self.sizeHint().height()
        if new_h > self.height():
            self.resize(self.width(), new_h)

    def _show_desc(self, card_id: Optional[int], slot_index: int) -> None:
        box = self._desc_boxes[slot_index]
        if card_id is None:
            box.clear()
        else:
            desc_entry = loader.get_item_description(card_id)
            if desc_entry and desc_entry.get('description'):
                box.setPlainText(desc_entry['description'])
            else:
                box.setPlainText("(No description available)")
        self._fit_desc_box(slot_index)

    def _update_all_btn_states(self) -> None:
        can_copy = self._num_slots > 1
        for btn in self._all_btns:
            btn.setEnabled(can_copy)

    # ── Slot actions ────────────────────────────────────────────────────────

    def _browse(self, slot_index: int) -> None:
        from gui.dialogs.equipment_browser import EquipmentBrowserDialog  # noqa: lazy
        card_eqp = self._eqp_override if self._slot_key == "left_hand" else None
        current = self._card_ids[slot_index]
        dlg = EquipmentBrowserDialog(
            self._slot_key, current,
            job_id=self._job_id,
            item_type_override="IT_CARD",
            eqp_override=card_eqp,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_id = dlg.selected_item_id()
            self._card_ids[slot_index] = new_id
            self._name_labels[slot_index].setText(self._card_label(slot_index))
            self._show_desc(new_id, slot_index)

    def _clear_slot(self, slot_index: int) -> None:
        self._card_ids[slot_index] = None
        self._name_labels[slot_index].setText(self._card_label(slot_index))
        self._show_desc(None, slot_index)

    def _copy_to_all(self, source_index: int) -> None:
        cid = self._card_ids[source_index]
        for i in range(self._num_slots):
            self._card_ids[i] = cid
            self._name_labels[i].setText(self._card_label(i))
            self._show_desc(cid, i)

    # ── EQP override injection ───────────────────────────────────────────────

    def set_eqp_override(self, eqp: Optional[set]) -> None:
        self._eqp_override = eqp

    # ── Public API ───────────────────────────────────────────────────────────

    def result_card_ids(self) -> list[Optional[int]]:
        return list(self._card_ids)
