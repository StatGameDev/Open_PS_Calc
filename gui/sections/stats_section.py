"""
StatsSection — base stat inputs and derived stat display.

Left pane: base stat spinboxes with auto-computed bonus column and flat bonus rows.
Right pane: read-only derived stats (BATK, MATK, DEF, MDEF, FLEE, HIT, CRI, ASPD, …).
Driven by update_from_bonuses() after gear aggregation and refresh() after StatusCalculator.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.data_loader import loader
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.status import StatusData
from core.server_profiles import STANDARD, ServerProfile
from gui.section import Section
from gui.widgets import NoWheelSpin


def _stat_cost(v: int) -> int:
    """Cost to raise a stat from v to v+1 (pre-renewal).
    Source: pc.c:7191 #else RENEWAL: sp += (1 + (final + 9) / 10)
    """
    return 1 + (v + 9) // 10


def _spent_points(base: int) -> int:
    """Total stat points spent to raise a stat from 1 to base."""
    return sum(_stat_cost(i) for i in range(1, base))


# (display_label, key, base_attr, gb_attr)
# gb_attr: attribute name on GearBonuses, or None if not tracked there
_STATS: list[tuple[str, str, str, str | None]] = [
    ("STR", "str", "base_str",  "str_"),
    ("AGI", "agi", "base_agi",  "agi"),
    ("VIT", "vit", "base_vit",  "vit"),
    ("INT", "int", "base_int",  "int_"),
    ("DEX", "dex", "base_dex",  "dex"),
    ("LUK", "luk", "base_luk",  "luk"),
]

# (display_label, key, gb_attr, ai_key)
_FLAT_BONUSES: list[tuple[str, str, str | None, str]] = [
    ("BATK+",     "batk",     "batk",         "batk"),
    ("HIT+",      "hit",      "hit",           "hit"),
    ("FLEE+",     "flee",     "flee",          "flee"),
    ("FLEE2+",    "flee2",    "flee2",         "flee2"),
    ("CRI+",      "cri",      "cri",           "cri"),
    ("Hard DEF",  "def",      "def_",          "def"),
    ("Hard MDEF", "mdef",     "mdef_",         "mdef"),
    ("ASPD%",     "aspd_pct", "aspd_percent",  "aspd_pct"),
]

# (display_label, key, default_text)
_DERIVED_ROWS = [
    ("BATK",       "batk",         "—"),
    ("MATK",       "matk",         "—"),
    ("DEF",        "def",          "—"),
    ("MDEF",       "mdef",         "—"),
    ("FLEE",       "flee",         "—"),
    ("HIT",        "hit",          "—"),
    ("CRI",        "cri",          "—"),
    ("ASPD",       "aspd",         "—"),
    ("ATK Ele",    "atk_ele",      "—"),
    ("DEF Ele",    "def_ele",      "—"),
    ("HP",         "hp",           "—"),
    ("HP Regen",   "hp_regen",     "—"),
    ("SP",         "sp",           "—"),
    ("SP Regen",   "sp_regen",     "—"),
    ("Cast Red.",  "cast_red",     "—"),
    ("ACD Red.",   "acd_red",      "—"),
    ("SP Cost Red.", "sp_cost_red","—"),
]


def _fmt_bonus(v: int) -> str:
    return f"+{v}" if v > 0 else str(v)


def _make_tooltip(gear: int, ai: int, ma: int, sc: int = 0, jb: int = 0) -> str:
    parts = []
    if gear:
        parts.append(f"Gear: {_fmt_bonus(gear)}")
    if jb:
        parts.append(f"Job Bonus: {_fmt_bonus(jb)}")
    if sc:
        parts.append(f"Buffs: {_fmt_bonus(sc)}")
    if ai:
        parts.append(f"Active Items: {_fmt_bonus(ai)}")
    if ma:
        parts.append(f"Manual: {_fmt_bonus(ma)}")
    return "  |  ".join(parts) if parts else "No bonuses"


class StatsSection(Section):
    """Base stat spinboxes (STR/AGI/VIT/INT/DEX/LUK) + derived stats.

    Left pane: points label, stat spinboxes with auto-computed bonus column, flat bonuses.
    Right pane: read-only derived stats grid (BATK, MATK, DEF, MDEF, FLEE, HIT, CRI, ASPD, …).

    Exposes both update_from_bonuses() (called after gear aggregation) and refresh()
    (called after StatusCalculator) so main_window has a single Stats section to drive.
    """

    stats_changed = Signal()

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._compact_widget: QWidget | None = None
        self._compact_labels: dict[str, QLabel] = {}
        self._derived_compact_values: dict[str, QLabel] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._row_name_labels: dict[str, QLabel] = {}
        self._optional_rows: set[str] = {"cast_red", "acd_red", "sp_cost_red"}

        # Tracked numeric bonus values (auto-computed, not user-editable)
        self._bonus_values: dict[str, int] = {k: 0 for _, k, *_ in _STATS}
        self._flat_values:  dict[str, int] = {k: 0 for _, k, *_ in _FLAT_BONUSES}

        # Base level / job_id — updated by update_from_bonuses() for stat planner
        self._base_level: int = 1
        self._job_id: int = 0

        # ── Left: base stats ──────────────────────────────────────────────
        left = QWidget()
        left_vbox = QVBoxLayout(left)
        left_vbox.setContentsMargins(0, 0, 4, 0)
        left_vbox.setSpacing(4)

        self._points_label = QLabel("Stat Points: —")
        self._points_label.setObjectName("stat_points_label")
        left_vbox.addWidget(self._points_label)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)

        for col, header in enumerate(("", "Base", "+", "Bonus", "=", "Total", "Next+"), start=0):
            if header:
                lbl = QLabel(header)
                lbl.setObjectName("stat_col_header")
                grid.addWidget(lbl, 0, col)

        self._base_spins:   dict[str, QSpinBox] = {}
        self._bonus_labels: dict[str, QLabel]   = {}
        self._total_labels: dict[str, QLabel]   = {}
        self._next_labels:  dict[str, QLabel]   = {}

        for row, (display, key_s, _base_attr, _gb_attr) in enumerate(_STATS, start=1):
            name_lbl = QLabel(display)
            name_lbl.setObjectName("stat_row_label")
            grid.addWidget(name_lbl, row, 0)

            base_spin = NoWheelSpin()
            base_spin.setRange(1, 99)
            base_spin.setValue(1)
            base_spin.setFixedWidth(58)
            self._base_spins[key_s] = base_spin
            grid.addWidget(base_spin, row, 1)

            plus_lbl = QLabel("+")
            plus_lbl.setObjectName("stat_operator")
            grid.addWidget(plus_lbl, row, 2)

            bonus_lbl = QLabel("0")
            bonus_lbl.setObjectName("stat_bonus_auto")
            bonus_lbl.setFixedWidth(65)
            bonus_lbl.setToolTip("No bonuses")
            self._bonus_labels[key_s] = bonus_lbl
            grid.addWidget(bonus_lbl, row, 3)

            eq_lbl = QLabel("=")
            eq_lbl.setObjectName("stat_operator")
            grid.addWidget(eq_lbl, row, 4)

            total_lbl = QLabel("1")
            total_lbl.setObjectName("stat_total")
            total_lbl.setFixedWidth(38)
            self._total_labels[key_s] = total_lbl
            grid.addWidget(total_lbl, row, 5)

            next_lbl = QLabel("2")
            next_lbl.setObjectName("stat_next_cost")
            next_lbl.setFixedWidth(30)
            next_lbl.setToolTip("Stat points to raise this stat by 1")
            self._next_labels[key_s] = next_lbl
            grid.addWidget(next_lbl, row, 6)

            base_spin.valueChanged.connect(self._on_stat_changed)

        left_vbox.addWidget(grid_widget)

        bonus_header = QLabel("— Flat Bonuses —")
        bonus_header.setObjectName("stat_sub_header")
        left_vbox.addWidget(bonus_header)

        flat_grid_widget = QWidget()
        flat_grid = QGridLayout(flat_grid_widget)
        flat_grid.setContentsMargins(0, 0, 0, 0)
        flat_grid.setHorizontalSpacing(6)
        flat_grid.setVerticalSpacing(3)

        self._flat_labels: dict[str, QLabel] = {}
        cols_per_row = 4

        for i, (display, key_s, _gb_attr, _ai_key) in enumerate(_FLAT_BONUSES):
            row = i // (cols_per_row // 2)
            col_base = (i % (cols_per_row // 2)) * 2

            lbl = QLabel(display + ":")
            lbl.setObjectName("flat_bonus_label")
            flat_grid.addWidget(lbl, row, col_base)

            val_lbl = QLabel("0")
            val_lbl.setObjectName("stat_bonus_auto")
            val_lbl.setFixedWidth(65)
            val_lbl.setToolTip("No bonuses")
            self._flat_labels[key_s] = val_lbl
            flat_grid.addWidget(val_lbl, row, col_base + 1)

        left_vbox.addWidget(flat_grid_widget)
        left_vbox.addStretch()

        # ── Right: derived stats ──────────────────────────────────────────
        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(4, 0, 0, 0)
        right_vbox.setSpacing(4)

        derived_grid_widget = QWidget()
        derived_grid = QGridLayout(derived_grid_widget)
        derived_grid.setContentsMargins(0, 0, 0, 0)
        derived_grid.setHorizontalSpacing(10)
        derived_grid.setVerticalSpacing(3)

        for row_i, (display, key_s, default) in enumerate(_DERIVED_ROWS):
            name_lbl = QLabel(display)
            name_lbl.setObjectName("derived_stat_label")
            derived_grid.addWidget(name_lbl, row_i, 0)
            self._row_name_labels[key_s] = name_lbl

            val_lbl = QLabel(default)
            val_lbl.setObjectName("derived_stat_value")
            self._value_labels[key_s] = val_lbl
            derived_grid.addWidget(val_lbl, row_i, 1)

            if key_s in self._optional_rows:
                name_lbl.setVisible(False)
                val_lbl.setVisible(False)

        right_vbox.addWidget(derived_grid_widget)
        right_vbox.addStretch()

        # ── Horizontal container ──────────────────────────────────────────
        h_container = QWidget()
        h_layout = QHBoxLayout(h_container)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)
        h_layout.addWidget(left)
        h_layout.addWidget(right)

        self.add_content_widget(h_container)

    # ── Internal ──────────────────────────────────────────────────────────

    def _on_stat_changed(self) -> None:
        self._update_totals()
        self.stats_changed.emit()

    def _update_totals(self) -> None:
        spent = 0
        for key_s in self._base_spins:
            base = self._base_spins[key_s].value()
            bonus = self._bonus_values.get(key_s, 0)
            self._total_labels[key_s].setText(str(base + bonus))
            self._next_labels[key_s].setText(str(_stat_cost(base)))
            spent += _spent_points(base)
        available = loader.get_stat_points_at_level(self._base_level, self._job_id)
        remaining = available - spent
        self._points_label.setText(
            f"Stat Points — Spent: {spent} / {available}  |  Left: {remaining}"
        )
        if self._compact_widget is not None:
            self._update_compact_labels()

    def _update_compact_labels(self) -> None:
        for display, key_s, *_ in _STATS:
            lbl = self._compact_labels.get(key_s)
            if lbl is not None:
                base = self._base_spins[key_s].value()
                bonus = self._bonus_values.get(key_s, 0)
                lbl.setText(f"{display}: {base}+{bonus}" if bonus else f"{display}: {base}")

    def _build_compact_widget(self) -> None:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # Stats mini-grid (2 rows × 3 cols)
        stats_grid_w = QWidget()
        grid = QGridLayout(stats_grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for i, (display, key_s, *_) in enumerate(_STATS):
            row = i // 3
            col = i % 3
            lbl = QLabel()
            lbl.setObjectName("compact_stat_label")
            self._compact_labels[key_s] = lbl
            grid.addWidget(lbl, row, col)
        outer.addWidget(stats_grid_w)

        # Derived mini-row (BATK / DEF / FLEE / HIT / CRI)
        derived_w = QWidget()
        d_layout = QHBoxLayout(derived_w)
        d_layout.setContentsMargins(0, 0, 0, 0)
        d_layout.setSpacing(8)
        for key_s, display in [("batk", "BATK"), ("def", "DEF"), ("flee", "FLEE"),
                                ("hit", "HIT"), ("cri", "CRI")]:
            name_lbl = QLabel(display + ":")
            name_lbl.setObjectName("derived_stat_label")
            d_layout.addWidget(name_lbl)
            val_lbl = QLabel("—")
            val_lbl.setObjectName("derived_stat_value")
            self._derived_compact_values[key_s] = val_lbl
            d_layout.addWidget(val_lbl)
        d_layout.addStretch()
        outer.addWidget(derived_w)

        w.setVisible(False)
        self._compact_widget = w
        self.layout().addWidget(w)
        self._update_compact_labels()

    # ── Compact API ────────────────────────────────────────────────────────

    def _enter_slim(self) -> None:
        if self._compact_widget is None:
            self._build_compact_widget()
        self._update_compact_labels()
        for key_s, clbl in self._derived_compact_values.items():
            full_lbl = self._value_labels.get(key_s)
            if full_lbl:
                clbl.setText(full_lbl.text())
        self._compact_widget.setVisible(True)

    def _exit_slim(self) -> None:
        if self._compact_widget is not None:
            self._compact_widget.setVisible(False)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(
        self,
        status: StatusData,
        atk_ele: int | None = None,
        def_ele: int | None = None,
        profile: ServerProfile = STANDARD,
    ) -> None:
        """Push StatusCalculator output to the derived stats pane."""
        cri_pct = status.cri / 10.0
        self._value_labels["batk"].setText(str(status.batk))
        self._value_labels["matk"].setText(f"{status.matk_min}–{status.matk_max}")
        self._value_labels["def"].setText(f"{status.def_} + {status.def2}")
        self._value_labels["mdef"].setText(f"{status.mdef} + {status.mdef2}")
        flee_str = str(status.flee)
        if status.flee2:
            flee_str += f" + {status.flee2 / 10.0:.1f}%"
        self._value_labels["flee"].setText(flee_str)
        self._value_labels["hit"].setText(str(status.hit))
        self._value_labels["cri"].setText(f"{cri_pct:.1f}%")
        self._value_labels["aspd"].setText(f"{status.aspd:.1f}")
        self._value_labels["atk_ele"].setText(
            loader.get_element_name(atk_ele) if atk_ele is not None else "—"
        )
        self._value_labels["def_ele"].setText(
            loader.get_element_name(def_ele) if def_ele is not None else "—"
        )
        self._value_labels["hp"].setText(str(status.max_hp))
        self._value_labels["hp_regen"].setText(
            f"+{status.hp_regen} every {profile.tick_hp_stand}s"
        )
        self._value_labels["sp"].setText(str(status.max_sp))
        self._value_labels["sp_regen"].setText(
            f"+{status.sp_regen} every {profile.tick_sp_stand}s"
        )
        self._set_optional("cast_red", status.cast_time_reduction_pct,
                           f"{status.cast_time_reduction_pct}%")
        self._set_optional("acd_red", status.after_cast_delay_reduction_pct,
                           f"{status.after_cast_delay_reduction_pct}%")
        self._set_optional("sp_cost_red", status.sp_cost_reduction_pct,
                           f"{status.sp_cost_reduction_pct}%")
        # Sync derived compact values if slim widget is live
        for key_s, clbl in self._derived_compact_values.items():
            full_lbl = self._value_labels.get(key_s)
            if full_lbl:
                clbl.setText(full_lbl.text())

    def _set_optional(self, key_s: str, value: int, text: str) -> None:
        visible = value != 0
        self._row_name_labels[key_s].setVisible(visible)
        lbl = self._value_labels[key_s]
        lbl.setVisible(visible)
        if visible:
            lbl.setText(text)

    def update_from_bonuses(
        self,
        gb: GearBonuses,
        ai: dict[str, int],
        ma: dict[str, int],
        sc: dict[str, int] | None = None,
        jb: dict[str, int] | None = None,
        sc_flat: dict[str, int] | None = None,
        base_level: int = 1,
        job_id: int = 0,
    ) -> None:
        """Refresh auto-computed bonus labels from all sources.

        sc: comprehensive non-gear/job/ai/manual stat bonuses (party buffs, self buffs,
            passives, consumable foods, debuff penalties) — computed from StatusCalculator
            output difference so the total always matches the actual calculated stat.
        sc_flat: SC/passive/consumable contributions to flat bonus rows (batk/hit/flee/etc).
        """
        if sc is None:
            sc = {}
        if jb is None:
            jb = {}
        if sc_flat is None:
            sc_flat = {}
        self._base_level = base_level
        self._job_id = job_id
        for _display, key_s, _base_attr, gb_attr in _STATS:
            gear_val = int(getattr(gb, gb_attr, 0)) if gb_attr else 0
            ai_val   = ai.get(key_s, 0)
            ma_val   = ma.get(key_s, 0)
            sc_val   = sc.get(key_s, 0)
            jb_val   = jb.get(gb_attr, 0)  # gb_attr = "str_"/"int_"/etc.
            total    = gear_val + ai_val + ma_val + sc_val + jb_val
            self._bonus_values[key_s] = total
            lbl = self._bonus_labels[key_s]
            lbl.setText(_fmt_bonus(total) if total else "0")
            lbl.setToolTip(_make_tooltip(gear_val, ai_val, ma_val, sc_val, jb_val))

        for _display, key_s, gb_attr, ai_key in _FLAT_BONUSES:
            gear_val = int(getattr(gb, gb_attr, 0)) if gb_attr else 0
            ai_val   = ai.get(ai_key, 0)
            ma_val   = ma.get(ai_key, 0)
            sc_val   = sc_flat.get(key_s, 0)
            total    = gear_val + ai_val + ma_val + sc_val
            self._flat_values[key_s] = total
            lbl = self._flat_labels[key_s]
            lbl.setText(_fmt_bonus(total) if total else "0")
            lbl.setToolTip(_make_tooltip(gear_val, ai_val, ma_val, sc=sc_val))

        self._update_totals()

    def load_build(self, build: PlayerBuild) -> None:
        """Populate base stat spinboxes from build. Bonus column is auto-computed."""
        for spin in self._base_spins.values():
            spin.blockSignals(True)

        self._base_spins["str"].setValue(build.base_str)
        self._base_spins["agi"].setValue(build.base_agi)
        self._base_spins["vit"].setValue(build.base_vit)
        self._base_spins["int"].setValue(build.base_int)
        self._base_spins["dex"].setValue(build.base_dex)
        self._base_spins["luk"].setValue(build.base_luk)

        for spin in self._base_spins.values():
            spin.blockSignals(False)
        self._update_totals()

    def collect_into(self, build: PlayerBuild) -> None:
        """Write base stats into build. Bonus fields are computed in _apply_gear_bonuses."""
        build.base_str = self._base_spins["str"].value()
        build.base_agi = self._base_spins["agi"].value()
        build.base_vit = self._base_spins["vit"].value()
        build.base_int = self._base_spins["int"].value()
        build.base_dex = self._base_spins["dex"].value()
        build.base_luk = self._base_spins["luk"].value()
