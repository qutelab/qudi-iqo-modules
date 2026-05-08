# -*- coding: utf-8 -*-
"""
This module contains the spectrometer/camera status widget for SpectrometerGui.

By Adam Mayer, 2026

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

__all__ = ['SpectrometerSettingsWidget']

import pyqtgraph as pg
from PySide6 import QtCore
from PySide6 import QtWidgets

from qudi.util.colordefs import QudiPalettePale as palette
from qudi.util.widgets.toggle_switch import ToggleSwitch
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox

class SpectrometerSettingsWidget(QtWidgets.QWidget):
    """
    """
    # To include: 
    # - Camera Temperature and status
    # - Camera cooling on/off
    # - Spectrometer Exposure Time
    # - Spectrometer Central Wavelength
    # - Spectrometer Grating
    # - Spectrometer Output Port
    #
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)

        self.cam_temp_display = QtWidgets.QLineEdit()
        self.cam_temp_display.setReadOnly(True)
        self.cam_temp_display.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(self.cam_temp_display,0,0,1,2)

        self.camera_cooler_toggle = ToggleSwitch(state_names=('Cooling OFF', 'Cooling ON'))
        main_layout.addWidget(self.camera_cooler_toggle,0,2,1,2)

        self.exposure_time_set = QtWidgets.QDoubleSpinBox()
        self.exposure_time_set.setSuffix(' s')
        self.exposure_time_set.setRange(0.001,999999)
        self.exposure_time_set.setDecimals(3)
        self.exposure_time_set.setSingleStep(0.5) 
        main_layout.addWidget(QtWidgets.QLabel('Exposure Time:'),0,4)
        main_layout.addWidget(self.exposure_time_set,0,5)
        

        self.central_wavelength_set = QtWidgets.QDoubleSpinBox()
        self.central_wavelength_set.setSuffix(' nm')
        self.central_wavelength_set.setDecimals(3)
        self.central_wavelength_set.setSingleStep(5)
        #self.central_wavelength_set.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.central_wavelength_set.setRange(100,10000)
        main_layout.addWidget(QtWidgets.QLabel('Central Wavelength:'),1,0)
        main_layout.addWidget(self.central_wavelength_set,1,1)

        self.grating_set = QtWidgets.QComboBox()
        main_layout.addWidget(QtWidgets.QLabel('Grating:'),1,2)
        main_layout.addWidget(self.grating_set,1,3)

        self.output_port_set = QtWidgets.QComboBox()
        main_layout.addWidget(QtWidgets.QLabel('Output Port:'),1,4)
        main_layout.addWidget(self.output_port_set,1,5)

    def setTempDisplay(self, temp, unit='°C', statusbool=None): 
        #temp_palette = self.cam_temp_display.palette()
        if temp==0:  #Driver returns exactly 0 when acquiring, so we'll grey it out.
            self.cam_temp_display.setStyleSheet(f'background-color: (50,50,50);')
            self.cam_temp_display.setText('-')
        else:
            if statusbool is not None:
                if statusbool:
                    self.cam_temp_display.setStyleSheet(f'background-color: rgba{palette.green.getRgb()};')
                else:
                    self.cam_temp_display.setStyleSheet(f'background-color: rgba{palette.magenta.getRgb()};')
            else:
                self.cam_temp_display.setStyleSheet('')
            self.cam_temp_display.setText(f'{temp:.1f} {unit}')






if __name__ == '__main__':
    import sys
    import os
    from qudi.util.paths import get_artwork_dir
    import qudi.core.application

    stylesheet_path = os.path.join(get_artwork_dir(), 'styles', 'qdark.qss')
    with open(stylesheet_path, 'r') as file:
        stylesheet = file.read()
    path = os.path.join(os.path.dirname(stylesheet_path), 'qdark').replace('\\', '/')
    stylesheet = stylesheet.replace('{qdark}', path)

    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(stylesheet)
    mw = QtWidgets.QMainWindow()
    widget = SpectrometerSettingsWidget()
    mw.setCentralWidget(widget)
    mw.show()
    sys.exit(app.exec_())