import sys
from unicodedata import name
import numpy as np
from PySide6 import QtWidgets as qw
from PySide6 import QtCore
import pyqtgraph as pg
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox


class GridApp(qw.QWidget):
    
    sig_grid_updated = QtCore.Signal(list,list)

    def __init__(self,parent):
        super().__init__()
        self.setWindowTitle("Grid Generator")
        self.parent=parent
        #self.scanning_data_logic = self.parent._connectors['scanning_data_logic']
        #for name, connector in self.parent._connectors.items():
        #    setattr(self, name, connector)
        

        # Layout
        layout = qw.QHBoxLayout(self)

        # Plot
        self.plot = pg.PlotWidget()
        layout.addWidget(self.plot)

        self.img = pg.ImageItem()
        self.plot.addItem(self.img)

        self.scatter = pg.ScatterPlotItem(pen=None, brush='r', size=5)
        self.scatter_select = pg.ScatterPlotItem(pen=None, brush=(173, 216, 230), size=5)
        self.scatter_done = pg.ScatterPlotItem(pen=None, brush='g', size=5)
        self.scatter_current = pg.ScatterPlotItem(pen=None, brush='y', size=5)
        self.scatter_highlight = pg.ScatterPlotItem(pen=pg.mkPen('orange', width=2), brush=None, size=14, symbol='o')
        self.plot.addItem(self.scatter)
        self.plot.addItem(self.scatter_select)
        self.plot.addItem(self.scatter_done)
        self.plot.addItem(self.scatter_current)
        self.plot.addItem(self.scatter_highlight)
        self._select_data = np.full((3,2),np.nan)

        # Crosshair
        self.vLine = pg.InfiniteLine(angle=90, movable=False)
        self.hLine = pg.InfiniteLine(angle=0, movable=False)
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self.mouse_clicked)

        self.pick_mode = None

        # Selection / manual-add state
        self.select_mode = False
        self.add_manual_mode = False
        self.selected_indices = set()
        self._drag_rect_item = None

        # Hijack the viewbox drag event so a left-drag can rubber-band select points
        self.vb = self.plot.plotItem.vb
        self._default_drag_event = self.vb.mouseDragEvent
        self.vb.mouseDragEvent = self._vb_mouse_drag_event

        
        inputLayout = qw.QGridLayout()

        # Corner inputs
        self.corners = [[ScienDSpinBox(), ScienDSpinBox()],
                        [ScienDSpinBox(), ScienDSpinBox()],
                        [ScienDSpinBox(), ScienDSpinBox()]]

        for ii, cornerI in enumerate(self.corners):
            inputLayout.addWidget(qw.QLabel(f'Corner {ii+1}'),ii,0)
            for jj, cornerIJ in enumerate(cornerI):
                cornerIJ.setDecimals(4)
                cornerIJ.setMinimumWidth(100)
                cornerIJ.setValue(np.random.rand()*1e-5)
                inputLayout.addWidget(cornerIJ,ii,jj+1)



        # Point counts
        self.n12 = qw.QSpinBox()
        self.n12.setMaximum(10000)
        self.n12.setValue(10)
        self.n23 = qw.QSpinBox()
        self.n23.setMaximum(10000)
        self.n23.setValue(10)

        inputLayout.addWidget(qw.QLabel("N points (1→2)"),3,0)
        inputLayout.addWidget(self.n12,3,1)
        inputLayout.addWidget(qw.QLabel("N points (2→3)"),4,0)
        inputLayout.addWidget(self.n23,4,1)
        
        layout.addLayout(inputLayout)

        # Buttons
        
        self.btn_c1 = qw.QPushButton("Pick Corner 1")
        self.btn_c2 = qw.QPushButton("Pick Corner 2")
        self.btn_c3 = qw.QPushButton("Pick Corner 3")

        inputLayout.addWidget(self.btn_c1,0,3)
        inputLayout.addWidget(self.btn_c2,1,3)
        inputLayout.addWidget(self.btn_c3,2,3)
        
        self.btn_update = qw.QPushButton("Update Grid")
        inputLayout.addWidget(self.btn_update,5,0)

        self.btn_select = qw.QPushButton("Select Points")
        self.btn_select.setCheckable(True)
        self.btn_delete_selected = qw.QPushButton("Delete Selected")
        self.btn_add_manual = qw.QPushButton("Add Manual")
        self.btn_add_manual.setCheckable(True)

        inputLayout.addWidget(self.btn_select,6,0)
        inputLayout.addWidget(self.btn_delete_selected,6,1)
        inputLayout.addWidget(self.btn_add_manual,7,0)

        # Connections
        self.btn_update.clicked.connect(self.update_grid)
        self.btn_c1.clicked.connect(lambda: self.set_pick_mode(1))
        self.btn_c2.clicked.connect(lambda: self.set_pick_mode(2))
        self.btn_c3.clicked.connect(lambda: self.set_pick_mode(3))
        self.btn_select.toggled.connect(self.toggle_select_mode)
        self.btn_delete_selected.clicked.connect(self.delete_selected)
        self.btn_add_manual.toggled.connect(self.toggle_add_manual_mode)

        #Defaults
        self.grid=None
        self.gridCR=None

    def _connect_scan_logic(self,logic):
        setattr(self,'scanning_data_logic',logic)
        
    def exec(self):
        self.load_data()
        self.update_image()
        self.show()

    def load_data(self):
        self.data = self.scanning_data_logic().get_last_history_entry(('x','y'))[0]._data[0]
        self.extent = self.scanning_data_logic().get_last_history_entry(('x','y'))[0].settings.range

    def update_image(self):
        (xmin, xmax), (ymin, ymax) = self.extent
        self.img.setImage(self.data)
        self.img.setRect(QtCore.QRectF(xmin, ymin, xmax - xmin, ymax - ymin))

    def set_pick_mode(self, corner):
        self.pick_mode = corner

    def mouse_moved(self, evt):
        pos = evt[0]
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_point = self.plot.plotItem.vb.mapSceneToView(pos)
            self.vLine.setPos(mouse_point.x())
            self.hLine.setPos(mouse_point.y())

    def mouse_clicked(self, evt):
        pos = evt.scenePos()
        mouse_point = self.plot.plotItem.vb.mapSceneToView(pos)
        x, y = mouse_point.x(), mouse_point.y()

        if self.pick_mode is not None:
            self.corners[self.pick_mode-1][0].setValue(x)
            self.corners[self.pick_mode-1][1].setValue(y)

            self._select_data[self.pick_mode-1] = (x,y)
            self.update_done()
            self.scatter_select.setData(*self._select_data.T)

            self.pick_mode = None
            return

        if self.add_manual_mode:
            self.add_manual_point(x, y)
            return

        if self.select_mode:
            self.toggle_nearest_point_selection(x, y)
            return

    def toggle_select_mode(self, checked):
        self.select_mode = checked
        if checked:
            self.add_manual_mode = False
            self.btn_add_manual.setChecked(False)
        else:
            self.selected_indices = set()
            self.update_selection_highlight()

    def toggle_add_manual_mode(self, checked):
        self.add_manual_mode = checked
        if checked:
            self.select_mode = False
            self.btn_select.setChecked(False)
            self.selected_indices = set()
            self.update_selection_highlight()

    def add_manual_point(self, x, y):
        point = np.array([[x, y]])
        if self.grid is None or len(self.grid) == 0:
            self.grid = point
            self.gridCR = []
        else:
            self.grid = np.vstack([self.grid, point])
        self.gridCR.append(f'M{len(self.grid)-1}')
        self.scatter.setData(self.grid[:, 0], self.grid[:, 1])
        self.sig_grid_updated.emit([list(gI) for gI in self.grid], self.gridCR)

    def toggle_nearest_point_selection(self, x, y):
        if self.grid is None or len(self.grid) == 0:
            return
        xspan = float(np.ptp(self.grid[:, 0])) or 1.0
        yspan = float(np.ptp(self.grid[:, 1])) or 1.0
        threshold = 0.03 * max(xspan, yspan)
        dists = np.hypot(self.grid[:, 0] - x, self.grid[:, 1] - y)
        idx = int(np.argmin(dists))
        if dists[idx] > threshold:
            return
        if idx in self.selected_indices:
            self.selected_indices.discard(idx)
        else:
            self.selected_indices.add(idx)
        self.update_selection_highlight()

    def select_points_in_rect(self, p1, p2):
        if self.grid is None or len(self.grid) == 0:
            return
        xmin, xmax = sorted((p1.x(), p2.x()))
        ymin, ymax = sorted((p1.y(), p2.y()))
        inside = np.where(
            (self.grid[:, 0] >= xmin) & (self.grid[:, 0] <= xmax) &
            (self.grid[:, 1] >= ymin) & (self.grid[:, 1] <= ymax)
        )[0]
        self.selected_indices = set(inside.tolist())
        self.update_selection_highlight()

    def update_selection_highlight(self):
        if self.grid is None or not self.selected_indices:
            self.scatter_highlight.setData([])
            return
        idx = sorted(self.selected_indices)
        pts = self.grid[idx]
        self.scatter_highlight.setData(pts[:, 0], pts[:, 1])

    def delete_selected(self):
        if self.grid is None or not self.selected_indices:
            return
        keep = [i for i in range(len(self.grid)) if i not in self.selected_indices]
        self.grid = self.grid[keep]
        self.gridCR = [self.gridCR[i] for i in keep]
        self.selected_indices = set()
        if len(self.grid):
            self.scatter.setData(self.grid[:, 0], self.grid[:, 1])
        else:
            self.scatter.setData([])
        self.update_selection_highlight()
        self.sig_grid_updated.emit([list(gI) for gI in self.grid], self.gridCR)

    def _vb_mouse_drag_event(self, ev, axis=None):
        if not self.select_mode or ev.button() != QtCore.Qt.MouseButton.LeftButton:
            self._default_drag_event(ev, axis=axis)
            return

        ev.accept()
        start = self.vb.mapSceneToView(ev.buttonDownScenePos())
        cur = self.vb.mapSceneToView(ev.scenePos())

        if ev.isStart():
            self._drag_rect_item = qw.QGraphicsRectItem()
            self._drag_rect_item.setPen(pg.mkPen('y', width=1))
            self.plot.addItem(self._drag_rect_item)

        if self._drag_rect_item is not None:
            rect = QtCore.QRectF(
                QtCore.QPointF(min(start.x(), cur.x()), min(start.y(), cur.y())),
                QtCore.QPointF(max(start.x(), cur.x()), max(start.y(), cur.y())),
            )
            self._drag_rect_item.setRect(rect)

        if ev.isFinish():
            self.select_points_in_rect(start, cur)
            if self._drag_rect_item is not None:
                self.plot.removeItem(self._drag_rect_item)
                self._drag_rect_item = None
    
    
    def update_grid(self):
        try:
            c1 = np.array([(self.corners[0][0].value()), (self.corners[0][1].value())])
            c2 = np.array([(self.corners[1][0].value()), (self.corners[1][1].value())])
            c3 = np.array([(self.corners[2][0].value()), (self.corners[2][1].value())])

            n12 = int(self.n12.value())
            n23 = int(self.n23.value())

            # Basis vectors
            v12 = c2 - c1
            v23 = c3 - c2
            # Generate grid
            grid = []
            self.gridCR = []
            for i in range(n12):
                for j in range(n23):
                    p = c1 + (i / (n12 - 1)) * v12 + (j / (n23 - 1)) * v23
                    grid.append(p)
                    self.gridCR.append(f'C{i}R{j}')

            self.grid = np.array(grid)
            self.selected_indices = set()
            self.update_selection_highlight()
            self.update_done()
            self.scatter.setData(self.grid[:, 0], self.grid[:, 1])
            self.scatter_select.setData([])
            self.sig_grid_updated.emit([list(gI) for gI in self.grid], self.gridCR)

        except Exception as e:
            print("Error:", e)

    @QtCore.Slot()
    def update_done(self,data=None,currentPoint=None):
        if data is not None:
            self.scatter_done.setData(*np.array(data).T)
        else:
            self.scatter_done.setData([])
        if currentPoint is not None:
            self.scatter_current.setData([currentPoint[0]],[currentPoint[1]])
        else:
            self.scatter_current.setData([])

