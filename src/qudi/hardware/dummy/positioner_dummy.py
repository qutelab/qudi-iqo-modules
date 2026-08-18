# -*- coding: utf-8 -*-

"""
This module is a dummy positioner hardware module, simulating an Attocube-like
stepper positioner for testing the GUI/logic layers without real hardware.
Written by Adam Mayer (2026), University of Calgary QuTe Lab.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import time

from qudi.core.configoption import ConfigOption
from qudi.interface.positioner_interface import PositionerInterface


class PositionerDummy(PositionerInterface):
    """ Dummy hardware module simulating the Attocube ANC300 positioner.

    Example config for copy-paste:

    positioner_dummy:
        module.Class: 'dummy.positioner_dummy.PositionerDummy'
        options:
            axis_dict:
                X: 3
                Y: 2
                Z: 1
            restrict_z: True
    """

    _axis_dict = ConfigOption('axis_dict', default={'X': 3, 'Y': 2, 'Z': 1})
    _restrict_z = ConfigOption('restrict_z', default=True)

    mode_options = ('GND', 'INP', 'CAP', 'STP', 'OSV', 'STPP', 'STPM')
    mode_options_labels = ('Ground', 'Input', 'Capacitance', 'Step', 'Offset', 'Step + Offset', 'Step - Offset')
    filt_options = (0, 1, 2)  #, 3
    filt_options_labels = ('OFF', '16 Hz', '160 Hz')  #AMN300 Options

    _CAPACITANCE_NF = 750.0
    _FREQ_LIMIT_HZ = 10000
    _VOLTAGE_LIMIT_V = 150



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._acin = dict()
        self._dcin = dict()
        self._mode = dict()
        self._filt = dict()
        self._step_freq = dict()
        self._step_voltage = dict()
        self._offset_voltage = dict()
        self._t_act_start = dict()
        self._t_act_duration = dict()
        self._t_act_bool = dict()

    def on_activate(self):
        """ Activate module. """
        self._axis_dict = dict(self._axis_dict)
        self._available_axes = set(self._axis_dict.values())
        for axis in self._axis_dict.values():
            self._acin[axis] = False
            self._dcin[axis] = False
            self._mode[axis] = 'GND'
            self._filt[axis] = 0
            self._step_freq[axis] = 100.0
            self._step_voltage[axis] = 30.0
            self._offset_voltage[axis] = 0.0
            self._t_act_start[axis] = 0.0
            self._t_act_duration[axis] = 0.0
            self._t_act_bool[axis] = False

    def on_deactivate(self):
        """ Deactivate module. """
        pass

    @property
    def axis_names(self):
        """ Names of the configured axes in definition order. """
        return tuple(self._axis_dict.keys())

    @property
    def restrict_z(self):
        """ Whether the Z axis is restricted to single steps for safety reasons. """
        return self._restrict_z

    def _validate_axis(self, axis):
        if type(axis) is str:
            axis = axis.upper()
            if axis not in self._axis_dict:
                raise ValueError(f"Invalid axis: {axis}. Must be one of {list(self._axis_dict.keys())}")
            axis = self._axis_dict[axis]
        if type(axis) is int:
            if axis not in self._available_axes:
                raise ValueError(f"Invalid axis: {axis}. Must be one of {list(self._available_axes)}")
            return axis
        else:
            raise ValueError(f"Invalid axis: {axis}. Must be a string or an integer.")

    #Device commands
    def set_acin(self, axis, value):
        """ Set the ACIN value for a given axis, ON or OFF, or bool. """
        if type(value) is bool:
            value = 'ON' if value else 'OFF'
        if value not in ['ON', 'OFF']:
            raise ValueError(f"Invalid value for ACIN: {value}. Must be 'ON' or 'OFF', or bool.")
        axis = self._validate_axis(axis)
        self._acin[axis] = value == 'ON'
        print(f'[PositionerDummy] m{axis}.acin = {value}')
        return value

    def get_acin(self, axis):
        """ Get the ACIN value for a given axis. """
        axis = self._validate_axis(axis)
        return self._acin[axis]

    def set_dcin(self, axis, value):
        """ Set the DCIN value for a given axis, ON or OFF, or bool. """
        if type(value) is bool:
            value = 'ON' if value else 'OFF'
        if value not in ['ON', 'OFF']:
            raise ValueError(f"Invalid value for DCIN: {value}. Must be 'ON' or 'OFF', or bool.")
        axis = self._validate_axis(axis)
        self._dcin[axis] = value == 'ON'
        print(f'[PositionerDummy] m{axis}.dcin = {value}')
        return value

    def get_dcin(self, axis):
        """ Get the DCIN value for a given axis. """
        axis = self._validate_axis(axis)
        return self._dcin[axis]

    def set_mode(self, axis, value):
        """ Set the MODE value for a given axis. """
        if value in self.mode_options_labels:
            value = self.mode_options[self.mode_options_labels.index(value)]
        if value not in self.mode_options:
            raise ValueError(f"Invalid value for MODE: {value}. Must be in {self.mode_options}.")
        axis = self._validate_axis(axis)
        self._mode[axis] = value
        print(f'[PositionerDummy] m{axis}.mode = {value}')
        return value

    def get_mode(self, axis):
        """ Get the MODE value for a given axis. """
        axis = self._validate_axis(axis)
        return self._mode[axis]

    def set_filt(self, axis, value):
        """ Set the FILTER value for a given axis: 0, 1, 2, 3, 4 """
        if value in self.filt_options_labels:
            value = self.filt_options[self.filt_options_labels.index(value)]
        if value not in self.filt_options:
            raise ValueError(f"Invalid value for FILT: {value}. Must be in {self.filt_options}.")
        axis = self._validate_axis(axis)
        self._filt[axis] = value
        print(f'[PositionerDummy] m{axis}.filt = {value}')
        return value

    def get_filt(self, axis):
        """ Get the FILTER value for a given axis. """
        axis = self._validate_axis(axis)
        return self._filt[axis]

    def get_cap(self, axis):
        """ Get the (fixed dummy) capacitance reading in nF. """
        axis = self._validate_axis(axis)
        return self._CAPACITANCE_NF

    def set_step_freq(self, axis, value):
        """ Set the step frequency, from 1 to 10000 Hz """
        if (value < 1) or (value > 10000):
            raise ValueError(f'Frequency not in range 1-10000 Hz: {value}')
        axis = self._validate_axis(axis)
        value = round(value,1)
        self._step_freq[axis] = value
        print(f'[PositionerDummy] m{axis}.stepfreq = {value}')
        return value

    def get_step_freq(self, axis):
        """ Get the step frequency, from 1 to 10000 Hz """
        axis = self._validate_axis(axis)
        return self._step_freq[axis]

    def set_step_voltage(self, axis, value):
        """ Set the step voltage, from 0 to 150 V """
        if (value < 0) or (value > 150):
            raise ValueError(f'Voltage not in range 0-150 V: {value}')
        axis = self._validate_axis(axis)
        value = round(value, 1)
        self._step_voltage[axis] = value
        print(f'[PositionerDummy] m{axis}.stp = {value}')
        return value

    def get_step_voltage(self, axis):
        """ Get the step voltage, from 0 to 150 V """
        axis = self._validate_axis(axis)
        return self._step_voltage[axis]

    def set_offset_voltage(self, axis, value):
        """ Set the offset voltage, from 0 to 150 V """
        if (value < 0) or (value > 150):
            raise ValueError(f'Voltage not in range 0-150 V: {value}')
        axis = self._validate_axis(axis)
        value = round(value, 1)
        self._offset_voltage[axis] = value
        print(f'[PositionerDummy] m{axis}.osv = {value}')
        return value

    def get_offset_voltage(self, axis):
        """ Get the offset voltage, from 0 to 150 V """
        axis = self._validate_axis(axis)
        return self._offset_voltage[axis]

    def get_output_voltage(self, axis):
        """ Get the output voltage: offset voltage, plus step voltage while active. """
        axis = self._validate_axis(axis)
        output = self._offset_voltage[axis]
        if self.get_activity_indicator(axis):
            output += self._step_voltage[axis]
        return output

    def get_activity_indicator(self, axis):
        """ Get the activity indicator status.

        True while a step motion is in progress, i.e. while the simulated
        step duration (n_steps / step_freq at the time of the step call) has not yet elapsed.
        """
        axis = self._validate_axis(axis)
        if self._t_act_bool[axis]:
            if time.time() < (self._t_act_start[axis] + self._t_act_duration[axis]):
                return True
            self._t_act_bool[axis] = False
        return False

    def get_limit_indicator(self, axis):
        """ Get the (fixed dummy) safety limit indicator status. """
        axis = self._validate_axis(axis)
        return False

    def get_step_frequency_limit(self, axis):
        """ Get the (fixed dummy) step frequency limit value. """
        axis = self._validate_axis(axis)
        return self._FREQ_LIMIT_HZ

    def get_step_voltage_limit(self, axis):
        """ Get the (fixed dummy) step voltage limit value. """
        axis = self._validate_axis(axis)
        return self._VOLTAGE_LIMIT_V

    def get_output_voltage_limit(self, axis):
        """ Get the (fixed dummy) output voltage limit value. """
        axis = self._validate_axis(axis)
        return self._VOLTAGE_LIMIT_V

    def step_up(self, axis, n_steps):
        """ Move the specified axis up by the given number of steps. """
        if type(n_steps) is not int:
            raise ValueError(f'Number of steps must be an integer: {n_steps}')
        if n_steps < 1:
            raise ValueError(f'Number of steps must be a positive integer: {n_steps}')
        axis = self._validate_axis(axis)
        if self._restrict_z and axis == self._validate_axis('Z') and n_steps > 1:
            raise ValueError(f'Stepping Z axis is restricted single-steps for safety reasons.')
        self._t_act_start[axis] = time.time()
        self._t_act_duration[axis] = n_steps / self._step_freq[axis]
        self._t_act_bool[axis] = True
        print(f'[PositionerDummy] m{axis}:step(UP,{n_steps})')

    def step_down(self, axis, n_steps):
        """ Move the specified axis down by the given number of steps. """
        if type(n_steps) is not int:
            raise ValueError(f'Number of steps must be an integer: {n_steps}')
        if n_steps < 1:
            raise ValueError(f'Number of steps must be a positive integer: {n_steps}')
        axis = self._validate_axis(axis)
        if self._restrict_z and axis == self._validate_axis('Z') and n_steps > 1:
            raise ValueError(f'Stepping Z axis is restricted single-steps for safety reasons.')
        self._t_act_start[axis] = time.time()
        self._t_act_duration[axis] = n_steps / self._step_freq[axis]
        self._t_act_bool[axis] = True
        print(f'[PositionerDummy] m{axis}:step(DOWN,{n_steps})')

    def stop(self, axis):
        """ Stop motion on axis. """
        axis = self._validate_axis(axis)
        self._t_act_bool[axis] = False
        print(f'[PositionerDummy] m{axis}:stop()')
