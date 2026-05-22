"""
InteractivePlot — a self-contained pg.PlotWidget with a draggable, snapping
InfiniteLine, scatter readout, and status bar.

Public API
----------
Construction:
    plot = InteractivePlot(data=None, guide_values=None, **pg_kwargs)

Properties (gettable and settable at runtime):
    plot.data         = (x_array, y_array)  # show / update line + curve
    plot.data         = None                # hide line, scatter, curve
    plot.guide_values  = array               # update Ctrl+arrow targets
    plot.guide_values  = None               # disable snap navigation
    plot.snap_line                          # read-only: the SnappingLine object

SnappingLine public API (via plot.snap_line):
    .has_data                   bool
    .selected                   bool
    .dragging                   bool
    .current_x()                float
    .current_y()                float
    .move_to_x(x_value)         move line to nearest data x to x_value
    .move_data(go_right)        step one data index left/right
    .move_snap(go_right)        jump to prev/next guide_values entry
    .select() / .deselect()
    .show() / .hide()           inherited from QGraphicsItem
    .sigPlotChanged             NOT present — use InteractivePlot.sigLineMoved
    (all pg.InfiniteLine methods also available)

Signal:
    plot.sigLineMoved(float x, float y)   emitted on every line movement

Controls (when data is loaded):
    Click line          → select (highlight yellow)
    Drag line           → move, snapped to nearest data x
    ← / →               → step one data x-value at a time
    Ctrl + ← / →        → jump to previous / next guide_values entry
    Click elsewhere     → deselect

Requires: PySide6, pyqtgraph, numpy
    pip install PySide6 pyqtgraph numpy
"""

import sys
import os

os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, QtGui
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.util.units import ScaledFloat

# ── Module-level constants ────────────────────────────────────────────────────

_STYLE_NORMAL   = {"color": (100, 180, 255), "width": 1}
_STYLE_SELECTED = {"color": (255, 220,  50), "width": 1}
_HIT_TOLERANCE_PX = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nearest_index(arr: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(arr - value)))


# ── SnappingLine ──────────────────────────────────────────────────────────────

class SnappingLine(pg.InfiniteLine):
    """
    Vertical InfiniteLine pinned to exact data x-values.

    Can be constructed with no data (data_x=None, data_y=None); in that state
    it is hidden and all movement methods are no-ops.  Call set_data(x, y) to
    activate it, or clear_data() to return to the no-data state.

    guide_values may be None — Ctrl+arrow then behaves like plain arrow.
    """
    # Emitted with (x, y) whenever the line moves.
    sigLineMoved = QtCore.Signal(float, float)
    #sigPositionChangeFinished = QtCore.Signal()

    class _labelFormat:  #For passing into InfiniteLine as label formatter
        @staticmethod
        def format(value):
            x = ScaledFloat(value)
            return '{:.3r}'.format(x)
    
    def __init__(self, data_x=None, data_y=None, guide_values=None, initial_index: int = 0, **kwargs):
        

        self._selected    = False
        self._dragging    = False
        self._data_index  = 0
        self._snap_index  = 0
        self._data_x      = None
        self._data_y      = None
        self._guide_values = None

        # Initialise the pg.InfiniteLine at pos=0 regardless of data state.
        super().__init__(pos=0, angle=90, movable=False, label=self._labelFormat, **kwargs)

        #self.label.valueChanged = self._labelValueChangedOverride
        

        self._apply_style(selected=False)

        # Load data if provided at construction time.
        if data_x is not None and data_y is not None:
            self.set_data(data_x, data_y,
                          guide_values=guide_values,
                          initial_index=initial_index)
        else:
            # Store guide_values for when data arrives later.
            self._guide_values = (np.asarray(guide_values, dtype=float)
                                 if guide_values is not None else None)
            self.setVisible(False)

        #Make the scatter point showing current x,y
        self._xypoint = pg.ScatterPlotItem(
                [0], [0],
                size=6,
                pen=pg.mkPen(color=(255, 220, 50), width=2),
                brush=pg.mkBrush(color=(255, 220, 50, 180)),
                symbol="o",
                zValue=10,
            )
        self._xypoint.hide()
        self.setZValue(5)
        self._xypoint.setZValue(10)


    # ── Data management ───────────────────────────────────────────────────────

    @property
    def has_data(self) -> bool:
        return self._data_x is not None

    def set_data(self, data_x, data_y, guide_values=None, initial_index: int = 0):
        """Load or replace the underlying data arrays and show the line."""
        x = np.asarray(data_x, dtype=float)
        y = np.asarray(data_y, dtype=float)

        # Preserve current position across data updates where possible.
        if self.has_data:
            # Re-snap the existing position to the nearest point in the new data.
            current = self._data_x[self._data_index]
            new_index = _nearest_index(x, current)
        else:
            new_index = int(np.clip(initial_index, 0, len(x) - 1))

        self._data_x     = x
        self._data_y     = y

        # guide_values: use the argument if supplied, otherwise keep existing.
        if guide_values is not None or not self.has_data:
            self.set_guide_values(guide_values)

        self._data_index = new_index
        self._sync_snap_index()
        self.setPos(self._data_x[self._data_index])
        
        self.setVisible(True)
        self._xypoint.show()

    def clear_data(self):
        """Remove data and hide the line."""
        self._data_x     = None
        self._data_y     = None
        self._data_index = 0
        self._snap_index = 0
        self._selected   = False
        self._dragging   = False
        self.setVisible(False)

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def selected(self) -> bool:
        return self._selected

    @property
    def dragging(self) -> bool:
        return self._dragging

    def current_x(self) -> float:
        """Current x position (data-snapped). Returns 0.0 if no data."""
        return float(self._data_x[self._data_index]) if self.has_data else 0.0

    def current_y(self) -> float:
        """Current y value at the line position. Returns 0.0 if no data."""
        return float(self._data_y[self._data_index]) if self.has_data else 0.0

    # ── guide_values ───────────────────────────────────────────────────────────

    def set_guide_values(self, guide_values):
        if guide_values is None:
            self._guide_values = None
            self._snap_index  = 0
        else:
            self._guide_values = np.asarray(guide_values, dtype=float)
            self._sync_snap_index()

    def _sync_snap_index(self):
        """Keep _snap_index aligned to the current data position."""
        if self._guide_values is not None and self.has_data:
            self._snap_index = _nearest_index(
                self._guide_values, self._data_x[self._data_index]
            )

    # ── Style ─────────────────────────────────────────────────────────────────

    def select(self):
        self._selected = True
        self._apply_style(selected=True)

    def deselect(self):
        self._selected = False
        self._dragging = False
        self._apply_style(selected=False)

    def _apply_style(self, selected: bool):
        s = _STYLE_SELECTED if selected else _STYLE_NORMAL
        self.setPen(pg.mkPen(color=s["color"], width=s["width"]))

    # ── Hit test ──────────────────────────────────────────────────────────────

    def hit_test_px(self, widget_pos: QtCore.QPointF, graphics_view) -> bool:
        if not self.has_data or not self.isVisible():
            return False
        vb = self.getViewBox()
        line_scene  = vb.mapViewToScene(QtCore.QPointF(self.value(), 0.0))
        line_widget = graphics_view.mapFromScene(line_scene)
        return abs(widget_pos.x() - line_widget.x()) <= _HIT_TOLERANCE_PX

    # ── Core index setter ─────────────────────────────────────────────────────

    def _set_data_index(self, idx: int):
        if not self.has_data:
            return
        self._data_index = int(np.clip(idx, 0, len(self._data_x) - 1))
        self._sync_snap_index()
        super().setPos(self._data_x[self._data_index])
        
        cx,cy = self.current_x(), self.current_y()
        self.sigLineMoved.emit(cx,cy)

        self._xypoint.setData([cx], [cy])

    # ── Movement (all public, safe to call externally) ────────────────────────
    def setPos(self, x_value: float):  #Overrides pg.InfiniteLine.setPos
        """Move the line to the data x nearest to x_value."""
        if not self.has_data:
            return
        self._set_data_index(_nearest_index(self._data_x, x_value))

    def start_drag(self):
        if self.has_data:
            self._dragging = True

    def drag_to(self, data_x_value: float):
        self.setPos(data_x_value)

    def end_drag(self):
        self._dragging = False

    def move_data(self, go_right: bool):
        """Step one data_x index left or right."""
        if not self.has_data:
            return
        self._set_data_index(self._data_index + (1 if go_right else -1))

    def move_snap(self, go_right: bool):
        """Jump to next/prev guide_values entry; falls back to move_data if None."""
        if not self.has_data:
            return
        if self._guide_values is None:
            self.move_data(go_right)
            return
        self._snap_index = int(np.clip(
            self._snap_index + (1 if go_right else -1),
            0, len(self._guide_values) - 1
        ))
        self._set_data_index(
            _nearest_index(self._data_x, self._guide_values[self._snap_index])
        )

    # ── Shortcuts for qudi compatibility ────────────────────────
    def value(self):
        return self.current_x()
    



# ── InteractivePlot ───────────────────────────────────────────────────────────

class InteractivePlot(pg.PlotWidget):
    """
    Self-contained PlotWidget with a draggable snapping InfiniteLine.

    The SnappingLine is created immediately at __init__ (hidden until data is
    set), so signals such as plot.sigLineMoved can be connected before any data
    is loaded.

    Parameters
    ----------
    data : tuple(array_like x, array_like y) or None
        Initial data.  Assign to plot.data at any time to update.
    guide_values : array_like or None
        Ctrl+arrow jump targets.  Assign to plot.guide_values at any time.
    **kwargs
        Forwarded to pg.PlotWidget (e.g. title=, background=).
    """



    def __init__(self, data=None, guide_values=None, **kwargs):
        super().__init__(**kwargs)

        self._curve          = None
        self._guide_lines     = []
        self._connected_items = {}
        self._guide_values    = (np.asarray(guide_values, dtype=float)
                                if guide_values is not None else None)

        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        #self._setup_style()
        self._setup_status_bar()
        #self._setup_instructions()

        # Create the SnappingLine immediately so signals can be connected before
        # data arrives.  It starts hidden.
        self._snap_line = SnappingLine(
            guide_values=self._guide_values,
            #label="{value:.2f}",
            labelOpts={"position": 0.08, "color": (220, 220, 220)},
        )
        self.addItem(self._snap_line)
        self.addItem(self._snap_line._xypoint)
        self.snap_line.sigLineMoved.connect(self._update_readout)

        if data is not None:
            self.data = data

    # ── Read-only property exposing the line ──────────────────────────────────

    @property
    def snap_line(self) -> SnappingLine:
        """The underlying SnappingLine item. Always exists; may be hidden."""
        return self._snap_line

    # ── Internal setup ────────────────────────────────────────────────────────

    def _setup_style(self):
        self.setBackground("#1a1a2e")
        for axis in ("bottom", "left"):
            self.getAxis(axis).setPen(pg.mkPen("#555"))
            self.getAxis(axis).setTextPen(pg.mkPen("#aaa"))

    def _setup_status_bar(self):
        self._status_item = pg.LabelItem("  x: —    y: —", parent=self.plotItem)
        self._status_item.anchor(itemPos=(0, 1), parentPos=(0, 1), offset=(4, -4))

    def _setup_instructions(self):
        instr = pg.LabelItem(
            "<span style='color:#555; font-size:10px'>"
            "Click line to select  ·  Drag  ·  ←/→ step data  ·  "
            "Ctrl+←/→ snap values  ·  Click elsewhere to deselect"
            "</span>",
            parent=self.plotItem,
        )
        instr.anchor(itemPos=(0, 0), parentPos=(0, 0), offset=(8, 6))

    # ── data property ─────────────────────────────────────────────────────────

    @property
    def data(self):
        return self._data if hasattr(self, "_data") else None

    @data.setter
    def data(self, value):
        if value is None:
            self._hide_data_items()
            self._data = None
            self._status_item.setText("  x: —    y: —")
            return

        x = np.asarray(value[0], dtype=float)
        y = np.asarray(value[1], dtype=float)
        self._data = (x, y)

        # Update or create the curve.
        if self._curve is None:
            self._curve = self.plot(
                x, y#, pen=pg.mkPen(color=(100, 200, 140), width=1.5)
            )
            self._curve.setPen(palette.c1, width=1)
        else:
            self._curve.setData(x, y)

        # Rebuild the snap guide lines if needed.
        self._rebuild_snap_guide_lines()

        # Feed new data into the (always-existing) SnappingLine.
        self._snap_line.set_data(x, y, guide_values=self._guide_values)

        # Emit sigLineMoved to update with new data.
        cx, cy = self._snap_line.current_x(), self._snap_line.current_y()
        self._snap_line.sigLineMoved.emit(cx,cy)


    def _hide_data_items(self):
        """Hide the line and remove the curve/scatter when data is cleared."""
        self._snap_line.clear_data()
        for item in [self._curve] + self._guide_lines:
            if item is not None:
                self.removeItem(item)
        self._curve      = None
        self._guide_lines = []

    # ── PlotDataItem connection ───────────────────────────────────────────────

    def connect_data_item(self, item: pg.PlotDataItem):
        """
        Sync this plot's data to a PlotDataItem whenever its data changes.
        Stores the connection so it can be removed with disconnect_data_item().
        """
        if item in self._connected_items:
            return

        def _sync():
            x, y = item.getData()
            if x is not None and y is not None:
                self.data = (x, y)

        item.sigPlotChanged.connect(_sync)
        self._connected_items[item] = _sync
        _sync()

    def disconnect_data_item(self, item: pg.PlotDataItem):
        """Remove the sync connection made with connect_data_item()."""
        slot = self._connected_items.pop(item, None)
        if slot is not None:
            item.sigPlotChanged.disconnect(slot)

    # ── guide_values property ──────────────────────────────────────────────────

    @property
    def guide_values(self):
        return self._guide_values

    @guide_values.setter
    def guide_values(self, value):
        self._guide_values = (np.asarray(value, dtype=float)
                             if value is not None else None)
        self._snap_line.set_guide_values(self._guide_values)
        self._rebuild_snap_guide_lines()

    def _rebuild_snap_guide_lines(self):
        for item in self._guide_lines:
            self.removeItem(item)
        self._guide_lines = []
        if self._guide_values is None:
            return
        for v in self._guide_values:
            line = pg.InfiniteLine(
                pos=v, angle=90,
                pen=pg.mkPen(color=(70, 70, 110), width=1, style=QtCore.Qt.DotLine),
            )
            self.addItem(line)
            self._guide_lines.append(line)

    # ── Readout ───────────────────────────────────────────────────────────────

    def _update_readout(self):
        if not self._snap_line.has_data:
            return
        x_raw = self._snap_line.current_x()
        y_raw = self._snap_line.current_y()
        if np.isfinite(x_raw):
            x = '{:.3r}'.format(ScaledFloat(x_raw))
        else:
            x = 'nan'
        if np.isfinite(y_raw):
            y = '{:.3r}'.format(ScaledFloat(y_raw))
        else:
            y = 'nan'
        self._status_item.setText(
            f"<span style='color:#9ab; font-family:monospace; font-size:11px'>"
            f"  x: {x}    y: {y}</span>"
        )
        

    # ── Coordinate helper ─────────────────────────────────────────────────────

    def _to_data(self, pos) -> QtCore.QPointF:
        return self.plotItem.vb.mapSceneToView(self.mapToScene(pos))

    # ── Mouse events ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self._snap_line.hit_test_px(QtCore.QPointF(event.pos()), self):
                self._snap_line.select()
                self._snap_line.start_drag()
            else:
                self._snap_line.deselect()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._snap_line.dragging:
            data_pos = self.plotItem.vb.mapSceneToView(self.mapToScene(event.pos()))
            self._snap_line.drag_to(data_pos.x())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._snap_line.end_drag()
        super().mouseReleaseEvent(event)

    # ── Keyboard events ───────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if not self._snap_line.selected:
            super().keyPressEvent(event)
            return

        ctrl = bool(event.modifiers() & QtCore.Qt.ControlModifier)
        key  = event.key()

        if key == QtCore.Qt.Key_Left:
            self._snap_line.move_snap(go_right=False) if ctrl else \
                self._snap_line.move_data(go_right=False)
            return
        elif key == QtCore.Qt.Key_Right:
            self._snap_line.move_snap(go_right=True) if ctrl else \
                self._snap_line.move_data(go_right=True)
            return

        super().keyPressEvent(event)


# ── Demo ──────────────────────────────────────────────────────────────────────

def main():
    app = QtWidgets.QApplication(sys.argv)

    guide_values = np.array([0, 1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 66, 78, 91, 105], dtype=float)
    x = np.linspace(guide_values[0], guide_values[-1], 400)
    y = np.sin(x * 0.15) * 5 + np.random.default_rng(0).normal(0, 0.4, len(x))

    plot = InteractivePlot(
        data=(x, y),
        guide_values=guide_values,
        title="InteractivePlot Demo",
    )
    plot.setWindowTitle("InteractivePlot Demo")
    plot.resize(960, 540)

    # Signal connection — works even before data is set.
    plot.snap_line.sigLineMoved.connect(lambda x, y: print(f"sigLineMoved → x={x:.4f}  y={y:.4f}"))

    # External control example — move the line programmatically.
    # plot.snap_line.move_to_x(45.0)
    # plot.snap_line.hide()
    # plot.snap_line.show()

    plot.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()