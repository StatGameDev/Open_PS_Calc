"""
TargetSection — read-only display of mob stats for the selected target.

Full view: all mob fields including pipeline fields and base stats.
Slim/compact view: single summary line (Name  DEF:x  VIT:x  MDEF:x  INT:x  Race  Element  Size  [Boss]).

Input:  refresh_mob(mob_id) — reads from DataLoader.get_monster_data()
Output: display only; no load_build / collect_into
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from core.data_loader import loader
from gui.section import Section


class TargetSection(Section):

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._compact_widget: QWidget | None = None
        self._compact_label: QLabel | None = None

        # ── Full grid ────────────────────────────────────────────────────
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)

        self._labels: dict[str, QLabel] = {}

        # (row_key, display_label)
        rows = [
            ("name",          "Name"),
            ("id",            "ID"),
            ("level",         "Level"),
            ("hp",            "HP"),
            ("def_",          "DEF"),
            ("mdef",          "MDEF"),
            ("element",       "Element"),
            ("size",          "Size"),
            ("race",          "Race"),
            ("is_boss",       "Boss"),
            ("_sep", None),         # separator before base stats
            ("stat_str",      "STR"),
            ("stat_agi",      "AGI"),
            ("stat_vit",      "VIT"),
            ("stat_int",      "INT"),
            ("stat_dex",      "DEX"),
            ("stat_luk",      "LUK"),
        ]

        row_i = 0
        for row_key, display in rows:
            if row_key == "_sep":
                sep = QLabel("Base Stats")
                sep.setObjectName("target_section_header")
                grid.addWidget(sep, row_i, 0, 1, 2)
                row_i += 1
                continue

            name_lbl = QLabel(display)
            name_lbl.setObjectName("target_stat_label")
            grid.addWidget(name_lbl, row_i, 0)

            val_lbl = QLabel("—")
            val_lbl.setObjectName("target_stat_value")
            self._labels[row_key] = val_lbl
            grid.addWidget(val_lbl, row_i, 1)
            row_i += 1

        self.add_content_widget(grid_widget)

    # ── Compact API ────────────────────────────────────────────────────────

    def _build_compact_widget(self) -> None:
        w = QWidget()
        from PySide6.QtWidgets import QHBoxLayout
        layout = QHBoxLayout(w)
        layout.setContentsMargins(4, 2, 4, 2)
        lbl = QLabel("—")
        lbl.setObjectName("target_compact_summary")
        self._compact_label = lbl
        layout.addWidget(lbl)
        layout.addStretch()
        w.setVisible(False)
        self._compact_widget = w
        self.layout().addWidget(w)

    def _enter_slim(self) -> None:
        if self._compact_widget is None:
            self._build_compact_widget()
        self._update_compact_label()
        self._compact_widget.setVisible(True)

    def _exit_slim(self) -> None:
        if self._compact_widget is not None:
            self._compact_widget.setVisible(False)

    def _update_compact_label(self) -> None:
        if self._compact_label is None:
            return
        name = self._labels.get("name")
        def_ = self._labels.get("def_")
        vit  = self._labels.get("stat_vit")
        ele  = self._labels.get("element")
        size = self._labels.get("size")
        boss = self._labels.get("is_boss")

        parts: list[str] = []
        if name and name.text() != "—":
            parts.append(name.text())
        if def_:
            parts.append(f"DEF:{def_.text()}")
        if vit:
            parts.append(f"VIT:{vit.text()}")
        mdef = self._labels.get("mdef")
        stat_int = self._labels.get("stat_int")
        race = self._labels.get("race")
        if mdef:
            parts.append(f"MDEF:{mdef.text()}")
        if stat_int:
            parts.append(f"INT:{stat_int.text()}")
        if race:
            parts.append(race.text())
        if ele:
            parts.append(ele.text())
        if size:
            parts.append(size.text())
        if boss and boss.text() == "Yes":
            parts.append("Boss")

        self._compact_label.setText("  ".join(parts) if parts else "—")

    # ── Public API ─────────────────────────────────────────────────────────

    def refresh_mob(self, mob_id: Optional[int]) -> None:
        """Update all displayed values from mob_db. Clears to '—' if None."""
        if mob_id is None:
            self._clear()
            return

        data = loader.get_monster_data(mob_id)
        if data is None:
            self._clear()
            return

        element_id    = data.get("element", 0)
        element_level = data.get("element_level", 1)
        element_name  = loader.get_element_name(element_id)
        stats         = data.get("stats", {})

        self._labels["name"].setText(str(data.get("name", "—")))
        self._labels["id"].setText(str(data.get("id", "—")))
        self._labels["level"].setText(str(data.get("level", "—")))
        self._labels["hp"].setText(str(data.get("hp", "—")))
        self._labels["def_"].setText(str(data.get("def_", "—")))
        self._labels["mdef"].setText(str(data.get("mdef", "—")))
        self._labels["element"].setText(f"{element_name} / {element_level}")
        self._labels["size"].setText(str(data.get("size", "—")))
        self._labels["race"].setText(str(data.get("race", "—")))
        self._labels["is_boss"].setText("Yes" if data.get("is_boss") else "No")

        self._labels["stat_str"].setText(str(stats.get("str", "—")))
        self._labels["stat_agi"].setText(str(stats.get("agi", "—")))
        self._labels["stat_vit"].setText(str(stats.get("vit", "—")))
        self._labels["stat_int"].setText(str(stats.get("int", "—")))
        self._labels["stat_dex"].setText(str(stats.get("dex", "—")))
        self._labels["stat_luk"].setText(str(stats.get("luk", "—")))

        if self._compact_widget is not None and self._compact_widget.isVisible():
            self._update_compact_label()

    def _clear(self) -> None:
        for lbl in self._labels.values():
            lbl.setText("—")
        if self._compact_label is not None:
            self._compact_label.setText("—")
