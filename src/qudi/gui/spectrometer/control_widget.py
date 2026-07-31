# -*- coding: utf-8 -*-
"""
This module contains the spectrometer control widget for SpectrometerGui.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

__all__ = ['SpectrometerControlWidget']

from PySide6 import QtCore
from PySide6 import QtWidgets

from qudi.util.widgets.toggle_switch import ToggleSwitch


class SpectrometerControlWidget(QtWidgets.QWidget):
    """ Widget for the spectrometer controls in SpectrometerGui """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)
        # main_layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        # main_layout.setContentsMargins(1, 1, 1, 1)
        # main_layout.setSpacing(5)

        # Control buttons
        self.acquire_button = QtWidgets.QPushButton('Acquire Spectrum')
        self.acquire_button.setToolTip('Acquire a new spectrum.')
        main_layout.addWidget(self.acquire_button, 0, 0)

        self.spectrum_live_button = QtWidgets.QPushButton('Live Spectrum')
        self.spectrum_live_button.setToolTip(
            'Collect continuously, last N scans stored and averaged'
        )
        main_layout.addWidget(self.spectrum_live_button, 0, 1)

        self.save_spectrum_button = QtWidgets.QToolButton()
        self.save_spectrum_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.save_spectrum_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum,
                                                QtWidgets.QSizePolicy.Policy.Fixed)
        main_layout.addWidget(self.save_spectrum_button, 0, 2)

        self.background_button = QtWidgets.QPushButton('Acquire Background')
        self.background_button.setToolTip('Acquire a new background spectrum.')
        main_layout.addWidget(self.background_button, 1, 0)

        self.save_background_button = QtWidgets.QToolButton()
        self.save_background_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.save_background_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum,
                                                  QtWidgets.QSizePolicy.Policy.Fixed)
        main_layout.addWidget(self.save_background_button, 1, 2)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar, 2, 0, 1, 3)

        # Add separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        main_layout.addWidget(separator, 0, 3, 3, 1)

        # Control switches
        switch_layout = QtWidgets.QGridLayout()
        switchII=0
        
        number_spectra_label = QtWidgets.QLabel('Number of Spectra:')
        number_spectra_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.number_spectra_input = QtWidgets.QSpinBox()
        self.number_spectra_input.setMinimum(0)
        self.number_spectra_input.setMaximum(999999)
        self.number_spectra_input.setValue(1)
        self.number_spectra_input.setToolTip('Number of spectra to acquire and average.')
        switch_layout.addWidget(number_spectra_label, switchII, 0)
        switch_layout.addWidget(self.number_spectra_input, switchII, 1)
        
        switchII += 1
        number_background_label = QtWidgets.QLabel('Number of Background:')
        number_background_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.number_background_input = QtWidgets.QSpinBox()
        self.number_background_input.setMinimum(0)
        self.number_spectra_input.setMaximum(999999)
        self.number_background_input.setValue(1)
        self.number_background_input.setToolTip('Number of background spectra to acquire and average.')
        switch_layout.addWidget(number_background_label, switchII, 0)
        switch_layout.addWidget(self.number_background_input, switchII, 1)

        switchII += 1
        background_correction_label = QtWidgets.QLabel('Background Correction:')
        background_correction_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.background_correction_switch = ToggleSwitch(state_names=('Off', 'On'))
        self.background_correction_switch.setFixedWidth(
            background_correction_label.sizeHint().width()
        )
        self.background_correction_switch.setFixedHeight(
            background_correction_label.sizeHint().height()*1.5
        )
        switch_layout.addWidget(background_correction_label, switchII, 0)
        switch_layout.addWidget(self.background_correction_switch, switchII, 1)

        switchII += 1
        differential_spectrum_label = QtWidgets.QLabel('Differential Spectrum:')
        differential_spectrum_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.differential_spectrum_switch = ToggleSwitch(state_names=('Off', 'On'))
        if False:  #Don't have modulator for differential, hide this.
            switch_layout.addWidget(differential_spectrum_label, 2, 0)
            switch_layout.addWidget(self.differential_spectrum_switch, 2, 1)

        switch_layout.setColumnStretch(2, 1)

        main_layout.addLayout(switch_layout, 0, 4, 3, 1)

        main_layout.setRowStretch(3, 1)
        main_layout.setColumnStretch(4, 1)

        self.acquire_button.setFixedWidth(self.background_button.sizeHint().width())
        self.background_button.setFixedWidth(self.background_button.sizeHint().width())
