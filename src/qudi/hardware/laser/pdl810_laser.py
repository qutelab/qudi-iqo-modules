# -*- coding: utf-8 -*-
"""
This module controls PDL810 lasers.

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

from qudi.core.configoption import ConfigOption
from qudi.interface.simple_laser_interface import SimpleLaserInterface
from qudi.interface.simple_laser_interface import ControlMode, ShutterState, LaserState
import PDL810_control  # type: ignore


class PDL810(SimpleLaserInterface):
    """ Spectra PDL810 laser.

    Example config for copy-paste:

    pdl810_laser:
        module.Class: 'laser.pdl810_laser.PDL810'

    """
    
    #serial_interface = ConfigOption(name='interface', default='COM3', missing='warn')
    #maxpower = ConfigOption(name='maxpower', default=40.0, missing='warn')
    #maxcurrent = ConfigOption(name='maxcurrent', default=155.0, missing='warn')


    def on_activate(self):
        """ Activate Module.
        """
        self.connect_laser()

    def on_deactivate(self):
        """ Deactivate module
        """
        self.disconnect_laser()

    def connect_laser(self):
        """ Connect to Instrument.

            @return bool: connection success
        """
        try:
            self.laser = PDL810_control.PDL810()
            self.laser.connect()
            self.laser.read()
            ##(self.mfg, self.model, self.serial, self.version) = idn.split(',')
        except Exception as e:
            self.log.warning(f'Unable to connect to PDL810 laser: {e}')
            self.connected=False
            return False
        else:
            self.connected=True
            return True

    def disconnect_laser(self):
        """ Close the connection to the instrument.
        """
        if self.connected:
            self.laser.disconnect()
            self.connected=False

    def allowed_control_modes(self):
        """ Control modes for this laser

            @return ControlMode: available control modes
        """
        return {ControlMode.PERCENT} #, ControlMode.CURRENT, ControlMode.POWER_MODULATION, ControlMode.CURRENT_MODULATION
    
    _mode_dict = {  #Aliases to control modes
            'POWER': ControlMode.POWER,
            'CONSTANTPOWER': ControlMode.POWER,
            'CURRENT': ControlMode.CURRENT,
            'CONSTANTCURRENT': ControlMode.CURRENT,
            'POWER_MODULATION': ControlMode.POWER_MODULATION,
            'POWERMODULATION': ControlMode.POWER_MODULATION,
            'CURRENT_MODULATION': ControlMode.CURRENT_MODULATION,
            'CURRENTMODULATION': ControlMode.CURRENT_MODULATION,
            'PERCENT': ControlMode.PERCENT
        }
        
    def _interpret_control_mode(self, value):
        if type(value) is str:
            value = value.upper()
            if value in self._mode_dict.keys():
                return self._mode_dict[value]
            else:
                raise ValueError('Control mode not found')
        else:
            if value in self.allowed_control_modes():
                return value
            else:
                raise ValueError('Control mode not in allowed_control_modes')
    
    def get_control_mode(self):
        """ Get active control mode

        @return ControlMode: active control mode
        """
        return self._interpret_control_mode('PERCENT')

    def set_control_mode(self, mode):
        if mode != ControlMode.PERCENT:
            raise ValueError('PDL810 only supports percent control')

    def get_shutter_state(self):
        return ShutterState.NO_SHUTTER

    def set_shutter_state(self, state):
        raise NotImplementedError('PDL810 has no shutter')

    def get_extra_info(self):
        return 'PDL810'

    # def set_control_mode(self, mode):
    #     """ Set actve control mode

    #     @param ControlMode mode: desired control mode
    #     @return ControlMode: actual control mode
    #     """
    #     return
    #     # mode = self._interpret_control_mode(mode)
    #     # if mode == ControlMode.POWER:
    #         # self.laser.constant_power()
    #     # elif mode == ControlMode.CURRENT:
    #         # self.laser.constant_current()
    #     # elif mode == ControlMode.POWER_MODULATION:
    #         # self.laser.power_modulation_mode()
    #     # elif mode == ControlMode.CURRENT_MODULATION:
    #         # self.laser.current_modulation_mode()

    #Shortcuts so scan module calls the right functions
    def scanning_get_power(self):
        return self.get_percent()
    
    def scanning_set_power(self, value):
        self.set_percent(value)

    @property
    def scanning_power_unit(self):
        return ''

    @property
    def scanning_power_name(self):
        return 'Percent'
    
    def get_percent(self):
        """ Get current laser current

        @return float: current laser current
        """
        self.laser.read()
        return self.laser.get_intensity()

    def get_percent_setpoint(self):
        """ Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.laser.get_intensity()

    def set_percent(self, percent):
        """ Set laser current setpoint

        @param float current_percent: desired laser current setpoint
        @return float: actual laer current setpoint
        """
        if 0<=percent<=100:
            self.laser.write_intensity(percent)
        else:
            raise ValueError("Requested percent outside range 0-100")

    def get_laser_state(self):
        """ Get laser state.

        @return LaserState: current laser state
        """
        self.laser.read()
        
        #if self.laser.is_locked():
        #    return LaserState.LOCKED
        if self.laser.is_soft_locked():
            return LaserState.OFF
        else:
            return LaserState.ON

    def set_laser_state(self, status):
        """ Set laser state

        @param LaserState status: desited laser state
        @return LaserState: actual laser state
        """
        state = self.get_laser_state()
        if state == LaserState.LOCKED:
            raise RuntimeError('Cannot change laser state while locked')
        elif state != status:
            if status == LaserState.ON:
                self.laser.write_soft_lock(False)
            elif status == LaserState.OFF:
                self.laser.write_soft_lock(True)
                
    def get_temperature(self):
        return 0
        
    def get_temperatures(self):
        return {'Laser': 0}