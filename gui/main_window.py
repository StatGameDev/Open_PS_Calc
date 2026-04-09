"""
MainWindow — top-level application window. Owns the top bar, PanelContainer, all section
signal wiring, and the full recalculation pipeline (status → outgoing → incoming damage).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import dataclasses

from core import build_applicator
from core.build_manager import BuildManager
from core.server_profiles import get_profile
from core.calculators.battle_pipeline import BattlePipeline
from core.calculators.incoming_magic_pipeline import IncomingMagicPipeline
from core.calculators.incoming_physical_pipeline import IncomingPhysicalPipeline
from core.calculators.status_calculator import StatusCalculator
from core.calculators import target_utils
from core.config import BattleConfig
from core.data_loader import loader
from core.models.build import PlayerBuild
from core.player_state_builder import resolve_player_state
from core.models.damage import BattleResult
from core.models.skill import SkillInstance
from core.models.target import Target
from gui import app_config
from gui.panel_container import PanelContainer
from gui.sections.build_header import BuildHeaderSection
from gui.sections.combat_controls import CombatControlsSection
from gui.sections.equipment_section import EquipmentSection
from gui.sections.active_items_section import ManualAdjSection
from gui.sections.buffs_section import BuffsSection
from gui.sections.consumables_section import ConsumablesSection
from gui.sections.misc_section import MiscSection
from gui.sections.player_debuffs_section import PlayerDebuffsSection
from gui.sections.passive_section import PassiveSection
from gui.sections.stats_section import StatsSection
from gui.sections.incoming_damage import IncomingDamageSection
from gui.sections.step_breakdown import StepBreakdownSection
from gui.sections.summary_section import SummarySection
from gui.sections.target_section import TargetSection
from gui.sections.target_state_section import TargetStateSection
from gui.widgets import NoWheelCombo
from version import get_version

# _apply_weapon_endow and _ENDOW_SC_ELEMENT are in core/build_applicator.py.


class MainWindow(QMainWindow):
    """
    Top-level window. Owns the top bar and PanelContainer.
    No business logic here — widgets emit signals; core handles calculation.
    """

    server_changed = Signal(str)
    result_updated = Signal(object)  # Optional[BattleResult]; object allows None

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PS Calc — Pre-Renewal Damage Calculator")
        self.resize(1400, 900)
        self.setMinimumSize(1280, 720)

        self._current_build: PlayerBuild | None = None
        self._current_build_name: str = ""
        self._loading_build: bool = False
        self._config = BattleConfig()
        self._pipeline = BattlePipeline(self._config)
        self._incoming_phys_pipeline = IncomingPhysicalPipeline(self._config)
        self._incoming_magic_pipeline = IncomingMagicPipeline(self._config)

        # Load layout config (file I/O outside widget constructors)
        with open("gui/layout_config.json", "r", encoding="utf-8") as f:
            layout_config = json.load(f)

        # ── Central widget ────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._panel_container = PanelContainer(layout_config=layout_config)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._panel_container, stretch=1)

        # ── Typed section references — builder ────────────────────────────
        self._build_header:    BuildHeaderSection = self._panel_container.get_section("build_header")       # type: ignore[assignment]
        self._stats_section:   StatsSection       = self._panel_container.get_section("stats_section")     # type: ignore[assignment]
        self._equip_section:   EquipmentSection   = self._panel_container.get_section("equipment_section") # type: ignore[assignment]
        self._passive_section:   PassiveSection       = self._panel_container.get_section("passive_section")        # type: ignore[assignment]
        self._buffs_section:     BuffsSection         = self._panel_container.get_section("buffs_section")          # type: ignore[assignment]
        self._player_debuffs:    PlayerDebuffsSection = self._panel_container.get_section("player_debuffs_section") # type: ignore[assignment]
        self._consumables:       ConsumablesSection   = self._panel_container.get_section("consumables_section")    # type: ignore[assignment]
        self._misc_section:      MiscSection          = self._panel_container.get_section("misc_section")           # type: ignore[assignment]
        self._active_items:      ManualAdjSection     = self._panel_container.get_section("active_items_section")   # type: ignore[assignment]

        # ── Typed section references — combat ─────────────────────────────
        self._combat_controls:  CombatControlsSection  = self._panel_container.get_section("combat_controls")   # type: ignore[assignment]
        self._summary_section:  SummarySection         = self._panel_container.get_section("summary_section")   # type: ignore[assignment]
        self._step_breakdown:   StepBreakdownSection   = self._panel_container.get_section("step_breakdown")    # type: ignore[assignment]
        self._target_section:   TargetSection          = self._panel_container.get_section("target_section")    # type: ignore[assignment]
        self._incoming_damage:  IncomingDamageSection  = self._panel_container.get_section("incoming_damage")   # type: ignore[assignment]
        self._target_state:     TargetStateSection     = self._panel_container.get_section("target_state_section") # type: ignore[assignment]

        self._connect_builder_signals()
        self._connect_combat_signals()

        # Wire result_updated to combat sections
        self.result_updated.connect(self._summary_section.refresh)
        self.result_updated.connect(self._step_breakdown.refresh)
        self.result_updated.connect(self._panel_container.steps_bar.refresh)

        self._refresh_builds()

        # ── Scale toast ───────────────────────────────────────────────────
        self._scale_toast = QLabel(central)
        self._scale_toast.setObjectName("scale_toast")
        self._scale_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scale_toast.hide()
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.timeout.connect(self._scale_toast.hide)

        # Debounce timer: coalesces rapid Ctrl+scroll into one font rescale.
        # Font rescale is fast (no CSS re-polish) so interval can be short.
        self._apply_scale_timer = QTimer(self)
        self._apply_scale_timer.setSingleShot(True)
        self._apply_scale_timer.setInterval(50)
        self._apply_scale_timer.timeout.connect(self._apply_scaled_fonts)

        # ── Scale keybinds ────────────────────────────────────────────────
        QShortcut(QKeySequence("Ctrl++"), self).activated.connect(
            lambda: self._adjust_scale(app_config._SCALE_STEP)
        )
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(
            lambda: self._adjust_scale(app_config._SCALE_STEP)
        )
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(
            lambda: self._adjust_scale(-app_config._SCALE_STEP)
        )

        # Ctrl+scroll: accumulate wheel delta so smooth-scroll devices still
        # produce one step per notch-equivalent (120 units) rather than many.
        self._wheel_accum: int = 0
        QApplication.instance().installEventFilter(self)

    # ── Top bar construction ───────────────────────────────────────────────

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("top_bar")
        bar.setFixedHeight(44)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        title = QLabel("PS Calc")
        title.setObjectName("app_title")
        layout.addWidget(title)

        ver_label = QLabel(get_version())
        ver_label.setObjectName("version_label")
        layout.addWidget(ver_label)
        layout.addSpacing(8)

        layout.addWidget(QLabel("Build:"))
        self._build_combo = NoWheelCombo()
        self._build_combo.setMinimumWidth(200)
        self._build_combo.currentIndexChanged.connect(self._on_build_index_changed)
        layout.addWidget(self._build_combo)

        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._on_new_build)
        layout.addWidget(new_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._on_save_build)
        self._save_btn.setEnabled(False)
        layout.addWidget(self._save_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_builds)
        layout.addWidget(refresh_btn)

        layout.addStretch()

        # Server toggle — exclusive button group
        self._server_group = QButtonGroup(self)
        self._server_group.setExclusive(True)

        std_btn = QPushButton("Standard")
        std_btn.setCheckable(True)
        std_btn.setChecked(True)
        std_btn.setObjectName("server_btn")

        ps_btn = QPushButton("Payon Stories")
        ps_btn.setCheckable(True)
        ps_btn.setObjectName("server_btn")

        self._server_group.addButton(std_btn, 0)
        self._server_group.addButton(ps_btn, 1)
        self._server_group.idToggled.connect(self._on_server_toggled)

        layout.addWidget(std_btn)
        layout.addWidget(ps_btn)

        layout.addStretch()

        builder_btn = QPushButton("◧ Builder")
        builder_btn.setObjectName("focus_btn")
        builder_btn.clicked.connect(self._focus_builder)
        layout.addWidget(builder_btn)

        combat_btn = QPushButton("◨ Combat")
        combat_btn.setObjectName("focus_btn")
        combat_btn.clicked.connect(self._focus_combat)
        layout.addWidget(combat_btn)

        return bar

    # ── Signal wiring ──────────────────────────────────────────────────────

    def _connect_builder_signals(self) -> None:
        """Wire all builder section change signals to _on_build_changed."""
        self._build_header.build_name_changed.connect(self._on_build_changed)
        self._build_header.job_changed.connect(self._on_build_changed)
        self._build_header.job_changed.connect(self._equip_section.update_for_job)
        self._build_header.job_changed.connect(self._passive_section.update_job)
        self._build_header.job_changed.connect(self._buffs_section.update_job)
        self._build_header.job_changed.connect(self._combat_controls.update_job)
        self._build_header.level_changed.connect(self._on_build_changed)
        self._stats_section.stats_changed.connect(self._on_build_changed)
        self._equip_section.equipment_changed.connect(self._on_build_changed)
        self._passive_section.passives_changed.connect(self._on_build_changed)
        self._buffs_section.changed.connect(self._on_build_changed)
        self._buffs_section.sc_level_changed.connect(self._on_sc_level_changed)
        self.server_changed.connect(lambda s: loader.set_profile(get_profile(s)))
        self.server_changed.connect(self._buffs_section.set_server)
        self.server_changed.connect(self._passive_section.set_server)
        self.server_changed.connect(self._combat_controls.set_server)
        self._player_debuffs.changed.connect(self._on_build_changed)
        self._consumables.changed.connect(self._on_build_changed)
        self._active_items.bonuses_changed.connect(self._on_build_changed)
        self._target_state.state_changed.connect(self._on_build_changed)
        self._incoming_damage.config_changed.connect(self._on_incoming_config_changed)

    def _connect_combat_signals(self) -> None:
        """Wire combat section change signals to _on_build_changed."""
        self._combat_controls.combat_settings_changed.connect(self._on_build_changed)
        self._combat_controls.spirit_spheres_changed.connect(self._buffs_section.set_spirit_spheres)

    def _on_sc_level_changed(self, sc_key: str, value: int) -> None:
        """Forward SC level changes to any combat param that mirrors that SC key.

        Runs synchronously before _on_build_changed collects the build, so
        collect_into reads the already-updated widget value.
        """
        from gui.skill_param_defs import SKILL_PARAM_REGISTRY
        for specs in SKILL_PARAM_REGISTRY.values():
            for spec in specs:
                if spec.mirrors_sc_key == sc_key:
                    self._combat_controls.set_param_value(spec.key, value)

    # ── UI scale ───────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._wheel_accum += event.angleDelta().y()
            while self._wheel_accum >= 120:
                self._adjust_scale(app_config._SCALE_STEP)
                self._wheel_accum -= 120
            while self._wheel_accum <= -120:
                self._adjust_scale(-app_config._SCALE_STEP)
                self._wheel_accum += 120
            return True  # consume event; don't scroll the widget underneath
        return False

    def _adjust_scale(self, delta: float) -> None:
        app_config.set_scale_override(app_config.scale_override() + delta)
        self._show_scale_toast()
        self._apply_scale_timer.start()  # restart debounce on each event

    def _apply_scaled_fonts(self) -> None:
        """Update fonts after a scale change. O(n_widgets) but no CSS re-polish."""
        QApplication.instance().setFont(app_config.app_font())
        app_config.rescale_all_fonts(self)

    def _show_scale_toast(self) -> None:
        pct = round(app_config.effective_scale() * 100)
        self._scale_toast.setText(f"  Scale: {pct}%  ")
        self._scale_toast.adjustSize()
        self._reposition_toast()
        self._scale_toast.raise_()
        self._scale_toast.show()
        self._scale_timer.start(2000)

    def _reposition_toast(self) -> None:
        cw = self.centralWidget()
        if cw is None:
            return
        margin = 12
        self._scale_toast.move(margin, cw.height() - self._scale_toast.height() - margin)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_scale_toast") and self._scale_toast.isVisible():
            self._reposition_toast()

    # ── Build list helpers ─────────────────────────────────────────────────

    @staticmethod
    def _read_build_display_name(path: str) -> str:
        """Fast read of just the 'name' field from a build JSON. Returns stem on failure."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("name") or ""
        except Exception:
            return ""

    def _refresh_builds(self, select_name: str | None = None) -> None:
        """Populate combo with display names (item data = file stem).
        select_name can be a display name or a file stem — both are searched.
        """
        stems = sorted(BuildManager.list_builds(app_config.SAVES_DIR))
        # Prefer the display name of the currently selected build when no hint given
        want = select_name or self._build_combo.currentText()
        self._build_combo.blockSignals(True)
        self._build_combo.clear()
        for stem in stems:
            path = os.path.join(app_config.SAVES_DIR, f"{stem}.json")
            display = self._read_build_display_name(path) or stem
            self._build_combo.addItem(display, userData=stem)
        # Select by display name first, then by stem (item data)
        idx = self._build_combo.findText(want)
        if idx < 0:
            idx = self._build_combo.findData(want)
        if idx >= 0:
            self._build_combo.setCurrentIndex(idx)
        elif self._build_combo.count() > 0:
            self._build_combo.setCurrentIndex(0)
        self._build_combo.blockSignals(False)
        pairs = [(stem, self._read_build_display_name(os.path.join(app_config.SAVES_DIR, f"{stem}.json")) or stem)
                 for stem in stems]
        self._combat_controls.refresh_target_builds(pairs)
        # Load whichever build is now selected
        stem = self._build_combo.currentData()
        if stem:
            self._on_build_selected(stem)

    def _on_build_index_changed(self, index: int) -> None:
        stem = self._build_combo.itemData(index)
        if stem:
            self._on_build_selected(stem)

    def _on_new_build(self) -> None:
        from gui.dialogs.new_build_dialog import NewBuildDialog
        dlg = NewBuildDialog(app_config.SAVES_DIR, parent=self)
        if dlg.exec() == NewBuildDialog.DialogCode.Accepted:
            name = dlg.created_build_name()
            if name:
                self._refresh_builds(select_name=name)

    def _on_save_build(self) -> None:
        """Save using the current Name field value as the filename.
        _collect_build() is called first so build.name reflects what the user typed.
        If the name changed, refreshes the build combo and updates _current_build_name."""
        if self._current_build is None:
            return
        self._collect_build()
        build = self._current_build
        if not build.name:
            return
        path = os.path.join(app_config.SAVES_DIR, f"{build.name}.json")
        try:
            BuildManager.save_build(build, path)
        except Exception as exc:
            print(f"WARNING: Failed to save build '{build.name}': {exc}")
            return
        if self._current_build_name != build.name:
            self._current_build_name = build.name
            self._refresh_builds(select_name=build.name)

    def _on_build_selected(self, name: str) -> None:
        if not name:
            return
        self._current_build_name = name
        path = os.path.join(app_config.SAVES_DIR, f"{name}.json")
        try:
            build = BuildManager.load_build(path)
        except Exception as exc:
            print(f"WARNING: Failed to load build '{name}': {exc}")
            return

        # Legacy bonus_* fields from old saves are no longer user-editable.
        # Zero them on load so they don't stack on top of auto-computed gear bonuses.
        build.bonus_str = build.bonus_agi = build.bonus_vit = 0
        build.bonus_int = build.bonus_dex = build.bonus_luk = 0
        build.bonus_batk = build.bonus_hit = build.bonus_flee = build.bonus_cri = 0
        build.equip_def = build.equip_mdef = build.bonus_aspd_percent = 0
        self._current_build = build
        self._save_btn.setEnabled(True)
        self._loading_build = True
        try:
            # Prime all sections with the correct server before filling values,
            # so set_server (which sets spinbox maxima) runs before load_build writes values.
            self.server_changed.emit(build.server)
            self._load_build_into_sections(build)
        finally:
            self._loading_build = False

        # Sync server toggle to the loaded build's server field
        self._server_group.blockSignals(True)
        is_payon = (build.server == "payon_stories")
        btn = self._server_group.button(1 if is_payon else 0)
        if btn:
            btn.setChecked(True)
        self._server_group.blockSignals(False)

        base_title = "PS Calc — Pre-Renewal Damage Calculator"
        self.setWindowTitle(base_title + (" — Payon Stories" if is_payon else ""))

        gb, eff_build, weapon, status = resolve_player_state(self._current_build, self._config)
        self._run_status_calc(gb, eff_build, weapon, status)
        self._run_battle_pipeline(gb, eff_build, weapon, status)

    def _load_build_into_sections(self, build: PlayerBuild) -> None:
        """Push build data to all sections (no change signals fired)."""
        self._build_header.load_build(build)
        self._stats_section.load_build(build)
        self._equip_section.load_build(build)
        self._passive_section.load_build(build)
        self._buffs_section.load_build(build)
        self._player_debuffs.load_build(build)
        self._consumables.load_build(build)
        self._misc_section.load_build(build)
        self._active_items.load_build(build)
        self._combat_controls.load_build(build)
        self._target_state.load_build(build)

    # ── Build-change pipeline ─────────────────────────────────────────────

    def _on_build_changed(self, *_args) -> None:
        """Called when any section changes. Collects build and recalculates."""
        if self._loading_build:
            return
        if self._current_build is None:
            return
        self._collect_build()
        gb, eff_build, weapon, status = resolve_player_state(self._current_build, self._config)
        self._run_status_calc(gb, eff_build, weapon, status)
        self._run_battle_pipeline(gb, eff_build, weapon, status)

    def _on_incoming_config_changed(self) -> None:
        """Re-run battle pipeline when incoming damage config changes (no build change)."""
        if self._current_build is None:
            return
        gb, eff_build, weapon, status = resolve_player_state(self._current_build, self._config)
        self._run_battle_pipeline(gb, eff_build, weapon, status)

    def _collect_build(self) -> None:
        """Update self._current_build from all sections in-place."""
        build = self._current_build
        if build is None:
            return
        self._build_header.collect_into(build)
        self._stats_section.collect_into(build)
        self._equip_section.collect_into(build)
        self._passive_section.collect_into(build)
        self._buffs_section.collect_into(build)
        self._player_debuffs.collect_into(build)
        self._consumables.collect_into(build)
        self._misc_section.collect_into(build)
        self._active_items.collect_into(build)
        self._combat_controls.collect_into(build)
        self._target_state.collect_into(build)
        # bonus_str–luk and flat bonus fields are auto-computed from gear/AI/MA;
        # zero them so old loaded values don't double-stack on top of gear bonuses.
        build.bonus_str = 0
        build.bonus_agi = 0
        build.bonus_vit = 0
        build.bonus_int = 0
        build.bonus_dex = 0
        build.bonus_luk = 0
        build.bonus_batk = 0
        build.bonus_hit = 0
        build.bonus_flee = 0
        build.bonus_cri = 0
        build.equip_def = 0
        build.equip_mdef = 0
        build.bonus_aspd_percent = 0
        build.bonus_matk_flat = 0

    def _run_status_calc(self, gb, eff_build, weapon, status) -> None:
        """Run StatusCalculator and push results to DerivedSection and StatsSection."""
        build = self._current_build
        if build is None:
            return
        jb_bonuses = loader.get_job_bonus_stats(build.job_id, build.job_level)
        resolved_armor_ele = build_applicator.resolve_armor_element(eff_build.armor_element, gb)
        self._stats_section.refresh(status, atk_ele=weapon.element, def_ele=resolved_armor_ele,
                                    profile=get_profile(eff_build.server))

        # ── Stat bonus display ─────────────────────────────────────────────
        # sc_display: everything that isn't gear/job/ai/manual — party buffs,
        # self buffs, passives, consumable foods, debuff penalties — computed as
        # the difference so the displayed total always matches StatusCalculator.
        _STAT_MAP = [
            ("str", "str_",  "str",  "base_str"),
            ("agi", "agi",   "agi",  "base_agi"),
            ("vit", "vit",   "vit",  "base_vit"),
            ("int", "int_",  "int_", "base_int"),
            ("dex", "dex",   "dex",  "base_dex"),
            ("luk", "luk",   "luk",  "base_luk"),
        ]
        sc_display: dict[str, int] = {}
        for key_s, gb_attr, status_attr, build_base_attr in _STAT_MAP:
            final = getattr(status, status_attr)
            base  = getattr(build, build_base_attr)
            gear  = int(getattr(gb, gb_attr, 0))
            jb_v  = jb_bonuses.get(gb_attr, 0)
            ma_v  = build.manual_adj_bonuses.get(key_s, 0)
            sc_display[key_s] = final - base - gear - jb_v - ma_v

        # ── Flat bonus SC/passive/consumable contributions ─────────────────
        # StatusCalculator emits status.sources[stat][label] = amount for every additive
        # SC/passive/song contribution. Sum per stat to get the display totals.
        # CRI sources are in 0.1% units (native scale) — divide by 10 for display.
        _cons = build_applicator.compute_consumable_bonuses(build.consumable_buffs)
        sc_flat: dict[str, int] = {}
        for _src_stat, _src_contribs in status.sources.items():
            _total = sum(_src_contribs.values())
            if _src_stat == "cri":
                _total = _total // 10  # 0.1% → 1% display units
            if _total:
                sc_flat[_src_stat] = _total
        # Consumable contributions to flat rows — not in StatusCalculator (pre-baked into build).
        for _cons_key, _sc_key in (("batk", "batk"), ("hit", "hit"), ("flee", "flee"), ("cri", "cri")):
            _cv = _cons.get(_cons_key, 0)
            if _cv:
                sc_flat[_sc_key] = sc_flat.get(_sc_key, 0) + _cv
        # ASPD% from consumables (multiplicative rate modifier — not tracked in sources).
        _aspd_cons = _cons.get("aspd_percent", 0)
        if _aspd_cons:
            sc_flat["aspd_pct"] = sc_flat.get("aspd_pct", 0) + _aspd_cons

        self._stats_section.update_from_bonuses(
            gb, build.manual_adj_bonuses, {}, sc_display,
            jb=jb_bonuses, sc_flat=sc_flat, base_level=build.base_level, job_id=build.job_id,
        )
        self._misc_section.refresh_combos(gb.active_combo_descriptions)

    def _run_battle_pipeline(self, gb, eff_build, weapon, status) -> None:
        """Run BattlePipeline and push BattleResult to combat sections."""
        if self._current_build is None:
            return
        skill = self._combat_controls.get_skill_instance()
        pvp_stem = self._combat_controls.get_target_pvp_stem()
        mob_id = None if pvp_stem else (
            self._combat_controls.get_target_mob_id() or eff_build.target_mob_id
        )

        # Resolve outgoing target
        if pvp_stem:
            pvp_path = os.path.join(app_config.SAVES_DIR, f"{pvp_stem}.json")
            try:
                pvp_build = BuildManager.load_build(pvp_path)
            except Exception as exc:
                print(f"WARNING: Failed to load PvP target build '{pvp_stem}': {exc}")
                pvp_build = None
            if pvp_build is not None:
                pvp_gb, pvp_eff, pvp_weapon, pvp_status = resolve_player_state(pvp_build, self._config)
                # Merge stat-cascade debuffs into pvp_eff after gear resolution so effects
                # like DECREASEAGI → AGI → FLEE/ASPD cascade correctly through StatusCalculator.
                target_scs = self._target_state.collect_target_player_scs()
                if target_scs:
                    pvp_eff = dataclasses.replace(
                        pvp_eff,
                        player_active_scs={**pvp_eff.player_active_scs, **target_scs},
                    )
                    pvp_status = StatusCalculator(self._config).calculate(pvp_eff, pvp_weapon)
                target = BuildManager.player_build_to_target(pvp_eff, pvp_status, pvp_gb, weapon=pvp_weapon)
            else:
                pvp_stem = None
                target = Target()
        else:
            target = loader.get_monster(mob_id) if mob_id is not None else None

        if target is None:
            self._target_section.refresh_mob(None)
            self._incoming_damage.refresh(None, None)
            self.result_updated.emit(None)
            return

        # Apply target state debuffs after target is resolved.
        # apply_to_target() sets target_active_scs flags and element/strip overrides.
        # apply_mob_scs() applies stat mutations for mob targets (player targets get
        # these via StatusCalculator, fed from collect_target_player_scs() above).
        self._target_state.set_target_type(target.is_pc)
        self._target_state.set_is_boss(target.is_boss)
        self._target_state.apply_to_target(target)
        if not target.is_pc:
            target_utils.apply_mob_scs(target, server=eff_build.server)

        # Always refresh target section — independent of pipeline success.
        self._target_section.refresh_mob(mob_id)

        # Incoming damage pipelines — player as defender.
        # gb already computed at top of function (with passive bonuses applied).
        player_target = BuildManager.player_build_to_target(eff_build, status, gb, weapon=weapon)
        _player_profile = get_profile(eff_build.server)
        # PS GS_ADJUSTMENT — 30% incoming ranged damage reduction.
        # Source: ps_skill_db.json id=505: "receives 30% less damage from ranged physical attacks".
        if ("SC_GS_ADJUSTMENT_LR_REDUCE" in _player_profile.mechanic_flags
                and eff_build.active_status_levels.get("SC_GS_ADJUSTMENT")):
            player_target.long_attack_def_rate += 30
        siegfried_lv = int(eff_build.support_buffs.get("SC_SIEGFRIED", 0))
        if siegfried_lv:
            # skill.c:13330 BD_SIEGFRIED val1=55+lv*5; passed as SC_SIEGFRIED.val2 via sc_start4 (skill.c:13753); applied to subele at status.c:2233
            resist = 55 + 5 * siegfried_lv
            for ele_key in ("Ele_Water", "Ele_Earth", "Ele_Fire", "Ele_Wind",
                            "Ele_Poison", "Ele_Holy", "Ele_Dark", "Ele_Ghost"):
                player_target.sub_ele[ele_key] = player_target.sub_ele.get(ele_key, 0) + resist
        phys_result = None
        magic_result = None
        is_ranged, ele_override, ratio_override = (
            self._incoming_damage.get_incoming_config()
        )
        if pvp_stem and pvp_build is not None:
            # PvP incoming: run the attacker's (pvp) pipeline against the current player as target
            try:
                pvp_battle = self._pipeline.calculate(pvp_status, pvp_weapon, SkillInstance(), player_target, pvp_eff, pvp_gb)
                phys_result = pvp_battle.normal
            except Exception as exc:
                print(f"WARNING: PvP incoming pipeline error: {exc}")
        elif mob_id is not None:
            # Strip debuff rates for incoming pipelines.
            _strip_scs = target.target_active_scs
            _is_ps = eff_build.server == "payon_stories"
            # SC_NOEQUIPWEAPON: −25 atk_percent vanilla (status.c:7757–7771); −40 ATK PS (ps_skill_db.json id=215)
            _strip_weapon_rate = (-40 if _is_ps else -25) if _strip_scs.get("SC_NOEQUIPWEAPON") else 0
            # SC_NOEQUIPHELM: −40% INT PS (ps_skill_db.json id=218)
            _strip_helm_int_rate = -40 if _strip_scs.get("SC_NOEQUIPHELM") else 0
            try:
                phys_result = self._incoming_phys_pipeline.calculate(
                    mob_id=mob_id,
                    player_target=player_target,
                    gear_bonuses=gb,
                    build=eff_build,
                    is_ranged=is_ranged,
                    mob_atk_bonus_rate=_strip_weapon_rate,
                    ele_override=ele_override,
                )
            except Exception as exc:
                print(f"WARNING: IncomingPhysicalPipeline error: {exc}")
            try:
                magic_result = self._incoming_magic_pipeline.calculate(
                    mob_id=mob_id,
                    player_target=player_target,
                    gear_bonuses=gb,
                    build=eff_build,
                    ele_override=ele_override,
                    ratio_override=ratio_override,
                    mob_matk_bonus_rate=target.matk_percent - 100,
                    mob_int_bonus_rate=_strip_helm_int_rate,
                )
            except Exception as exc:
                print(f"WARNING: IncomingMagicPipeline error: {exc}")
        self._incoming_damage.refresh(phys_result, magic_result)

        try:
            result = self._pipeline.calculate(status, weapon, skill, target, eff_build, gb)
        except Exception as exc:
            print(f"WARNING: BattlePipeline error: {exc}")
            result = None
        self.result_updated.emit(result)

    # ── Server toggle ──────────────────────────────────────────────────────

    def _on_server_toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        is_payon = (btn_id == 1)
        server_str = "payon_stories" if is_payon else "standard"

        if self._current_build is not None:
            self._current_build.server = server_str

        base_title = self.windowTitle().replace(" — Payon Stories", "")
        self.setWindowTitle(base_title + (" — Payon Stories" if is_payon else ""))

        self.server_changed.emit(server_str)
        self._on_build_changed()

    # ── Focus buttons ──────────────────────────────────────────────────────

    def _focus_builder(self) -> None:
        self._panel_container.focus_builder()

    def _focus_combat(self) -> None:
        self._panel_container.focus_combat()
