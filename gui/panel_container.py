"""
PanelContainer — horizontal QSplitter hosting the builder and combat panels.

Instantiates all Section widgets from layout_config (gui/layout_config.json),
manages builder/combat focus states, and handles drag-to-snap and step-bar nudge.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QSplitter, QWidget

from gui.panel import Panel
from gui.section import Section

# ── Section factory ───────────────────────────────────────────────────────────
# Map each layout_config key to its class. Swapping a stub for a real
# implementation requires only updating the import here — no other files change.

from gui.sections.build_header import BuildHeaderSection
from gui.sections.stats_section import StatsSection
from gui.sections.equipment_section import EquipmentSection
from gui.sections.active_items_section import ManualAdjSection
from gui.sections.buffs_section import BuffsSection
from gui.sections.player_debuffs_section import PlayerDebuffsSection
from gui.sections.consumables_section import ConsumablesSection
from gui.sections.misc_section import MiscSection
from gui.sections.passive_section import PassiveSection
from gui.sections.combat_controls import CombatControlsSection
from gui.sections.summary_section import SummarySection
from gui.sections.step_breakdown import StepBreakdownSection
from gui.sections.target_section import TargetSection
from gui.sections.incoming_damage import IncomingDamageSection
from gui.sections.target_state_section import TargetStateSection

_SECTION_FACTORY: dict[str, type[Section]] = {
    "build_header":     BuildHeaderSection,
    "stats_section":    StatsSection,
    "equipment_section": EquipmentSection,
    "passive_section":       PassiveSection,
    "buffs_section":         BuffsSection,
    "player_debuffs_section": PlayerDebuffsSection,
    "consumables_section":   ConsumablesSection,
    "misc_section":          MiscSection,
    "active_items_section":  ManualAdjSection,
    "combat_controls":  CombatControlsSection,
    "summary_section":  SummarySection,
    "step_breakdown":   StepBreakdownSection,
    "target_section":   TargetSection,
    "target_state_section": TargetStateSection,
    "incoming_damage":  IncomingDamageSection,
}


class PanelContainer(QSplitter):
    """
    Horizontal QSplitter hosting the builder and combat panels.

    Responsibilities:
    - Instantiates all Section widgets from layout_config (gui/layout_config.json)
      and places them in the correct panel.
    - Manages focus states (builder_focused / combat_focused): adjusts splitter
      ratio and calls set_slim_mode on all sections.
    - Debounced drag-to-snap: after the user stops dragging, snaps to the
      nearest named focus state if within snap_threshold.
    - Step breakdown nudge: temporarily widens the combat panel on
      expand_requested, restores on collapse_requested.
    """

    focus_state_changed = Signal(str)

    def __init__(self, layout_config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

        self._focus_states: dict[str, dict] = layout_config["focus_states"]
        self._snap_threshold: float = layout_config.get("snap_threshold", 0.05)
        self._current_focus: str | None = None
        self._pending_focus_state: str = "builder_focused"
        self._pre_nudge_sizes: list[int] | None = None

        self._sections: dict[str, Section] = {}
        self._section_panel: dict[str, str] = {}  # key → "builder" | "combat"

        self.setHandleWidth(3)

        # ── Create panels ─────────────────────────────────────────────────
        self._builder_panel = Panel("builder")
        self._combat_panel = Panel("combat")
        self.addWidget(self._builder_panel)
        self.addWidget(self._combat_panel)

        # ── Instantiate sections ──────────────────────────────────────────
        # Pass 1: create instances; register in self._sections / self._section_panel.
        # Collect (key, section, panel_name, row_group) for layout pass.
        _sec_defs: list[tuple[str, Section, str, str | None]] = []
        for sec_def in layout_config.get("sections", []):
            key = sec_def["key"]
            cls = _SECTION_FACTORY.get(key)
            if cls is None:
                print(f"WARNING: No factory entry for section key '{key}' — skipping.")
                continue

            section = cls(
                key=key,
                display_name=sec_def["display_name"],
                default_collapsed=sec_def.get("default_collapsed", False),
                compact_modes=sec_def.get("compact_modes", []),
            )

            panel_name = sec_def.get("panel", "builder")
            self._sections[key] = section
            self._section_panel[key] = panel_name
            section.expand_requested.connect(self._on_section_expand_requested)
            section.collapse_requested.connect(self._on_section_collapse_requested)
            _sec_defs.append((key, section, panel_name, sec_def.get("row_group")))

        # Pass 2: add sections to panels, grouping row_group members side-by-side.
        # Order follows first appearance of each group in the sections list.
        _seen_groups: set[str] = set()
        for key, section, panel_name, row_group in _sec_defs:
            if row_group is not None and row_group in _seen_groups:
                continue  # already placed with its group
            panel = self._builder_panel if panel_name == "builder" else self._combat_panel
            if row_group is None:
                panel.add_section(section)
            else:
                _seen_groups.add(row_group)
                group = [s for _k, s, _p, rg in _sec_defs if rg == row_group]
                panel.add_section_row(group)

        # ── Wire combat panel's step-bar forwarding signals ──────────────
        # These propagate StepsBar expand/collapse to the outer-splitter nudge.
        self._combat_panel.steps_expand_requested.connect(self._on_section_expand_requested)
        self._combat_panel.steps_collapse_requested.connect(self._on_section_collapse_requested)

        # ── Drag-to-snap debounce timer ───────────────────────────────────
        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(200)
        self._snap_timer.timeout.connect(self._check_snap)
        self.splitterMoved.connect(self._on_splitter_moved)

    # ── Focus state management ─────────────────────────────────────────────

    def set_focus_state(self, state: str) -> None:
        if state == self._current_focus:
            return
        self._current_focus = state

        fraction = self._focus_states[state]["builder_fraction"]
        total = self.width()
        if total > 0:
            self.blockSignals(True)
            self.setSizes([int(total * fraction), int(total * (1 - fraction))])
            self.blockSignals(False)

        focused_panel = "builder" if state == "builder_focused" else "combat"
        for key, sec in self._sections.items():
            sec.set_slim_mode(self._section_panel[key] != focused_panel)

        # Show/hide the steps sidebar; expanded state is preserved across focus switches.
        show_bar = focused_panel == "builder"
        self._combat_panel.set_steps_bar_visible(show_bar)

        self.focus_state_changed.emit(state)

    def focus_builder(self) -> None:
        self.set_focus_state("builder_focused")

    def focus_combat(self) -> None:
        self.set_focus_state("combat_focused")

    # ── First-show sizing ──────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending_focus_state:
            self.set_focus_state(self._pending_focus_state)
            self._pending_focus_state = ""

    # ── Drag-to-snap ───────────────────────────────────────────────────────

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        self._snap_timer.start()

    def _check_snap(self) -> None:
        sizes = self.sizes()
        total = sizes[0] + sizes[1]
        if total == 0:
            return
        ratio = sizes[0] / total
        for state_name, state_data in self._focus_states.items():
            if abs(ratio - state_data["builder_fraction"]) <= self._snap_threshold:
                self.set_focus_state(state_name)
                return
        # Outside all snap zones: ratio updated visually, compact states unchanged.

    # ── Step breakdown expand/collapse nudge ───────────────────────────────

    def _on_section_expand_requested(self) -> None:
        self._pre_nudge_sizes = self.sizes()
        delta = int(self.width() * 0.05)
        s = self.sizes()
        self.blockSignals(True)
        self.setSizes([max(0, s[0] - delta), s[1] + delta])
        self.blockSignals(False)

    def _on_section_collapse_requested(self) -> None:
        if self._pre_nudge_sizes is not None:
            self.blockSignals(True)
            self.setSizes(self._pre_nudge_sizes)
            self.blockSignals(False)
            self._pre_nudge_sizes = None

    # ── Public accessor ────────────────────────────────────────────────────

    def get_section(self, key: str) -> Section:
        """Return the Section instance for the given layout_config key."""
        return self._sections[key]

    @property
    def steps_bar(self):
        """The combat panel's StepsBar (shown when builder is focused)."""
        return self._combat_panel.steps_bar
