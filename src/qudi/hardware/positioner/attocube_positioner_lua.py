# -*- coding: utf-8 -*-

"""
This module controls the Attocube ANC300 positioner controller
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

from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.interface.positioner_interface import PositionerInterface


class AttocubeANC300(PositionerInterface):
    """ Hardware module for Attocube ANC300 positioner controller
    Example config for copy-paste:

    anc300:
        module.Class: 'positioner.AttocubeANC300'
        options:
            ip_address: 
            port: 7231 #Optional, default is 7231 for LUA port
    """
    _ip_address = ConfigOption('ip_address', missing='error')
    _port = ConfigOption('port', default=7231)

    # axis-name to controller-slot mapping, configurable per unit
    _axis_dict = ConfigOption('axis_dict', default={'X': 3, 'Y': 2, 'Z': 1})
    _restrict_z = ConfigOption('restrict_z', default=True)

    EOL = '\r\n'

    mode_options = ('GND', 'INP', 'CAP', 'STP', 'OSV', 'STPP', 'STPM')
    mode_options_labels = ('Ground', 'Input', 'Capacitance', 'Step', 'Offset', 'Step + Offset', 'Step - Offset')
    filt_options = (0, 1, 2)  #, 3
    filt_options_labels = ('OFF', '16 Hz', '160 Hz')  #AMN300 Options
    #filt_options_labels = ('1600 Hz', '160 Hz', '16 Hz', '1.6 Hz')  #AMN200 Options
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._axis_dict_rev = dict()

    def on_activate(self):
        """ Activate module.
        """
        self._anc300.open()
        self._available_axes = set(self._axis_dict.values())  # TODO Get Available from device.

        self._axis_dict = dict(self._axis_dict)
        axis_dict_new = {}
        for label, axis in self._axis_dict.items():
            if axis not in self._available_axes:
                self.log.warning(f"Axis {label} (slot {axis}) is not available on the device. Removing from axis_dict.")
            else:
                axis_dict_new[label] = axis
        for axis in self._available_axes:
            if axis not in self._axis_dict.values():
                axis_dict_new[str(axis)] = axis
        self._axis_dict = axis_dict_new
        self._axis_dict_rev = {v: k for k, v in self._axis_dict.items()}


    def on_deactivate(self):
        """ Deactivate module.
        """
        self._anc300.close()

    @property
    def axis_names(self):
        """ Names of the configured axes in definition order. """
        return tuple(self._axis_dict.keys())

    @property
    def restrict_z(self):
        """ Whether the Z axis is restricted to single steps for safety reasons. """
        return self._restrict_z

    def _validate_axis(self, axis):
        '''
        Checks if axis is available in axis_dict or available_axes, and returns the corresponding number.
        '''
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


    def _query(self, prop):
        """ Query a property. """
        self._anc300.flush_read()
        self._anc300.write(f'print({prop})' + self.EOL)
        ret = self._anc300.read_until(self.EOL)
        return ret.strip()

    def _set_and_check(self, prop, value):
        """ Set a command and check the result. """
        self._anc300.write(f'{prop}={value}' + self.EOL)
        #if err is not None:
        #    raise Exception(f'Error in communication: {err}')
        return self._query(prop)



    #Device commands
    def set_acin(self,axis, value):
        """ Set the ACIN value for a given axis, ON or OFF, or bool. """
        if type(value) is bool:
            value = 'ON' if value else 'OFF'
        if value not in ['ON','OFF']:
            raise ValueError(f"Invalid value for ACIN: {value}. Must be 'ON' or 'OFF', or bool.")

        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.acin', value)

    def get_acin(self,axis):
        """ Get the ACIN value for a given axis, ON or OFF, or bool. """
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.acin') #Returns int, 0 or 1
        return ['OFF','ON'][int(ret)]

    def set_dcin(self,axis, value):
        """ Set the DCIN value for a given axis, ON or OFF, or bool. """
        if type(value) is bool:
            value = 'ON' if value else 'OFF'
        if value not in ['ON','OFF']:
            raise ValueError(f"Invalid value for DCIN: {value}. Must be 'ON' or 'OFF', or bool.")

        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.dcin', value)

    def get_dcin(self,axis):
        """ Get the DCIN value for a given axis, ON or OFF, or bool. """
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.dcin')  #Returns int, 0 or 1
        return ['OFF','ON'][int(ret)]

    def set_mode(self,axis, value):
        """ 
        Set the MODE value for a given axis: 
        GND : Ground
        INP : Input
        CAP : Capacitance
        STP : Step
        OSV : Offset
        STPP : Offset + step
        STPM : Offset - step
        """
        if value in self.mode_options_labels:
            value = self.mode_options[self.mode_options_labels.index(value)]
        if value not in self.mode_options:
            raise ValueError(f"Invalid value for MODE: {value}. Must be in {self.mode_options}.")

        axis = self._validate_axis(axis)
        ret = self._set_and_check(f'm{axis}.mode', value)
        return str(ret)

    def get_mode(self,axis):
        """ 
        Get the MODE value for a given axis: 
        GND : Ground
        INP : Input
        CAP : Capacitance
        STP : Step
        OSV : Offset
        STPP : Offset + step
        STPM : Offset - step
        """
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.mode')
        return int(ret)

    def set_filt(self,axis, value):
        """ Set the FILTER value for a given axis: 0, 1, 2, 3, 4
        Setting  ANM200   ANM300
        0        1600 Hz  Off
        1        160 Hz   16 Hz
        2        16 Hz    160 Hz
        3        1.6 Hz   Off
        4,5,..   1600 Hz  Off
        """
        if value in self.filt_options_labels:
            value = self.filt_options[self.filt_options_labels.index(value)]
        if value not in self.filt_options:
            raise ValueError(f"Invalid value for FILTER: {value}. Must be in {self.filt_options}.")

        axis = self._validate_axis(axis)
        ret = self._set_and_check(f'm{axis}.filt', value)
        return int(ret)

    def get_filt(self,axis):
        """ Get the FILTER value for a given axis:
        Setting  ANM200   ANM300
        0        1600 Hz  Off
        1        160 Hz   16 Hz
        2        16 Hz    160 Hz
        3        1.6 Hz   Off
        >=4      1600 Hz  Off
        """
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.filt')
        return int(ret)

    def get_cap(self,axis): #TODO Check if this measures or just reports.
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.cap')
        return float(ret)

    def set_step_freq(self,axis,value):
        """ Set the step frequency, from 0 to 10000 Hz"""
        if (value<1) or (value>10000):
            raise ValueError(f'Frequency not in range 1-10000 Hz: {value}')
        axis=self._validate_axis(axis)
        ret = self._set_and_check(f'm{axis}.frq', value)
        return float(ret)

    def get_step_freq(self,axis):
        """ Get the step frequency, from 1 to 10000 Hz"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.frq')
        return float(ret)

    def set_step_voltage(self,axis,value):
        """ Set the step voltage, from 0 to 150 V"""
        if (value<0) or (value>150):
            raise ValueError(f'Voltage not in range 0-150 V: {value}')
        axis=self._validate_axis(axis)
        ret = self._set_and_check(f'm{axis}.stp', value)
        return float(ret)
    
    def get_step_voltage(self,axis):
        """ Get the step voltage, from 0 to 150 V"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.stp')
        return float(ret)
    
    def set_offset_voltage(self,axis,value):
        """ Set the offset voltage, from 0 to 150 V"""
        if (value<0) or (value>150):
            raise ValueError(f'Voltage not in range  0-150 V: {value}')
        axis=self._validate_axis(axis)
        ret = self._set_and_check(f'm{axis}.osv', value)
        return float(ret)
    
    def get_offset_voltage(self,axis):
        """ Get the step voltage, from 0 to 150 V"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.osv')
        return float(ret)

    def get_output_voltage(self,axis):
        """ Get the output voltage"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.out')
        return float(ret)

    def get_activity_indicator(self,axis):
        """ Get the activity indicator status"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.act')
        return bool(ret)

    def get_limit_indicator(self,axis):
        """ Get the safety limit indicator status"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.safe')
        return bool(ret)

    def get_step_frequency_limit(self,axis):
        """ Get the step frequency limit value"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.frqlimit')
        return bool(ret)

    def get_step_voltage_limit(self,axis):
        """ Get the step voltage limit value"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.stplimit')
        return bool(ret)

    def get_output_voltage_limit(self,axis):
        """ Get the output voltage limit value"""
        axis = self._validate_axis(axis)
        ret = self._query(f'm{axis}.outlimit')
        return bool(ret)

    def trigger_up(self,axis,value):
        """ Trigger input up for a given axis, value in range 1-7 """
        raise NotImplementedError("trigger_up is not tested yet.")
        if type(value) is not int:
            raise ValueError(f'Trigger value must be an integer: {value}')
        if (value<1) or (value>7):
            raise ValueError(f'Trigger value not in range 1-7: {value}')
        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.trigu', value)

    def trigger_down(self,axis,value):
        raise NotImplementedError("trigger_down is not tested yet.")
        """ Trigger input down for a given axis, value in range 1-7 """
        if type(value) is not int:
            raise ValueError(f'Trigger value must be an integer: {value}')
        if (value<1) or (value>7):
            raise ValueError(f'Trigger value not in range 1-7: {value}')
        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.trigd', value)

    def set_pattern_up(self,axis,values):
        """ Set the step-voltage pattern for a given axis, with an list of 256 int values from 0-255 """
        raise NotImplementedError("set_pattern_up is not tested yet.")
        if type(values) is not list:
            raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        if len(values) != 256:
            raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        for v in values:
            if (v<0) or (v>255):
                raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.patu', ','.join(map(str,values)))

    def set_pattern_down(self,axis,values):
        """ Set the step-voltage pattern for a given axis, with an list of 256 int values from 0-255 """
        raise NotImplementedError("set_pattern_down is not tested yet.")
        if type(values) is not list:
            raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        if len(values) != 256:
            raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        for v in values:
            if (v<0) or (v>255):
                raise ValueError(f'Step-voltage pattern must be a list of 256 int values from 0-255: {values}')
        axis = self._validate_axis(axis)
        return self._set_and_check(f'm{axis}.patd', ','.join(map(str,values)))
        
    def step_up(self,axis, n_steps):
        #TODO Verify nothing is returned
        """ Move the specified axis up by the given number of steps. """
        if type(n_steps) is not int:
            raise ValueError(f'Number of steps must be an integer: {n_steps}')
        if n_steps < 1:
            raise ValueError(f'Number of steps must be a positive integer: {n_steps}')
        axis = self._validate_axis(axis)
        if self._restrict_z and axis == self._validate_axis('Z') and n_steps > 1:
            raise ValueError(f'Stepping Z axis is restricted single-steps for safety reasons.')
        self._anc300.write(f'm{axis}:step(UP,{n_steps})')

    def step_down(self,axis, n_steps):
        #TODO Verify nothing is returned
        """ Move the specified axis down by the given number of steps. """
        if type(n_steps) is not int:
            raise ValueError(f'Number of steps must be an integer: {n_steps}')
        if n_steps < 1:
            raise ValueError(f'Number of steps must be a positive integer: {n_steps}')
        axis = self._validate_axis(axis)
        if self._restrict_z and axis == self._validate_axis('Z') and n_steps > 1:
            raise ValueError(f'Stepping Z axis is restricted single-steps for safety reasons.')
        self._anc300.write(f'm{axis}:step(DOWN,{n_steps})')

    def stop(self,axis):
        #TODO Verify nothing is returned
        """ Stop motion on axis """
        axis = self._validate_axis(axis)
        self._anc300.write(f'm{axis}:stop()')

    def wait(self,axis):
        """ Wait for action to complete on axis """
        raise NotImplementedError #Need to figure out how this works to be blocking.
        axis = self._validate_axis(axis)
        self._anc300.write(f'm{axis}:wait()')

    