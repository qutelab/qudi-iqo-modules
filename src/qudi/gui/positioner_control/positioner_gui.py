# -*- coding: utf-8 -*-

"""
This file contains the qudi GUI module for the Attocube ANC300 positioner.

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

from PySide6 import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.util.widgets.toggle_switch import ToggleSwitch

from qudi.logic.positioner_logic import PositionerLogic

class PositionerGui(GuiBase):
    """ A graphical interface to control the Attocube ANC300 positioner by hand.

    Example config for copy-paste:

    positioner_gui:
        module.Class: 'positioner_control.positioner_gui.PositionerGui'
        connect:
            positioner_logic: positioner_logic
    """

    _positioner_logic = Connector(name='positioner_logic', interface=PositionerLogic)

    sigUpdateAll = QtCore.Signal()
    sigGetLimits = QtCore.Signal(str)
    sigSetAcin = QtCore.Signal(str, bool)
    sigSetDcin = QtCore.Signal(str, bool)
    sigSetMode = QtCore.Signal(str, str)
    sigSetFilt = QtCore.Signal(str, str)
    sigSetStepFreq = QtCore.Signal(str, float)
    sigSetStepVoltage = QtCore.Signal(str, float)
    sigSetOffsetVoltage = QtCore.Signal(str, float)
    sigStepUp = QtCore.Signal(str, int)
    sigStepDown = QtCore.Signal(str, int)
    sigStop = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._axis_widgets = dict()
        self._limits_dialogs = dict()

    def on_activate(self):
        """ Create all UI objects and show the window. """
        logic = self._positioner_logic()
        self._mode_dict = {value: label for label, value in zip(logic.mode_options_labels, logic.mode_options)}
        self._filt_dict = {value: label for label, value in zip(logic.filt_options_labels, logic.filt_options)}
        self._mw = PositionerMainWindow()
        self._axis_widgets = dict()
        self._limits_dialogs = dict()

        for axis in logic.axis_names:
            locked_to_single_step = logic.restrict_z and axis.upper() == 'Z'
            axis_widget = PositionerAxisWidget(axis, logic.mode_options_labels, logic.filt_options_labels,
                                              locked_to_single_step=locked_to_single_step)
            self._axis_widgets[axis] = axis_widget
            self._mw.axes_layout.addWidget(axis_widget)
            self._limits_dialogs[axis] = PositionerLimitsDialog(axis, self._mw)

            axis_widget.sigAcinChanged.connect(self.sigSetAcin)
            axis_widget.sigDcinChanged.connect(self.sigSetDcin)
            axis_widget.sigModeChanged.connect(self.sigSetMode)
            axis_widget.sigFiltChanged.connect(self.sigSetFilt)
            axis_widget.sigStepFreqChanged.connect(self.sigSetStepFreq)
            axis_widget.sigStepVoltageChanged.connect(self.sigSetStepVoltage)
            axis_widget.sigOffsetVoltageChanged.connect(self.sigSetOffsetVoltage)
            axis_widget.sigStepUp.connect(self.sigStepUp)
            axis_widget.sigStepDown.connect(self.sigStepDown)
            axis_widget.sigStop.connect(self.sigStop)
            axis_widget.sigLimitsRequested.connect(self._show_limits_dialog)

        self._mw.update_button.clicked.connect(self.sigUpdateAll)

        self.sigUpdateAll.connect(logic.update_all_values, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigGetLimits.connect(logic.get_limits, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetAcin.connect(logic.set_acin, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetDcin.connect(logic.set_dcin, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetMode.connect(logic.set_mode, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetFilt.connect(logic.set_filt, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetStepFreq.connect(logic.set_step_freq, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetStepVoltage.connect(logic.set_step_voltage, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigSetOffsetVoltage.connect(logic.set_offset_voltage, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigStepUp.connect(logic.step_up, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigStepDown.connect(logic.step_down, QtCore.Qt.ConnectionType.QueuedConnection)
        self.sigStop.connect(logic.stop, QtCore.Qt.ConnectionType.QueuedConnection)

        logic.sigValuesUpdated.connect(self._values_updated, QtCore.Qt.ConnectionType.QueuedConnection)
        logic.sigLimitsUpdated.connect(self._limits_updated, QtCore.Qt.ConnectionType.QueuedConnection)
        logic.sigActivityChanged.connect(self._activity_changed, QtCore.Qt.ConnectionType.QueuedConnection)

        self._restore_window_geometry(self._mw)
        self.sigUpdateAll.emit()
        self.show()

    def on_deactivate(self):
        """ Hide window and disconnect signals. """
        logic = self._positioner_logic()
        logic.sigValuesUpdated.disconnect(self._values_updated)
        logic.sigLimitsUpdated.disconnect(self._limits_updated)
        logic.sigActivityChanged.disconnect(self._activity_changed)

        self.sigUpdateAll.disconnect()
        self.sigGetLimits.disconnect()
        self.sigSetAcin.disconnect()
        self.sigSetDcin.disconnect()
        self.sigSetMode.disconnect()
        self.sigSetFilt.disconnect()
        self.sigSetStepFreq.disconnect()
        self.sigSetStepVoltage.disconnect()
        self.sigSetOffsetVoltage.disconnect()
        self.sigStepUp.disconnect()
        self.sigStepDown.disconnect()
        self.sigStop.disconnect()

        self._save_window_geometry(self._mw)
        self._mw.close()

    def show(self):
        """ Make sure that the window is visible and at the top. """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _values_updated(self, axis, values):
        widget = self._axis_widgets.get(axis)
        if widget is not None:
            if 'mode' in values:
                values['mode'] = self._mode_dict[values['mode']]
            if 'filt' in values:
                values['filt'] = self._filt_dict[values['filt']]
            widget.update_values(values)

    def _limits_updated(self, axis, limits):
        dialog = self._limits_dialogs.get(axis)
        if dialog is not None:
            dialog.update_limits(limits)

    def _activity_changed(self, axis, active):
        widget = self._axis_widgets.get(axis)
        if widget is not None:
            widget.set_locked(active)

    def _show_limits_dialog(self, axis):
        self.sigGetLimits.emit(axis)
        dialog = self._limits_dialogs.get(axis)
        if dialog is not None:
            dialog.show()
            dialog.raise_()


class PositionerLimitsDialog(QtWidgets.QDialog):
    """ Pop-up dialog showing the safety-limit values of a single axis. """

    def __init__(self, axis, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle(f'qudi: Axis {axis} - Safety Limits')
        layout = QtWidgets.QFormLayout()
        self.setLayout(layout)

        self.limit_indicator_label = QtWidgets.QLabel('unknown')
        self.step_freq_limit_label = QtWidgets.QLabel('unknown')
        self.step_voltage_limit_label = QtWidgets.QLabel('unknown')
        self.output_voltage_limit_label = QtWidgets.QLabel('unknown')

        layout.addRow('Safety Limit Reached:', self.limit_indicator_label)
        layout.addRow('Step Frequency Limit:', self.step_freq_limit_label)
        layout.addRow('Step Voltage Limit:', self.step_voltage_limit_label)
        layout.addRow('Output Voltage Limit:', self.output_voltage_limit_label)

        self.close_button = QtWidgets.QPushButton('Close')
        self.close_button.clicked.connect(self.accept)
        layout.addRow(self.close_button)

    def update_limits(self, limits):
        self.limit_indicator_label.setText(str(limits['limit_indicator']))
        self.step_freq_limit_label.setText(str(limits['step_freq_limit']))
        self.step_voltage_limit_label.setText(str(limits['step_voltage_limit']))
        self.output_voltage_limit_label.setText(str(limits['output_voltage_limit']))


class PositionerAxisWidget(QtWidgets.QWidget):
    """ Widget containing all controls for a single positioner axis (one GUI column). """

    sigAcinChanged = QtCore.Signal(str, bool)
    sigDcinChanged = QtCore.Signal(str, bool)
    sigModeChanged = QtCore.Signal(str, str)
    sigFiltChanged = QtCore.Signal(str, str)
    sigStepFreqChanged = QtCore.Signal(str, float)
    sigStepVoltageChanged = QtCore.Signal(str, float)
    sigOffsetVoltageChanged = QtCore.Signal(str, float)
    sigStepUp = QtCore.Signal(str, int)
    sigStepDown = QtCore.Signal(str, int)
    sigStop = QtCore.Signal(str)
    sigLimitsRequested = QtCore.Signal(str)

    def __init__(self, axis, mode_options, filt_options, locked_to_single_step=False,
                *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.axis = axis
        self._locked_to_single_step = locked_to_single_step

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        axis_label = QtWidgets.QLabel(axis)
        axis_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = axis_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        axis_label.setFont(font)
        layout.addWidget(axis_label)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.acin_switch = ToggleSwitch(state_names=('OFF', 'ON'))
        self.acin_switch.sigStateChanged.connect(
            lambda state: self.sigAcinChanged.emit(self.axis, state == 'ON')
        )
        form.addRow('ACIN:', self.acin_switch)

        self.dcin_switch = ToggleSwitch(state_names=('OFF', 'ON'))
        self.dcin_switch.sigStateChanged.connect(
            lambda state: self.sigDcinChanged.emit(self.axis, state == 'ON')
        )
        form.addRow('DCIN:', self.dcin_switch)

        self.mode_combobox = QtWidgets.QComboBox()
        self.mode_combobox.addItems(mode_options)
        self.mode_combobox.currentTextChanged.connect(
            lambda text: self.sigModeChanged.emit(self.axis, text)
        )
        form.addRow('Mode:', self.mode_combobox)

        self.filt_combobox = QtWidgets.QComboBox()
        self.filt_combobox.addItems([str(f) for f in filt_options])
        self.filt_combobox.currentTextChanged.connect(
            lambda text: self.sigFiltChanged.emit(self.axis, text)
        )
        form.addRow('Filter:', self.filt_combobox)

        self.cap_label = QtWidgets.QLabel('unknown')
        form.addRow('Capacitance:', self.cap_label)

        self.step_freq_spinbox = QtWidgets.QDoubleSpinBox()
        self.step_freq_spinbox.setRange(1, 10000)
        self.step_freq_spinbox.setSuffix(' Hz')
        self.step_freq_spinbox.editingFinished.connect(
            lambda: self.sigStepFreqChanged.emit(self.axis, self.step_freq_spinbox.value())
        )
        form.addRow('Step Frequency:', self.step_freq_spinbox)

        self.step_voltage_spinbox = QtWidgets.QDoubleSpinBox()
        self.step_voltage_spinbox.setRange(0, 150)
        self.step_voltage_spinbox.setSuffix(' V')
        self.step_voltage_spinbox.editingFinished.connect(
            lambda: self.sigStepVoltageChanged.emit(self.axis, self.step_voltage_spinbox.value())
        )
        form.addRow('Step Voltage:', self.step_voltage_spinbox)

        self.offset_voltage_spinbox = QtWidgets.QDoubleSpinBox()
        self.offset_voltage_spinbox.setRange(0, 150)
        self.offset_voltage_spinbox.setSuffix(' V')
        self.offset_voltage_spinbox.editingFinished.connect(
            lambda: self.sigOffsetVoltageChanged.emit(self.axis, self.offset_voltage_spinbox.value())
        )
        form.addRow('Offset Voltage:', self.offset_voltage_spinbox)

        self.output_voltage_label = QtWidgets.QLabel('unknown')
        form.addRow('Output Voltage:', self.output_voltage_label)

        self.activity_label = QtWidgets.QLabel('idle')
        form.addRow('Activity:', self.activity_label)

        step_group = QtWidgets.QGroupBox('Step')
        step_layout = QtWidgets.QFormLayout()
        step_group.setLayout(step_layout)
        layout.addWidget(step_group)

        self.n_steps_spinbox = QtWidgets.QSpinBox()
        self.n_steps_spinbox.setRange(1, 1000000)
        self.n_steps_spinbox.setValue(1)
        step_layout.addRow('Number of Steps:', self.n_steps_spinbox)
        if self._locked_to_single_step:
            self.n_steps_spinbox.setValue(1)
            self.n_steps_spinbox.setEnabled(False)

        self.step_up_button = QtWidgets.QPushButton('Step Up')
        self.step_up_button.setCheckable(True)
        self.step_up_button.toggled.connect(self._step_up_toggled)
        step_layout.addRow(self.step_up_button)

        self.step_down_button = QtWidgets.QPushButton('Step Down')
        self.step_down_button.setCheckable(True)
        self.step_down_button.toggled.connect(self._step_down_toggled)
        step_layout.addRow(self.step_down_button)

        self.stop_button = QtWidgets.QPushButton('Stop')
        layout.addWidget(self.stop_button)
        self.stop_button.clicked.connect(lambda: self.sigStop.emit(self.axis))

        self.limits_button = QtWidgets.QPushButton('Safety Limits...')
        self.limits_button.clicked.connect(lambda: self.sigLimitsRequested.emit(self.axis))
        layout.addWidget(self.limits_button)

        layout.addStretch(1)

        self._input_widgets = (
            self.acin_switch, self.dcin_switch, self.mode_combobox, self.filt_combobox,
            self.step_freq_spinbox, self.step_voltage_spinbox, self.offset_voltage_spinbox,
            self.n_steps_spinbox, self.step_up_button, self.step_down_button
        )

    def _step_up_toggled(self, checked):
        if checked:
            if self.n_steps_spinbox.value() >= 1:
                self.sigStepUp.emit(self.axis, self.n_steps_spinbox.value())
            self.step_up_button.setChecked(False)

    def _step_down_toggled(self, checked):
        if checked:
            if self.n_steps_spinbox.value() >= 1:
                self.sigStepDown.emit(self.axis, self.n_steps_spinbox.value())
            self.step_down_button.setChecked(False)

    def set_locked(self, locked):
        """ Lock/unlock all inputs except the stop button, e.g. while the axis is active. """
        for widget in self._input_widgets:
            if self._locked_to_single_step and widget is self.n_steps_spinbox:
                continue
            widget.setEnabled(not locked)
        self.activity_label.setText('active' if locked else 'idle')

    def update_values(self, values):
        if 'acin' in values:
            if type(values['acin']) is str:
                val = True if values['acin'] == 'ON' else False
            else:
                val = bool(values['acin'])
            self.acin_switch.setChecked(val)
        if 'dcin' in values:
            if type(values['dcin']) is str:
                val = True if values['dcin'] == 'ON' else False
            else:
                val = bool(values['dcin'])
            self.dcin_switch.setChecked(val)
        if 'mode' in values:
            self.mode_combobox.setCurrentText(str(values['mode']))
        if 'filt' in values:
            self.filt_combobox.setCurrentText(str(values['filt']))
        if 'cap' in values:
            self.cap_label.setText(str(values['cap']))
        if 'step_freq' in values:
            self.step_freq_spinbox.setValue(float(values['step_freq']))
        if 'step_voltage' in values:
            self.step_voltage_spinbox.setValue(float(values['step_voltage']))
        if 'offset_voltage' in values:
            self.offset_voltage_spinbox.setValue(float(values['offset_voltage']))
        if 'output_voltage' in values:
            self.output_voltage_label.setText(str(values['output_voltage']))


class PositionerMainWindow(QtWidgets.QMainWindow):
    """ Main window for the PositionerGui module. """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('qudi: Attocube ANC300 Positioner')

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout()
        central_widget.setLayout(main_layout)

        self.axes_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(self.axes_layout)

        self.update_button = QtWidgets.QPushButton('Update All')
        main_layout.addWidget(self.update_button)
