import sys
from unicodedata import name
import numpy as np
from PySide2 import QtWidgets as qw
from PySide2 import QtCore
import pyqtgraph as pg
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox


class GridApp(qw.QWidget):
    
    sig_grid_updated = QtCore.Signal(list)

    def __init__(self,parent):
        super().__init__()
        self.setWindowTitle("Grid Generator")
        self.parent=parent
        #self.scanning_data_logic = self.parent._connectors['scanning_data_logic']
        for name, connector in self.parent._connectors.items():
            setattr(self, name, connector)
        

        # Layout
        layout = qw.QHBoxLayout(self)

        # Plot
        self.plot = pg.PlotWidget()
        layout.addWidget(self.plot)

        self.img = pg.ImageItem()
        self.plot.addItem(self.img)

        self.scatter = pg.ScatterPlotItem(pen=None, brush='r', size=5)
        self.scatter_select = pg.ScatterPlotItem(pen=None, brush='r', size=5)
        self.scatter_done = pg.ScatterPlotItem(pen=None, brush='g', size=5)
        self.scatter_current = pg.ScatterPlotItem(pen=None, brush='y', size=5)
        self.plot.addItem(self.scatter)
        self.plot.addItem(self.scatter_select)
        self.plot.addItem(self.scatter_done)
        self.plot.addItem(self.scatter_current)
        self._select_data = np.full((3,2),np.nan)

        # Crosshair
        self.vLine = pg.InfiniteLine(angle=90, movable=False)
        self.hLine = pg.InfiniteLine(angle=0, movable=False)
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self.mouse_clicked)

        self.pick_mode = None


        
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
        self.n12.setValue(10)
        self.n23 = qw.QSpinBox()
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

        

        # Connections
        self.btn_update.clicked.connect(self.update_grid)
        self.btn_c1.clicked.connect(lambda: self.set_pick_mode(1))
        self.btn_c2.clicked.connect(lambda: self.set_pick_mode(2))
        self.btn_c3.clicked.connect(lambda: self.set_pick_mode(3))

        
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
        self.img.setRect(pg.QtCore.QRectF(xmin, ymin, xmax - xmin, ymax - ymin))

    def set_pick_mode(self, corner):
        self.pick_mode = corner

    def mouse_moved(self, evt):
        pos = evt[0]
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_point = self.plot.plotItem.vb.mapSceneToView(pos)
            self.vLine.setPos(mouse_point.x())
            self.hLine.setPos(mouse_point.y())

    def mouse_clicked(self, evt):
        if self.pick_mode is None:
            return

        pos = evt.scenePos()
        mouse_point = self.plot.plotItem.vb.mapSceneToView(pos)

        x, y = mouse_point.x(), mouse_point.y()

        self.corners[self.pick_mode-1][0].setValue(x)
        self.corners[self.pick_mode-1][1].setValue(y)

        self._select_data[self.pick_mode-1] = (x,y)
        self.update_done()
        self.scatter_select.setData(*self._select_data.T)

        self.pick_mode = None
    
    grid=None
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
            for i in range(n12):
                for j in range(n23):
                    p = c1 + (i / (n12 - 1)) * v12 + (j / (n23 - 1)) * v23
                    grid.append(p)

            self.grid = np.array(grid)
            self.update_done()
            self.scatter.setData(self.grid[:, 0], self.grid[:, 1])
            self.scatter_select.setData([])
            self.sig_grid_updated.emit([list(gI) for gI in self.grid])

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

