"""
collapsible_sub_group — CollapsibleSubGroup widget.

A collapsible sub-section for use inside a Section's content frame.
Not a Section itself — does not participate in compact_mode or PanelContainer snap.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _ClickableFrame(QFrame):
    """QFrame with a mouse-press signal."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._callback = None

    def set_click_callback(self, fn) -> None:
        self._callback = fn

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._callback:
            self._callback()
        super().mousePressEvent(event)


class CollapsibleSubGroup(QWidget):
    """
    Collapsible sub-section for use inside a Section's content frame.
    NOT a Section itself — does not participate in compact_mode or PanelContainer snap.

    Usage:
        grp = CollapsibleSubGroup("Party Buffs", default_collapsed=False)
        grp.add_content_widget(some_widget)
        section.add_content_widget(grp)
    """

    def __init__(
        self,
        title: str,
        default_collapsed: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._is_collapsed = default_collapsed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        self._header = _ClickableFrame()
        self._header.setObjectName("subgroup_header")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._header.set_click_callback(self.toggle)

        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(6, 3, 6, 3)
        h_layout.setSpacing(6)

        self._arrow = QLabel("▶" if default_collapsed else "▼")
        self._arrow.setObjectName("subgroup_arrow")
        self._arrow.setFixedWidth(12)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("subgroup_title")

        h_layout.addWidget(self._arrow)
        h_layout.addWidget(self._title_lbl)
        h_layout.addStretch()

        # ── Content ───────────────────────────────────────────────────────
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 4, 4, 4)
        self._content_layout.setSpacing(4)
        self._content.setVisible(not default_collapsed)

        root.addWidget(self._header)
        root.addWidget(self._content)

    # ── Public API ─────────────────────────────────────────────────────────

    def add_content_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def add_header_widget(self, widget: QWidget) -> None:
        """Insert a widget into the header row (before the stretch)."""
        layout = self._header.layout()
        layout.insertWidget(layout.count() - 1, widget)

    def toggle(self) -> None:
        self._is_collapsed = not self._is_collapsed
        self._content.setVisible(not self._is_collapsed)
        self._arrow.setText("▶" if self._is_collapsed else "▼")

    def set_collapsed(self, collapsed: bool) -> None:
        if self._is_collapsed == collapsed:
            return
        self._is_collapsed = collapsed
        self._content.setVisible(not collapsed)
        self._arrow.setText("▶" if collapsed else "▼")

    @property
    def is_collapsed(self) -> bool:
        return self._is_collapsed

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout
