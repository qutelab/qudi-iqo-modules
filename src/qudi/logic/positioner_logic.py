# -*- coding: utf-8 -*-

"""
Logic module for controlling the Attocube ANC300 positioner.

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

from PySide6 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.positioner_interface import PositionerInterface


class PositionerLogic(LogicBase):
    """ Logic module to interact with the Attocube ANC300 positioner hardware.

    Example config for copy-paste:

    positioner_logic:
        module.Class: 'positioner_logic.PositionerLogic'
        options:
            poll_interval: 0.5  # optional, in seconds
        connect:
            positioner: positioner_dummy
    """

    _positioner = Connector(name='positioner', interface=PositionerInterface)

    _poll_interval = ConfigOption(name='poll_interval', default=0.5, missing='nothing')

    

    sigValuesUpdated = QtCore.Signal(str, dict)
    sigLimitsUpdated = QtCore.Signal(str, dict)
    sigActivityChanged = QtCore.Signal(str, bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._poll_interval_ms = 0
        self._poll_active = False
        self._axis_activity = dict()

    def on_activate(self):
        """ Activate module. """
        self._poll_interval_ms = int(round(self._poll_interval * 1000))
        self._axis_activity = {axis: False for axis in self.axis_names}
        self._poll_active = True
        QtCore.QMetaObject.invokeMethod(self, '_poll_activity_body',
                                        QtCore.Qt.ConnectionType.QueuedConnection)

        self.mode_options = self._positioner().mode_options
        self.mode_options_labels = self._positioner().mode_options_labels
        self.filt_options = self._positioner().filt_options
        self.filt_options_labels = self._positioner().filt_options_labels


    def on_deactivate(self):
        """ Deactivate module. """
        self._poll_active = False

    @property
    def axis_names(self):
        """ Names of the configured axes in definition order. """
        return self._positioner().axis_names

    @property
    def restrict_z(self):
        """ Whether the Z axis is restricted to single steps for safety reasons. """
        return self._positioner().restrict_z

    @QtCore.Slot(str)
    def get_values(self, axis):
        """ Query all non-limit get-functions for a single axis and emit the result.

        @param str axis: name of the axis to query
        """
        hw = self._positioner()
        with self._thread_lock:
            values = {
                'acin': hw.get_acin(axis),
                'dcin': hw.get_dcin(axis),
                'mode': hw.get_mode(axis),
                'filt': hw.get_filt(axis),
                'cap': hw.get_cap(axis),
                'step_freq': hw.get_step_freq(axis),
                'step_voltage': hw.get_step_voltage(axis),
                'offset_voltage': hw.get_offset_voltage(axis),
                'output_voltage': hw.get_output_voltage(axis),
            }
        self.sigValuesUpdated.emit(axis, values)
        return values

    @QtCore.Slot()
    def update_all_values(self):
        """ Query all non-limit get-functions for every configured axis. """
        for axis in self.axis_names:
            try:
                self.get_values(axis)
            except:
                self.log.exception(f'Error while updating values for axis "{axis}".')

    @QtCore.Slot(str)
    def get_limits(self, axis):
        """ Query the safety-limit related get-functions for a single axis and emit the result.

        @param str axis: name of the axis to query
        """
        hw = self._positioner()
        with self._thread_lock:
            limits = {
                'limit_indicator': hw.get_limit_indicator(axis),
                'step_freq_limit': hw.get_step_frequency_limit(axis),
                'step_voltage_limit': hw.get_step_voltage_limit(axis),
                'output_voltage_limit': hw.get_output_voltage_limit(axis),
            }
        self.sigLimitsUpdated.emit(axis, limits)
        return limits

    @QtCore.Slot(str, bool)
    def set_acin(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_acin(axis, value)
        self.sigValuesUpdated.emit(axis, {'acin': value})

    @QtCore.Slot(str, bool)
    def set_dcin(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_dcin(axis, value)
        self.sigValuesUpdated.emit(axis, {'dcin': value})

    @QtCore.Slot(str, str)
    def set_mode(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_mode(axis, value)
        self.sigValuesUpdated.emit(axis, {'mode': value})

    @QtCore.Slot(str, object)  #Accepts int or float
    def set_filt(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_filt(axis, value)
        self.sigValuesUpdated.emit(axis, {'filt': value})

    @QtCore.Slot(str, float)
    def set_step_freq(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_step_freq(axis, value)
        self.sigValuesUpdated.emit(axis, {'step_freq': value})

    @QtCore.Slot(str, float)
    def set_step_voltage(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_step_voltage(axis, value)
        self.sigValuesUpdated.emit(axis, {'step_voltage': value})

    @QtCore.Slot(str, float)
    def set_offset_voltage(self, axis, value):
        with self._thread_lock:
            value = self._positioner().set_offset_voltage(axis, value)
        self.sigValuesUpdated.emit(axis, {'offset_voltage': value})

    @QtCore.Slot(str, int)
    def step_up(self, axis, n_steps):
        with self._thread_lock:
            self._positioner().step_up(axis, n_steps)

    @QtCore.Slot(str, int)
    def step_down(self, axis, n_steps):
        with self._thread_lock:
            self._positioner().step_down(axis, n_steps)

    @QtCore.Slot(str)
    def stop(self, axis):
        with self._thread_lock:
            self._positioner().stop(axis)

    @QtCore.Slot()
    def _poll_activity_body(self):
        """ Regularly poll the activity indicator of every axis and emit changes. """
        with self._thread_lock:
            if self._poll_active:
                hw = self._positioner()
                for axis in self.axis_names:
                    try:
                        active = bool(hw.get_activity_indicator(axis))
                        output = hw.get_output_voltage(axis)
                        self.sigValuesUpdated.emit(axis, {'output_voltage': output})
                    except:
                        self.log.exception(f'Error while polling activity of axis "{axis}".')
                        continue
                    if active != self._axis_activity.get(axis):
                        self._axis_activity[axis] = active
                        self.sigActivityChanged.emit(axis, active)
                QtCore.QTimer.singleShot(self._poll_interval_ms, self._poll_activity_body)
