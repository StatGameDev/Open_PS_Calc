"""
MiscSection — active item combo display.

Shows active item combos from GearBonuses.active_combo_descriptions, which is
pre-computed by GearBonusAggregator.apply_combo_bonuses() with full stat context
(base stats, level, class). Populated via refresh_combos(), called from
main_window._run_status_calc() after every resolve_player_state().

Input:  list[str] via refresh_combos()
Output: read-only display; collect_into() is a no-op
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.models.build import PlayerBuild
from gui.section import Section


class MiscSection(Section):

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(3)

        self._placeholder = QLabel("No active item combos.")
        self._placeholder.setObjectName("combat_field_label")
        self._placeholder.setWordWrap(True)
        self._layout.addWidget(self._placeholder)

        self._combo_labels: list[QLabel] = []

        self.add_content_widget(self._container)

    def load_build(self, build: PlayerBuild) -> None:
        """Clear combo display. Combos are populated via refresh_combos() after resolve_player_state."""
        self._clear_combos()

    def refresh_combos(self, descriptions: list[str]) -> None:
        """Display pre-computed combo descriptions from GearBonuses.active_combo_descriptions."""
        self._clear_combos()
        if not descriptions:
            return
        self._placeholder.hide()
        for desc in descriptions:
            lbl = QLabel(f"\u2022 {desc}")
            lbl.setObjectName("combat_field_label")
            lbl.setWordWrap(True)
            self._layout.addWidget(lbl)
            self._combo_labels.append(lbl)

    def _clear_combos(self) -> None:
        for lbl in self._combo_labels:
            self._layout.removeWidget(lbl)
            lbl.deleteLater()
        self._combo_labels.clear()
        self._placeholder.setText("No active item combos.")
        self._placeholder.show()

    def collect_into(self, build: PlayerBuild) -> None:
        pass
