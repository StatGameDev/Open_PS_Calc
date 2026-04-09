"""
SummarySection — damage summary card showing normal, crit, proc, hit%, and DPS.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from core.calculators.proc_keys import PROC_AUTO_BLITZ, PROC_AUTOSPELL
from core.models.damage import BattleResult
from gui.section import Section

_PROC_DISPLAY_NAMES: dict[str, str] = {
    PROC_AUTO_BLITZ: "Auto Blitz",
    PROC_AUTOSPELL:  "Autocast",
}

_DASH = "—"


class SummarySection(Section):
    """Damage summary card (normal range, crit range, hit%)."""

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)

        for col, text in enumerate(("", "Min", "Avg", "Max"), start=0):
            hdr = QLabel(text)
            hdr.setObjectName("summary_col_header")
            hdr.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(hdr, 0, col)

        normal_lbl = QLabel("Normal")
        normal_lbl.setObjectName("summary_label")
        grid.addWidget(normal_lbl, 1, 0)

        self._n_min = self._make_val()
        self._n_avg = self._make_val()
        self._n_max = self._make_val()
        grid.addWidget(self._n_min, 1, 1)
        grid.addWidget(self._n_avg, 1, 2)
        grid.addWidget(self._n_max, 1, 3)

        crit_lbl = QLabel("Crit")
        crit_lbl.setObjectName("summary_label")
        grid.addWidget(crit_lbl, 2, 0)

        self._c_min = self._make_val()
        self._c_avg = self._make_val()
        self._c_max = self._make_val()
        grid.addWidget(self._c_min, 2, 1)
        grid.addWidget(self._c_avg, 2, 2)
        grid.addWidget(self._c_max, 2, 3)

        self._crit_pct = QLabel(_DASH)
        self._crit_pct.setObjectName("summary_crit_pct")
        self._crit_pct.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._crit_pct, 2, 4)

        # Double-hit proc row — hidden until a proc branch is present
        self._double_lbl = QLabel("Double")
        self._double_lbl.setObjectName("summary_label")
        grid.addWidget(self._double_lbl, 3, 0)

        self._d_min = self._make_val()
        self._d_avg = self._make_val()
        self._d_max = self._make_val()
        grid.addWidget(self._d_min, 3, 1)
        grid.addWidget(self._d_avg, 3, 2)
        grid.addWidget(self._d_max, 3, 3)

        self._proc_pct = QLabel(_DASH)
        self._proc_pct.setObjectName("summary_crit_pct")
        self._proc_pct.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._proc_pct, 3, 4)

        self._double_row_widgets = [
            self._double_lbl, self._d_min, self._d_avg, self._d_max, self._proc_pct,
        ]
        for w in self._double_row_widgets:
            w.setVisible(False)

        # Proc branches container — dynamic rows, one per proc_branches key.
        # Cleared and rebuilt each refresh().
        self._proc_container = QWidget()
        self._proc_vbox_layout = QGridLayout(self._proc_container)
        self._proc_vbox_layout.setContentsMargins(0, 0, 0, 0)
        self._proc_vbox_layout.setHorizontalSpacing(10)
        self._proc_vbox_layout.setVerticalSpacing(2)
        self._proc_vbox_layout.setColumnStretch(5, 1)
        grid.addWidget(self._proc_container, 4, 0, 1, 5)
        self._proc_container.setVisible(False)

        hit_lbl = QLabel("Hit")
        hit_lbl.setObjectName("summary_label")
        grid.addWidget(hit_lbl, 5, 0)

        self._hit_pct = QLabel(_DASH)
        self._hit_pct.setObjectName("summary_hit_pct")
        grid.addWidget(self._hit_pct, 5, 1, 1, 2)

        self._pdodge_pct = QLabel(_DASH)
        self._pdodge_pct.setObjectName("summary_hit_pct")
        self._pdodge_pct.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._pdodge_pct, 5, 3, 1, 2)

        # DPS row — shows "N/A" when dps_valid is False
        dps_lbl = QLabel("DPS")
        dps_lbl.setObjectName("summary_label")
        grid.addWidget(dps_lbl, 6, 0)

        self._dps_val = QLabel(_DASH)
        self._dps_val.setObjectName("summary_value")
        self._dps_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._dps_val, 6, 1, 1, 3)

        # Speed row — actions per second (= 1000 / period_ms).
        # More intuitive than raw period_ms: higher = faster attacking/casting.
        spd_lbl = QLabel("Attack Speed")
        spd_lbl.setObjectName("summary_label")
        grid.addWidget(spd_lbl, 7, 0)

        self._spd_val = QLabel(_DASH)
        self._spd_val.setObjectName("summary_value")
        self._spd_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._spd_val, 7, 1, 1, 3)

        grid.setColumnStretch(5, 1)

        container = QWidget()
        container.setLayout(grid)
        self.add_content_widget(container)

    @staticmethod
    def _make_val() -> QLabel:
        lbl = QLabel(_DASH)
        lbl.setObjectName("summary_value")
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return lbl

    # ── Public API ────────────────────────────────────────────────────────

    def _clear_proc_rows(self) -> None:
        """Remove all dynamically added proc branch rows."""
        layout = self._proc_vbox_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._proc_container.setVisible(False)

    def refresh(self, result: Optional[BattleResult]) -> None:
        if result is None:
            self._n_min.setText(_DASH)
            self._n_avg.setText(_DASH)
            self._n_max.setText(_DASH)
            self._c_min.setText(_DASH)
            self._c_avg.setText(_DASH)
            self._c_max.setText(_DASH)
            self._crit_pct.setText(_DASH)
            for w in self._double_row_widgets:
                w.setVisible(False)
            self._clear_proc_rows()
            self._hit_pct.setText(_DASH)
            self._pdodge_pct.setText(_DASH)
            self._dps_val.setText(_DASH)
            self._spd_val.setText(_DASH)
            return

        n = result.normal
        # Katar second hit — show "first + second" when present.
        # Dual-wield — show "rh + lh" when LH branch present.
        if result.katar_second is not None:
            k = result.katar_second
            self._n_min.setText(f"{n.min_damage} + {k.min_damage}")
            self._n_avg.setText(f"{n.avg_damage} + {k.avg_damage}")
            self._n_max.setText(f"{n.max_damage} + {k.max_damage}")
        elif result.lh_normal is not None:
            lh = result.lh_normal
            self._n_min.setText(f"{n.min_damage} + {lh.min_damage}")
            self._n_avg.setText(f"{n.avg_damage} + {lh.avg_damage}")
            self._n_max.setText(f"{n.max_damage} + {lh.max_damage}")
        else:
            self._n_min.setText(str(n.min_damage))
            self._n_avg.setText(str(n.avg_damage))
            self._n_max.setText(str(n.max_damage))

        if result.crit is not None:
            c = result.crit
            if result.katar_second_crit is not None:
                kc = result.katar_second_crit
                self._c_min.setText(f"{c.min_damage} + {kc.min_damage}")
                self._c_avg.setText(f"{c.avg_damage} + {kc.avg_damage}")
                self._c_max.setText(f"{c.max_damage} + {kc.max_damage}")
            elif result.lh_crit is not None:
                lhc = result.lh_crit
                self._c_min.setText(f"{c.min_damage} + {lhc.min_damage}")
                self._c_avg.setText(f"{c.avg_damage} + {lhc.avg_damage}")
                self._c_max.setText(f"{c.max_damage} + {lhc.max_damage}")
            else:
                self._c_min.setText(str(c.min_damage))
                self._c_avg.setText(str(c.avg_damage))
                self._c_max.setText(str(c.max_damage))
            # Effective crit%: crit and proc are mutually exclusive (battle.c:4926).
            eff_crit = result.crit_chance * (1.0 - result.proc_chance / 100.0)
            self._crit_pct.setText(f"{eff_crit:.1f}% crit")
        else:
            self._c_min.setText(_DASH)
            self._c_avg.setText(_DASH)
            self._c_max.setText(_DASH)
            self._crit_pct.setText("—")

        # Proc branch rows — rebuilt dynamically from result.proc_branches.
        self._clear_proc_rows()
        if result.proc_branches:
            self._proc_container.setVisible(True)
            layout = self._proc_vbox_layout
            for row_idx, (key, dr) in enumerate(result.proc_branches.items()):
                chance = result.proc_chances.get(key, 0.0)
                display = (result.proc_labels.get(key)
                           or _PROC_DISPLAY_NAMES.get(key, key.replace("_", " ").title()))
                lbl = QLabel(display)
                lbl.setObjectName("summary_label")
                v_min = self._make_val()
                v_avg = self._make_val()
                v_max = self._make_val()
                pct   = QLabel(f"{chance:.1f}% proc" if chance < 100.0 else "")
                pct.setObjectName("summary_crit_pct")
                pct.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                v_min.setText(str(dr.min_damage))
                v_avg.setText(str(dr.avg_damage))
                v_max.setText(str(dr.max_damage))
                layout.addWidget(lbl,   row_idx, 0)
                layout.addWidget(v_min, row_idx, 1)
                layout.addWidget(v_avg, row_idx, 2)
                layout.addWidget(v_max, row_idx, 3)
                layout.addWidget(pct,   row_idx, 4)

        # Double-hit proc row — show only when proc branch is present.
        # When dual-wielding, proc doubles RH only; LH contributes its normal value.
        # Show "RH×2 + LH" split to match the Normal row's "rh + lh" pattern.
        if result.double_hit is not None:
            d = result.double_hit
            if result.lh_normal is not None:
                lhd = result.lh_normal
                self._d_min.setText(f"{d.min_damage} + {lhd.min_damage}")
                self._d_avg.setText(f"{d.avg_damage} + {lhd.avg_damage}")
                self._d_max.setText(f"{d.max_damage} + {lhd.max_damage}")
            else:
                self._d_min.setText(str(d.min_damage))
                self._d_avg.setText(str(d.avg_damage))
                self._d_max.setText(str(d.max_damage))
            self._proc_pct.setText(f"{result.proc_chance:.1f}% proc")
            for w in self._double_row_widgets:
                w.setVisible(True)
        else:
            for w in self._double_row_widgets:
                w.setVisible(False)

        self._hit_pct.setText(f"{result.hit_chance:.1f}%")
        self._pdodge_pct.setText(f"pdodge {result.perfect_dodge:.1f}%")

        # DPS — shows "N/A" when dps_valid is False.
        if result.dps_valid:
            self._dps_val.setText(f"{result.dps:.1f}")
        else:
            self._dps_val.setText("N/A")

        # Speed — actions per second (= 1000 / period_ms).
        # Shows how fast the player can repeat the current attack/skill.
        if result.period_ms > 0:
            self._spd_val.setText(f"{1000.0 / result.period_ms:.2f}/s")
        else:
            self._spd_val.setText(_DASH)
