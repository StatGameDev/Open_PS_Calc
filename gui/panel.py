"""
Panel — scrollable container for an ordered list of Section widgets.

The combat panel adds a StepsBar sidebar via an inner QSplitter.
The builder panel uses a plain QScrollArea with no splitter overhead.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.models.damage import BattleResult
from gui.section import Section

class _ClippingScrollArea(QScrollArea):
    """
    QScrollArea whose minimum width is always zero, regardless of content.

    With ScrollBarAlwaysOff horizontal and setWidgetResizable(True), content
    already fills the viewport at any width. The default QScrollArea propagates
    the widget's minimumSizeHint upward, which forces the splitter wider whenever
    a section with long combo text is expanded. This subclass breaks that chain.
    """

    def minimumSizeHint(self) -> QSize:
        h = super().minimumSizeHint()
        return QSize(0, h.height())


# Width of the narrow collapsed bar (px)
_BAR_W = 22
# Width of the expanded step list including the bar (px)
_EXPANDED_W = 220

# _VerticalBarLabel paint colors — cannot be controlled via QSS (custom paintEvent)
_COLOR_BAR_BG   = QColor("#252830")   # bar background fill
_COLOR_BAR_TEXT = QColor("#6a7383")   # "Steps ▶/◀" label text


class _VerticalBarLabel(QWidget):
    """Narrow 22px strip with rotated 'Steps ▶/◀' label drawn via QPainter."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self.setFixedWidth(_BAR_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setToolTip("Toggle step list")

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), _COLOR_BAR_BG)
        p.save()
        p.translate(_BAR_W // 2, self.height() // 2)
        p.rotate(-90)
        import gui.app_config as app_config
        p.setFont(app_config.make_font(12))
        p.setPen(_COLOR_BAR_TEXT)
        arrow = "◀" if self._expanded else "▶"
        text = f"Steps  {arrow}"
        fm = p.fontMetrics()
        br = fm.boundingRect(text)
        p.drawText(-br.width() // 2, br.height() // 3, text)
        p.restore()


class StepsBar(QWidget):
    """
    Vertical sidebar for the compact combat panel.
    Layout: [bar (left, always visible)] [step list scroll (right, toggle)].

    The bar acts as a visual divider between the sections QScrollArea and the
    step list. Expanding/collapsing is delegated to Panel via signals so that
    the Panel's inner QSplitter can handle the resize reliably.
    """

    expand_requested = Signal()
    collapse_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self.setVisible(False)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Bar on LEFT — acts as divider between sections and step list
        self._bar = _VerticalBarLabel()
        self._bar.clicked.connect(self._on_bar_clicked)
        h.addWidget(self._bar)

        # Step list on RIGHT — hidden until expanded
        self._rows_inner = QWidget()
        self._rows_inner.setObjectName("panel_inner")
        self._rows_layout = QVBoxLayout(self._rows_inner)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._rows_inner)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVisible(False)
        h.addWidget(self._scroll, stretch=1)

    # ── Toggle ─────────────────────────────────────────────────────────────

    def _on_bar_clicked(self) -> None:
        if self._expanded:
            self._expanded = False
            self._scroll.setVisible(False)
            self._bar.set_expanded(False)
            self.collapse_requested.emit()
        else:
            self._expanded = True
            self._scroll.setVisible(True)
            self._bar.set_expanded(True)
            self.expand_requested.emit()

    # ── Public API ─────────────────────────────────────────────────────────

    def set_visible_bar(self, visible: bool) -> None:
        """Called by PanelContainer (gui/panel_container.py) on focus state changes."""
        if not visible and self._expanded:
            self._expanded = False
            self._scroll.setVisible(False)
            self._bar.set_expanded(False)
        self.setVisible(visible)

    def set_expanded_state(self, expanded: bool) -> None:
        """Programmatically set internal expanded state without emitting signals."""
        self._expanded = expanded
        self._scroll.setVisible(expanded)
        self._bar.set_expanded(expanded)

    def refresh(self, result: Optional[BattleResult]) -> None:
        """Rebuild step rows from BattleResult (wired to result_updated)."""
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if result is None:
            return
        for i, step in enumerate(result.normal.steps):
            row_w = QWidget()
            row_w.setProperty("alt_row", str(i % 2 == 1).lower())
            row_layout = QHBoxLayout(row_w)
            row_layout.setContentsMargins(6, 2, 6, 2)

            name_lbl = QLabel(step.name)
            name_lbl.setObjectName("compact_step_name")
            val_lbl = QLabel(str(step.value))
            val_lbl.setObjectName("compact_step_val")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            row_layout.addWidget(name_lbl)
            row_layout.addWidget(val_lbl)
            self._rows_layout.insertWidget(i, row_w)

            # per-row tooltip from DamageStep fields
            if step.min_value != step.max_value:
                output_str = f"Range: {step.min_value} – {step.max_value}  (avg {step.value})"
            else:
                output_str = f"Value: {step.value}"
            tooltip = (
                f"<b>{step.name}</b><br>"
                f"<br>"
                f"Formula: {step.formula}<br>"
                f"Output: {output_str}<br>"
                f"<br>"
                f"Source: {step.hercules_ref}"
            )
            row_w.setToolTip(tooltip)


class Panel(QWidget):
    """
    Container for an ordered list of Section widgets.

    The combat panel adds a StepsBar via an inner QSplitter so that expanding
    the steps list reliably pushes the sections QScrollArea to the left.
    The builder panel uses a plain QScrollArea with no splitter overhead.
    """

    # Forwarded from StepsBar so PanelContainer (gui/panel_container.py) can nudge the outer splitter.
    steps_expand_requested = Signal()
    steps_collapse_requested = Signal()

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName(f"panel_{name}")

        self._steps_bar: Optional[StepsBar] = None
        self._inner_splitter: Optional[QSplitter] = None
        self._steps_was_expanded: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scrollable sections area ──────────────────────────────────────
        self._scroll = _ClippingScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setObjectName(f"panel_scroll_{name}")

        self._inner = QWidget()
        self._inner.setObjectName("panel_inner")
        self._inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch()

        self._scroll.setWidget(self._inner)

        if name == "combat":
            # Inner QSplitter handles sections ↔ steps resize reliably
            self._inner_splitter = QSplitter(Qt.Orientation.Horizontal)
            self._inner_splitter.setHandleWidth(1)
            self._inner_splitter.setChildrenCollapsible(False)
            self._inner_splitter.addWidget(self._scroll)

            self._steps_bar = StepsBar()
            self._steps_bar.expand_requested.connect(self._on_steps_expand)
            self._steps_bar.expand_requested.connect(self.steps_expand_requested)
            self._steps_bar.collapse_requested.connect(self._on_steps_collapse)
            self._steps_bar.collapse_requested.connect(self.steps_collapse_requested)
            self._inner_splitter.addWidget(self._steps_bar)

            outer.addWidget(self._inner_splitter)
        else:
            outer.addWidget(self._scroll)

    # ── Steps expand/collapse (combat panel only) ─────────────────────────

    def _on_steps_expand(self) -> None:
        if self._inner_splitter is None:
            return
        total = sum(self._inner_splitter.sizes())
        self._inner_splitter.setSizes([max(0, total - _EXPANDED_W), _EXPANDED_W])

    def _on_steps_collapse(self) -> None:
        if self._inner_splitter is None:
            return
        total = sum(self._inner_splitter.sizes())
        self._inner_splitter.setSizes([total - _BAR_W, _BAR_W])

    def reset_steps_to_collapsed(self) -> None:
        """Set inner splitter to collapsed state (bar only, no step list)."""
        if self._inner_splitter is None:
            return
        total = sum(self._inner_splitter.sizes())
        if total > 0:
            self._inner_splitter.setSizes([total - _BAR_W, _BAR_W])

    def set_steps_bar_visible(self, show: bool) -> None:
        """Show/hide the steps sidebar, persisting expanded state across focus switches."""
        if self._steps_bar is None:
            return
        if not show:
            self._steps_was_expanded = self._steps_bar._expanded
            self._steps_bar.set_visible_bar(False)
        else:
            self._steps_bar.set_visible_bar(True)
            if self._steps_was_expanded:
                self._steps_bar.set_expanded_state(True)  # restore internal state first
                QTimer.singleShot(0, self._on_steps_expand)  # then fix splitter sizes
            else:
                QTimer.singleShot(0, self.reset_steps_to_collapsed)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def steps_bar(self) -> Optional[StepsBar]:
        return self._steps_bar

    # ── Section management ────────────────────────────────────────────────

    def add_section(self, section: Section) -> None:
        """Insert section before the trailing QSpacerItem."""
        idx = self._layout.count() - 1
        self._layout.insertWidget(idx, section)

    def add_section_row(self, sections: list[Section]) -> None:
        """Insert multiple sections side-by-side before the trailing QSpacerItem."""
        from gui.widgets.layout_helpers import make_side_by_side_row
        idx = self._layout.count() - 1
        self._layout.insertWidget(idx, make_side_by_side_row(sections))
