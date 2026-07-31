# -*- coding: utf-8 -*-
"""
Control dock widget for SimpleScanGui.

Contains all scan parameter controls: device selection, x range, timing, number of
scans, and shuffle option.

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

__all__ = ('SimpleScanControlDockWidget',)

from PySide6 import QtCore, QtWidgets

from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox


class SimpleScanControlDockWidget(AdvancedDockWidget):
    """
    Dock widget exposing all scan parameters for SimpleScanLogic.

    Signals
    -------
    sigDeviceChanged(str)
    sigXRangeChanged(float, float, int)   start, end, n_steps
    sigTimePerChanged(float)
    sigTimeWaitChanged(float)
    sigNumberScansChanged(int)
    sigShuffleXChanged(bool)
    """

    sigDeviceChanged = QtCore.Signal(str)
    sigXRangeChanged = QtCore.Signal(float, float, int)
    sigTimePerChanged = QtCore.Signal(float)
    sigTimeWaitChanged = QtCore.Signal(float)
    sigNumberScansChanged = QtCore.Signal(int)
    sigShuffleXChanged = QtCore.Signal(bool)
    sigStaticSetParamChanged = QtCore.Signal(str, object)  # label, new value

    def __init__(self, *args, **kwargs):
        super().__init__('Scan Control', *args, **kwargs)
        self.setObjectName('SimpleScan_ControlDock')

        main_widget = QtWidgets.QWidget()
        main_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(8, 8, 8, 8)
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(8)
        main_widget.setLayout(form)
        self.setWidget(main_widget)
        self._form = form
        self._static_param_widgets = {}  # label -> widget

        # ── Device selector ───────────────────────────────────────────────────
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.setToolTip('Select the device to scan')
        form.addRow('Scan Device:', self.device_combo)

        # ── X range ───────────────────────────────────────────────────────────
        x_range_widget = QtWidgets.QWidget()
        x_range_layout = QtWidgets.QHBoxLayout()
        x_range_layout.setContentsMargins(0, 0, 0, 0)
        x_range_layout.setSpacing(4)
        x_range_widget.setLayout(x_range_layout)

        x_range_layout.addWidget(QtWidgets.QLabel('Start:'))
        self.x_start_spinbox = ScienDSpinBox()
        self.x_start_spinbox.setDecimals(6)
        self.x_start_spinbox.setMinimumWidth(120)
        self.x_start_spinbox.setToolTip('Scan start value')
        x_range_layout.addWidget(self.x_start_spinbox)

        x_range_layout.addWidget(QtWidgets.QLabel('End:'))
        self.x_end_spinbox = ScienDSpinBox()
        self.x_end_spinbox.setDecimals(6)
        self.x_end_spinbox.setMinimumWidth(120)
        self.x_end_spinbox.setToolTip('Scan end value')
        x_range_layout.addWidget(self.x_end_spinbox)

        x_range_layout.addWidget(QtWidgets.QLabel('Steps:'))
        self.x_steps_spinbox = QtWidgets.QSpinBox()
        self.x_steps_spinbox.setMinimum(2)
        self.x_steps_spinbox.setMaximum(100000)
        self.x_steps_spinbox.setValue(10)
        self.x_steps_spinbox.setMinimumWidth(60)
        self.x_steps_spinbox.setToolTip('Number of evenly-spaced x points')
        x_range_layout.addWidget(self.x_steps_spinbox)

        self._x_range_form_label = QtWidgets.QLabel('X Range:')
        form.addRow(self._x_range_form_label, x_range_widget)

        # ── Time per point ────────────────────────────────────────────────────
        self.time_per_spinbox = ScienDSpinBox()
        self.time_per_spinbox.setDecimals(4)
        self.time_per_spinbox.setSuffix('s')
        self.time_per_spinbox.setMinimum(1e-6)
        self.time_per_spinbox.setValue(1.0)
        self.time_per_spinbox.setToolTip('Integration / acquisition time per data point')
        form.addRow('Time per Point:', self.time_per_spinbox)

        # ── Wait time ─────────────────────────────────────────────────────────
        self.time_wait_spinbox = ScienDSpinBox()
        self.time_wait_spinbox.setDecimals(4)
        self.time_wait_spinbox.setSuffix('s')
        self.time_wait_spinbox.setMinimum(1e-6)
        self.time_wait_spinbox.setValue(0.1)
        self.time_wait_spinbox.setToolTip(
            'Settling time after moving to each x position before recording'
        )
        form.addRow('Wait Time:', self.time_wait_spinbox)

        # ── Number of scans ───────────────────────────────────────────────────
        self.number_scans_spinbox = QtWidgets.QSpinBox()
        self.number_scans_spinbox.setMinimum(1)
        self.number_scans_spinbox.setMaximum(100000)
        self.number_scans_spinbox.setValue(1)
        self.number_scans_spinbox.setToolTip('Number of full scan repetitions to average')
        form.addRow('Number of Scans:', self.number_scans_spinbox)

        # ── Shuffle X ─────────────────────────────────────────────────────────
        self.shuffle_x_checkbox = QtWidgets.QCheckBox()
        self.shuffle_x_checkbox.setToolTip(
            'Randomise the x-point order within each scan line'
        )
        form.addRow('Shuffle X:', self.shuffle_x_checkbox)

        # ── Internal signal wiring ────────────────────────────────────────────
        self.device_combo.currentTextChanged.connect(self.sigDeviceChanged)
        self.x_start_spinbox.editingFinished.connect(self._emit_x_range)
        self.x_end_spinbox.editingFinished.connect(self._emit_x_range)
        self.x_steps_spinbox.editingFinished.connect(self._emit_x_range)
        self.time_per_spinbox.editingFinished.connect(
            lambda: self.sigTimePerChanged.emit(self.time_per_spinbox.value())
        )
        self.time_wait_spinbox.editingFinished.connect(
            lambda: self.sigTimeWaitChanged.emit(self.time_wait_spinbox.value())
        )
        self.number_scans_spinbox.editingFinished.connect(
            lambda: self.sigNumberScansChanged.emit(self.number_scans_spinbox.value())
        )
        self.shuffle_x_checkbox.toggled.connect(self.sigShuffleXChanged)

    # ── Internal slots ────────────────────────────────────────────────────────

    #@QtCore.Slot()
    #def _emit_static_param(self, label, spinbox):
    #    self.sigStaticSetParamChanged.emit(label, spinbox.value())

    @QtCore.Slot()
    def _emit_x_range(self):
        self.sigXRangeChanged.emit(
            self.x_start_spinbox.value(),
            self.x_end_spinbox.value(),
            self.x_steps_spinbox.value(),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def set_x_range_control(self, label, unit, range):
        """
        Update the X range row label and spinbox suffix to reflect the
        current device's first axis name and unit.

        Parameters
        ----------
        label : str
            Axis name (e.g. ``'Piezo Voltage'``).
        unit : str
            Axis unit (e.g. ``'V'``).  May be an empty string.
        """
        text = f'{label} ({unit}) Range:' if unit else f'{label} Range:'
        self._x_range_form_label.setText(text)
        suffix = unit if unit else ''
        self.x_start_spinbox.setSuffix(suffix)
        self.x_end_spinbox.setSuffix(suffix)
        self.x_start_spinbox.setValue(range[0])
        self.x_end_spinbox.setValue(range[1])
        self.x_steps_spinbox.setValue(range[2])

    def set_static_set_parameters(self, params):
        """
        Dynamically populate the form with rows for each static-set parameter.

        Existing dynamic rows are removed first.  Call with an empty dict to
        clear all rows.

        Parameters
        ----------
        params : dict from device
            ``{label: (function, value, unit, (constraints))}`` extracted from
            ``ScanDevice._static_set_parameters``.
        """
        # Remove previously added dynamic rows
        for widget in list(self._static_param_widgets.values()):
            self._form.removeRow(widget)
        self._static_param_widgets.clear()

        if not params:
            return

        for label, entry in params.items():
            print('Populating:',label,entry)
            if len(entry)==3:
                value,unit = entry[1:]
                constraint=None
            else:
                value,unit,constraint=entry[1:]
            if constraint is None or (type(constraint) == tuple):
                widget = ScienDSpinBox()
                widget.setDecimals(6)
                if constraint:
                    widget.setRange(constraint[0],constraint[1])
                else:
                    widget.setRange(-1e15, 1e15)
                if unit:
                    widget.setSuffix(unit)
                widget.setValue(float(value))
                widget.editingFinished.connect(
                    lambda sb=widget, lbl=label: self.sigStaticSetParamChanged.emit(lbl, sb.value())
                )

            elif type(constraint)==list:
                widget = QtWidgets.QComboBox()
                widget.addItems(constraint)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(
                    lambda text, lbl= label: self.sigStaticSetParamChanged.emit(lbl,text)
                )

            else:
                raise RuntimeError(f'Unexpected constraint type: {label} {constraint} : {type(constraint)}')
            # Use default-argument capture to freeze loop variables
            
            self._static_param_widgets[label] = widget
            self._form.addRow(f'{label}:', widget)

    def set_device_list(self, devices):
        """
        Populate the device combo box.

        Parameters
        ----------
        devices : list[str]
            Device names from ``logic.device_dict``.
        """
        current = self.device_combo.currentText()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(devices)
        idx = self.device_combo.findText(current)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)

    def set_scan_parameters(self, params):
        """
        Update controls from a parameter dict (matching ``sigScanParametersUpdated``).

        Parameters
        ----------
        params : dict
            May contain any subset of keys:
            ``'x_range'`` → (start, end, n_steps)
            ``'time_per'``, ``'time_wait'``, ``'number_scans'``, ``'shuffle_x'``
        """
        if 'x_range' in params:
            start, end, steps = params['x_range']
            self.x_start_spinbox.blockSignals(True)
            self.x_end_spinbox.blockSignals(True)
            self.x_steps_spinbox.blockSignals(True)
            self.x_start_spinbox.setValue(float(start))
            self.x_end_spinbox.setValue(float(end))
            self.x_steps_spinbox.setValue(int(steps))
            self.x_start_spinbox.blockSignals(False)
            self.x_end_spinbox.blockSignals(False)
            self.x_steps_spinbox.blockSignals(False)

        if 'time_per' in params:
            self.time_per_spinbox.blockSignals(True)
            self.time_per_spinbox.setValue(float(params['time_per']))
            self.time_per_spinbox.blockSignals(False)

        if 'time_wait' in params:
            self.time_wait_spinbox.blockSignals(True)
            self.time_wait_spinbox.setValue(float(params['time_wait']))
            self.time_wait_spinbox.blockSignals(False)

        if 'number_scans' in params:
            self.number_scans_spinbox.blockSignals(True)
            self.number_scans_spinbox.setValue(int(params['number_scans']))
            self.number_scans_spinbox.blockSignals(False)

        if 'shuffle_x' in params:
            self.shuffle_x_checkbox.blockSignals(True)
            self.shuffle_x_checkbox.setChecked(bool(params['shuffle_x']))
            self.shuffle_x_checkbox.blockSignals(False)

    def set_enabled(self, enabled):
        """Enable or disable all parameter editing widgets."""
        self.device_combo.setEnabled(enabled)
        self.x_start_spinbox.setEnabled(enabled)
        self.x_end_spinbox.setEnabled(enabled)
        self.x_steps_spinbox.setEnabled(enabled)
        self.time_per_spinbox.setEnabled(enabled)
        self.time_wait_spinbox.setEnabled(enabled)
        self.number_scans_spinbox.setEnabled(enabled)
        self.shuffle_x_checkbox.setEnabled(enabled)
        for widget in self._static_param_widgets.values():
            widget.setEnabled(enabled)
