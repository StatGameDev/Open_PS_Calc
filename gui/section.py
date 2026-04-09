"""
Section — base class for all collapsible GUI panel sections.

Handles collapse/expand, slim-mode transitions (hidden / header_summary / slim_content),
and the header bar with arrow and optional summary label. Subclasses implement content
layout and override _enter_slim() / _exit_slim() for compact views.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _ClickableFrame(QFrame):
    """QFrame that emits clicked() on left mouse press."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Section(QWidget):
    """
    Collapsible panel unit. All visibility changes go through this class.

    compact_modes (list[str], from layout_config.json) — independent flags:

      "slim_content"    — section has a compact widget for slim panels; when the
                          panel is slim, toggle between collapsed and the compact
                          widget (full content never shown in slim mode).
                          Subclasses override _enter_slim() / _exit_slim().

      "header_summary"  — an always-visible summary label is added to the header.
                          Call set_header_summary(text) to update it. When the
                          panel is slim and no slim_content exists, the section
                          auto-collapses (header text stays readable).

      "hidden"          — section is hidden entirely when panel is slim.

    Any combination is valid. Sections with neither flag are unaffected by slim mode.
    """

    collapsed_changed = Signal(bool)
    expand_requested = Signal()
    collapse_requested = Signal()

    def __init__(
        self,
        key: str,
        display_name: str,
        default_collapsed: bool,
        compact_modes: list[str] | str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._key = key
        self._display_name = display_name

        # Normalise — accept list (new) or legacy string (old layout_config)
        if isinstance(compact_modes, str):
            compact_modes = {
                "none": [],
                "hidden": ["hidden"],
                "collapsed": ["header_summary"],
                "compact_view": ["slim_content"],
            }.get(compact_modes, [])

        self._has_hidden         = "hidden"         in compact_modes
        self._has_header_summary = "header_summary" in compact_modes
        self._has_slim_content   = "slim_content"   in compact_modes

        self._is_collapsed = default_collapsed
        self._is_slim      = False
        self._pre_slim_collapsed: Optional[bool] = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        self._header = _ClickableFrame()
        self._header.setObjectName("section_header")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(8, 5, 8, 5)
        h_layout.setSpacing(6)

        self._arrow = QLabel("▶" if default_collapsed else "▼")
        self._arrow.setObjectName("section_arrow")
        self._arrow.setFixedWidth(12)

        self._title = QLabel(display_name)
        self._title.setObjectName("section_title")

        h_layout.addWidget(self._arrow)
        h_layout.addWidget(self._title)

        if self._has_header_summary:
            self._header_summary_lbl = QLabel("")
            self._header_summary_lbl.setObjectName("section_header_summary")
            self._header_summary_lbl.setWordWrap(True)
            self._header_summary_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h_layout.addWidget(self._header_summary_lbl)
        else:
            h_layout.addStretch()

        self._header.clicked.connect(self.toggle_collapse)

        # ── Content Frame (full) ───────────────────────────────────────────
        self._content_frame = QFrame()
        self._content_frame.setObjectName("section_content")
        self._content_layout = QVBoxLayout(self._content_frame)
        self._content_layout.setContentsMargins(10, 6, 10, 10)
        self._content_layout.setSpacing(4)
        self._content_frame.setVisible(not default_collapsed)

        root.addWidget(self._header)
        root.addWidget(self._content_frame)

    # ── Content API ────────────────────────────────────────────────────────

    def add_content_widget(self, widget: QWidget) -> None:
        """Append widget to the full-size content frame's layout."""
        self._content_layout.addWidget(widget)

    # ── Header Summary API ─────────────────────────────────────────────────

    def set_header_summary(self, text: str) -> None:
        """Update the always-visible summary label in the header."""
        if self._has_header_summary:
            self._header_summary_lbl.setText(text)

    # ── Collapse API ───────────────────────────────────────────────────────

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the section, respecting current slim state."""
        if self._is_collapsed == collapsed:
            return
        self._is_collapsed = collapsed
        self._arrow.setText("▶" if collapsed else "▼")

        if collapsed:
            self._content_frame.setVisible(False)
            if self._is_slim and self._has_slim_content:
                self._exit_slim()
        else:
            if self._is_slim and self._has_slim_content:
                self._enter_slim()
            else:
                self._content_frame.setVisible(True)

        self.collapsed_changed.emit(collapsed)

    def toggle_collapse(self) -> None:
        self.set_collapsed(not self._is_collapsed)

    # ── Slim Mode API ───────────────────────────────────────────────────────

    def set_slim_mode(self, slim: bool) -> None:
        """
        Called by PanelContainer when the owning panel enters or leaves slim mode.
        slim=True  → panel is narrow (e.g. builder panel in combat_focused state)
        slim=False → panel is at full width
        """
        if self._is_slim == slim:
            return
        self._is_slim = slim

        if self._has_hidden:
            self.setVisible(not slim)
            return

        if slim:
            if self._has_slim_content:
                if not self._is_collapsed:
                    # Currently showing full content → switch to slim content
                    self._content_frame.setVisible(False)
                    self._enter_slim()
            elif self._has_header_summary:
                # Collapse to header so the summary text is the only info shown
                self._pre_slim_collapsed = self._is_collapsed
                if not self._is_collapsed:
                    self._is_collapsed = True
                    self._content_frame.setVisible(False)
                    self._arrow.setText("▶")
        else:
            if self._has_slim_content:
                if not self._is_collapsed:
                    # Currently showing slim content → switch back to full content
                    self._exit_slim()
                    self._content_frame.setVisible(True)
            elif self._has_header_summary:
                if self._pre_slim_collapsed is not None:
                    was = self._pre_slim_collapsed
                    self._pre_slim_collapsed = None
                    if was != self._is_collapsed:
                        self._is_collapsed = was
                        self._content_frame.setVisible(not was)
                        self._arrow.setText("▶" if was else "▼")

    # ── Resize Hook ────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._on_width_changed(event.size().width())

    def _on_width_changed(self, width: int) -> None:
        """Called when the section's width changes. Override to reflow content."""
        pass

    # ── Slim Content Hooks (override in subclasses) ────────────────────────

    def _enter_slim(self) -> None:
        """
        Called when the section should display its slim content.
        Base fallback: show full content anyway (graceful degradation for stubs).
        Subclasses: build/update compact widget, make it visible; do NOT touch
        _content_frame, _is_collapsed, or _arrow — the base class owns those.
        """
        self._content_frame.setVisible(True)

    def _exit_slim(self) -> None:
        """
        Called when slim content should be hidden (section collapsing or exiting
        slim mode). Subclasses: hide their compact widget.
        """
        pass

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_collapsed(self) -> bool:
        return self._is_collapsed

    @property
    def key(self) -> str:
        return self._key
