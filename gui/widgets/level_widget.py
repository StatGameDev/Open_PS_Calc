"""
level_widget — Scroll-safe combo and spinbox widgets, plus LevelWidget.

NoWheelCombo / NoWheelSpin require a brief hover (0.15 s) before accepting
scroll-wheel input, preventing accidental value changes when the user scrolls
past the widget. NoScrollCombo disables wheel input entirely.

LevelWidget is a NoWheelCombo with a QSpinBox-compatible API (value/setValue/
valueChanged) used for skill level selectors throughout the GUI.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QComboBox, QSpinBox

_HOVER_DELAY = 0.15  # seconds of continuous hover before scroll wheel is accepted


class NoWheelCombo(QComboBox):
    """QComboBox that requires a brief hover before accepting scroll wheel input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hover_start: float | None = None
        self.setMaxVisibleItems(15)

    def enterEvent(self, event) -> None:
        self._hover_start = time.monotonic()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_start = None
        super().leaveEvent(event)

    def minimumSizeHint(self) -> QSize:
        h = super().minimumSizeHint()
        return QSize(0, h.height())

    def wheelEvent(self, event) -> None:
        if self._hover_start is not None and time.monotonic() - self._hover_start >= _HOVER_DELAY:
            # Invert direction so scroll-up = higher index (matches QSpinBox scroll-up = increment).
            step = 1 if event.angleDelta().y() > 0 else -1
            self.setCurrentIndex(max(0, min(self.currentIndex() + step, self.count() - 1)))
            event.accept()
        else:
            event.ignore()


class NoWheelSpin(QSpinBox):
    """QSpinBox that requires a brief hover before accepting scroll wheel input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hover_start: float | None = None

    def enterEvent(self, event) -> None:
        self._hover_start = time.monotonic()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_start = None
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        if self._hover_start is not None and time.monotonic() - self._hover_start >= _HOVER_DELAY:
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollCombo(QComboBox):
    """QComboBox that never reacts to the scroll wheel."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class LevelWidget(NoWheelCombo):
    """
    Dropdown level selector with QSpinBox-compatible API (value/setValue/valueChanged).
    Populates Off (optional, data=0) + 1..max_lv items.
    """

    valueChanged = Signal(int)

    def __init__(self, max_lv: int, include_off: bool = True, item_prefix: str = ""):
        super().__init__()
        self._include_off = include_off
        self._item_prefix = item_prefix
        self._populate(max_lv)
        self.currentIndexChanged.connect(lambda _: self.valueChanged.emit(self.value()))

    def _populate(self, max_lv: int) -> None:
        self.clear()
        if self._include_off:
            self.addItem("Off", 0)
        for lv in range(1, max_lv + 1):
            self.addItem(f"{self._item_prefix}{lv}", lv)

    def set_max(self, max_lv: int) -> None:
        """Rebuild items for 1..max_lv and reset to max_lv (new default).
        Manages its own signal blocking — do NOT call while signals are already blocked."""
        self.blockSignals(True)
        self._populate(max_lv)
        self.setValue(max_lv)
        self.blockSignals(False)

    def rebuild_max(self, max_lv: int) -> None:
        """Rebuild items for 1..max_lv without touching signal blocking.
        Use this when the caller has already blocked signals (e.g. inside load_build)."""
        self._populate(max_lv)

    def value(self) -> int:
        return self.currentData() or 0

    def setValue(self, v: int) -> None:
        idx = self.findData(v)
        self.setCurrentIndex(idx if idx >= 0 else 0)
