"""layout_helpers — Shared layout factory helpers.

Use make_field_grid() for any new section that has label + value rows. It pre-configures
the grid so that label columns absorb spare horizontal space and value columns stay at
their natural width, with consistent margins and spacing matching the rest of the UI.

Use make_side_by_side_row() anywhere two or more widgets should sit side-by-side and
top-aligned — works at panel level (Section rows), inside sections (CollapsibleSubGroup
rows), or anywhere else in the widget tree.
"""
from __future__ import annotations

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget


class _ProportionalRow(QWidget):
    """Row widget that sets column stretch proportional to sizeHints on first show.

    Used by make_side_by_side_row(equal_width=False). Columns are added with
    stretch=0 initially; showEvent reads each column's sizeHint and sets
    horizontalStretch on its policy so remaining space is distributed in
    proportion to content width. This happens before the first paint.
    """

    def __init__(self, cols: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cols = cols
        self._proportions_set = False

    def showEvent(self, event: QShowEvent) -> None:
        if not self._proportions_set:
            self._proportions_set = True
            hints = [max(c.sizeHint().width(), 1) for c in self._cols]
            for col, hint in zip(self._cols, hints):
                policy = col.sizePolicy()
                policy.setHorizontalStretch(hint)
                col.setSizePolicy(policy)
        super().showEvent(event)


def make_side_by_side_row(widgets: list[QWidget], *, equal_width: bool = True) -> QWidget:
    """Return a QWidget containing *widgets* laid out side-by-side and top-aligned.

    Each widget is wrapped in a column widget with a trailing stretch so that
    widgets of different heights stay top-aligned rather than stretching to fill
    the tallest neighbour's height.

    equal_width=True  (default) — all columns share available width equally
                                   (stretch=1 each). Use for section-level rows
                                   where uniform column widths are wanted.
    equal_width=False           — columns are sized proportionally to their content.
                                   On first show, each column's sizeHint width is read
                                   and used as its horizontalStretch factor so the row
                                   fills available width with proportional distribution.
                                   Adds 8px spacing between columns automatically.

    Works at any level of the widget tree::

        # Equal-width section row (default):
        section.add_content_widget(make_side_by_side_row([grp_a, grp_b]))

        # Proportional-width columns (e.g. mixed checkbox/levelled groups):
        section.add_content_widget(make_side_by_side_row([a, b, c], equal_width=False))
    """
    cols: list[QWidget] = []
    if equal_width:
        row = QWidget()
    else:
        row = _ProportionalRow([])  # cols list filled below

    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8 if not equal_width else 0)

    for w in widgets:
        col = QWidget()
        col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col_layout = QVBoxLayout(col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)
        col_layout.addWidget(w)
        col_layout.addStretch()
        row_layout.addWidget(col, stretch=1 if equal_width else 0)
        cols.append(col)

    if not equal_width:
        row._cols = cols  # type: ignore[attr-defined]

    return row


def make_field_grid() -> QGridLayout:
    """Return a QGridLayout pre-configured for a single label+value column pair.

    Column 0 (label) stretches to absorb spare width; value widget sits at the
    right edge. Use this in full-width contexts (stats, equipment, etc.).

    For sections with two side-by-side label+value pairs (e.g. passives), call this
    and additionally set ``grid.setColumnStretch(2, 1)`` for the second label column.

    For compact/two-column layouts where value widgets should sit immediately
    after their labels, use ``grid.setColumnStretch(2, 1)`` instead of the
    default ``setColumnStretch(0, 1)`` — an empty col 2 absorbs spare width
    while cols 0 and 1 stay at natural size.

    Usage::

        grid = make_field_grid()
        grid.addWidget(QLabel("STR"), 0, 0)
        grid.addWidget(str_spin, 0, 1)
    """
    g = QGridLayout()
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(6)
    g.setVerticalSpacing(3)
    g.setColumnStretch(0, 1)
    return g
