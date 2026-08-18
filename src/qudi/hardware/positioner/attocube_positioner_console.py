# -*- coding: utf-8 -*-

"""
This module controls spectrometers from Andor Shamrock
Written by Adam Mayer (2026), University of Calgary QuTe Lab, based on pylablib and pyandor.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.interface.positioner_interface import PositionerInterface


from pylablib.devices import Attocube


class AttocubeANC300(PositionerInterface):
    """ Hardware module for reading spectra from the Andor Shamrock+DU401A spectrometer.
    This depends on the camera module (DU401A), so make sure to set defaults there too.
    Example config for copy-paste:

    myspectrometer:
        module.Class: 'positioner.attocube_positioner.AttocubeANC300'
        options:
            ip_address: '192.168.X.X'
            axis_labels : # Assigned labels cannot be int, as these are reserved for looking up axis directly by index.
                1 : Z
                2 : Y
                3 : X
            calibration_um :  # um per step for each axis, (+, -) if different. Use either axis label or axis index.
                X : 500
                Y : (450,650)
                Z : (350,550)
            restrict_z : True  # Allow only single-stepping for Z, requires one axis to be labeled "Z"


    """
    _ip_address = ConfigOption('ip_address', missing='error')
    _axis_labels = ConfigOption('axis_labels', default='')
    _calibration_um = ConfigOption('calibration_um', default='')
    _restrict_z = ConfigOption('restrict_z', default='')

    #Status vars
    _current_pos = StatusVar('current_pos',default={})

    #Placeholder vars
    _capacitance = {}



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #Check config
        self._axis_label_dict = {}  #Reverse dict
        for idx,value in self._axis_labels.items():
            if type(idx) is not int:
                raise ValueError('For axis_labels, first entry should be int representing index')
            if type(value) is int:
                raise ValueError('For axis_labels, second entry should NOT be int, as int represents index')
            if value in self._axis_label_dict:
                raise ValueError(f'Duplicate entry found in _axis_labels: {value}')
            self._axis_label_dict[value]=idx

        calNew = {}  #Convert to using index if labels were used in config.
        for idx,value in self._calibration_um.items():
            if type(value) not in (list,tuple):
                self._calibration_um[idx] = (value,value)
            if type(idx) is int:  #Lookup by either index or label.
                calNew[idx] = self._calibration_um[idx]
            else:
                calNew[self.parse_axis(idx)] = self._calibration_um[idx]
        self._calibration_um = calNew

        self._restrict_axis = None
        if self._restrict_z:
            for idx,value in self._axis_labels.items():
                if value=='Z':
                    self._restrict_axis = idx
                    break
            if self._restrict_axis == None:
                self.log.error('Unable to restrict z-axis, no matching label found')


        



    def on_activate(self):
        """ Activate module.
        """
        self._anc300 = Attocube.ANC300(self._ip_address)
        self._available_axes = self._anc300.update_available_axes()
        for axis in self._available_axes:
            if axis not in self._axis_labels:
                self._axis_labels[axis] = str(axis)
                self._axis_label_dict[str(axis)] = axis


    def on_deactivate(self):
        """ Deactivate module.
        """
        self._anc300.close()


    def parse_axis(self,axis):
        if (type(axis) is int) and (axis in self._available_axes):
            return axis

        elif axis in self._axis_label_dict:
            return self.parse_axis(self._axis_label_dict[axis])

        else:
            raise ValueError(f'Axis not available: {axis}')

    def set_calibration(self,axis,cal):
        self._calibration_um[self.parse_axis(axis)]=cal
        self.log.info("Note: Updated attocube calibration only valid for this session, don't forget to updated the config file")

    def get_calibration(self,axis='all',use_labels=True):
        if axis=='all':
            if use_labels:
                return {self._axis_labels[ax] : value for ax,value in self._calibration_um.items()}
            else:
                return self._calibration_um
        else:
            return self._calibration_um[self.parse_axis(axis)]


    def measure_capacitance(self,axis):
        return self._anc300.get_capacitance(self.parse_axis(axis), measure=True)

    def capacitance(self,axis):
        return self._anc300.get_capacitance(self.parse_axis(axis), measure=False)
    
    def set_mode(self,axis,mode='stp'):
         """
        Set axis mode.

        `axis` is either an axis index (starting from 1), or ``"all"`` (all axes).
        `mode` can be ``"gnd"`` (ground), ``"stp"`` (step), ``"cap"`` (measure capacitance, then ground),
        ``"offs"`` (offset only, no stepping), ``"stp+"`` (offset with added stepping waveform), ``"stp-"`` (offset with subtracted stepping).
        """
         return self._anc300.set_mode(self.parse_axis(axis),mode)

    def get_mode(self,axis):
        """
        Get axis mode.
        """
        return self._anc300.get_mode(self.parse_axis(axis))

    def get_voltage(self, axis="all"):
        """Get axis step amplitude in Volts"""
        return self._anc300.get_voltage(axis)

    def set_voltage(self, axis, voltage):
        """Set axis step amplitude in Volts"""
        return self._anc300.set_voltage(axis, voltage)

    def get_offset(self, axis="all"):
        """Get axis offset voltage in Volts"""
        return self._anc300.get_offset(axis)

    def set_offset(self, axis, voltage):
        """Set axis offset voltage in Volts"""
        return self._anc300.set_offset(axis, voltage)

    def get_output(self, axis="all"):
        """Get axis current output voltage in Volts"""
        return self._anc300.get_output(axis)

    def get_frequency(self, axis="all"):
        """Get axis step frequency in Hz"""
        return self._anc300.get_frequency(axis)

    def set_frequency(self, axis, freq):
        """Set axis step frequency in Hz"""
        return self._anc300.set_frequency(axis, freq)

    def get_external_input_modes(self, axis="all"):
        """
        Get external BNC input modes.

        Return tuple ``(acin, dcin)`` indicating whether AC-IN and DC-IN channels are enabled.
        """
        return self._anc300.get_external_input_modes(axis)

    def set_external_input_modes(self, axis, acin=None, dcin=None):
        """
        Enable or disable external BNC inputs.

        `acin` and `dcin` are can be boolean indicating if the corresponding input is enabled, or ``None`` (keep the value unchanged).
        """
        return self._anc300.set_external_input_modes(axis, acin, dcin)

    def store_move(self,axis,steps):
        axis = self.parse_axis(axis)
        cal = self._calibration_um.get(self._axis_label_dict,(1,1))
        if steps>0:
            self._current_pos[axis] += steps * cal[0]
        if steps<0:
            self._current_pos[axis] += -steps * cal[1]

    def move_by(self, axis, steps=1):
        """Move a given axis for a given number of steps"""
        axis = self.parse_axis(axis)
        if axis==self._restrict_axis and steps>1:
            self.log.warning('Unable to move z-axis more than 1 step at a time, if desired change in config.')
        else:
            self.store_move(axis,steps)
            return self._anc300.move_by(axis, steps)

    def is_moving(self, axis):
        """Check if a given axis is moving"""
        return self._anc300.is_moving(axis)

    def wait_move(self, axis, timeout=30.):
        """
        Wait for a given axis to stop moving.

        If the motion is not finished after `timeout` seconds, raise a backend error.
        """
        return self._anc300.wait_move(axis, timeout)

    def stop(self, axis="all"):
        """Stop motion of a given axis"""
        return self._anc300.stop(axis)

    def move_by_um(self,axis,distance):
        cal = self._calibration_um.get(self.parse_axis(axis),None) 
        if cal is not None:
            moveby = int(distance/cal)
            if moveby:
                self.move_by(axis,moveby)
            else:
                raise ValueError('Move-by distance is less than one step')
        else:
            raise ValueError(f'Cannot move_by_um, axis {axis} has no calibration')

    def current_position(self,axis='all'):
        """
        Returns software-stored position in um if calibration provided, otherwise steps. 
        """
        if axis=='all':
            return self._current_pos
        else:
            return self._current_pos[self.parse_axis(axis)]

    def reset_position(self,axis='all'):
        if axis=='all':
            for ax in self._available_axes:
                self._current_pos[ax] = 0
        else:
            self._current_pos[self.parse_axis(axis)] = 0

    def set_position(self,axis, value):
        self._current_pos[self.parse_axis(axis)] = value

    
