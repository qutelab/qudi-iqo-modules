# -*- coding: utf-8 -*-
"""
This module controls Cobolt lasers.

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
import pycobolt


class CoboltLaser(SimpleLaserInterface):
    """ Spectra Physics Millennia diode pumped solid state laser.

    Example config for copy-paste:

    cobolt_laser:
        module.Class: 'laser.cobolt_laser.CoboltLaser'
        options:
            interface: 'COM3'
            maxpower: 40 # in mW
            maxcurrent: 155 # in mA

    """

    serial_interface = ConfigOption(name='interface', default='COM3', missing='warn')
    maxpower = ConfigOption(name='maxpower', default=40.0, missing='warn')
    maxcurrent = ConfigOption(name='maxcurrent', default=155.0, missing='warn')

    def on_activate(self):
        """ Activate Module.
        """
        self.connect_laser(self.serial_interface)


    def on_deactivate(self):
        """ Deactivate module
        """
        self.disconnect_laser()

    def connect_laser(self, interface):
        """ Connect to Instrument.

            @param str interface: visa interface identifier

            @return bool: connection success
        """
        try:
            self.laser = pycobolt.CoboltLaser(port=self.serial_interface)
            idn = self.laser.send_cmd('*IDN?')
            if 'Cobolt' not in idn:
                del self.laser
                raise RuntimeError(f'Non cobolt device found on {self.serial_interface}')
            (self.mfg, self.model, self.serial, self.version) = idn.split(',')
        except Exception as e:
            self.log.warning(f'Unable to connect to Cobolt laser: {e}')
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
        return {ControlMode.POWER, ControlMode.CURRENT, ControlMode.POWER_MODULATION, ControlMode.CURRENT_MODULATION}
    
    _mode_dict = {
            'POWER': ControlMode.POWER,
            'CONSTANTPOWER': ControlMode.POWER,
            'CURRENT': ControlMode.CURRENT,
            'CONSTANTCURRENT': ControlMode.CURRENT,
            'POWER_MODULATION': ControlMode.POWER_MODULATION,
            'POWERMODULATION': ControlMode.POWER_MODULATION,
            'CURRENT_MODULATION': ControlMode.CURRENT_MODULATION,
            'CURRENTMODULATION': ControlMode.CURRENT_MODULATION,
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

    def get_control_mode(self):
        """ Get active control mode

        @return ControlMode: active control mode
        """
        mode = self.laser.get_mode()
        return self._interpret_control_mode(mode)

    def set_control_mode(self, mode):
        """ Set actve control mode

        @param ControlMode mode: desired control mode
        @return ControlMode: actual control mode
        """
        mode = self._interpret_control_mode(mode)
        if mode == ControlMode.POWER:
            self.laser.constant_power()
        elif mode == ControlMode.CURRENT:
            self.laser.constant_current()
        elif mode == ControlMode.POWER_MODULATION:
            self.laser.power_modulation_mode()
        elif mode == ControlMode.CURRENT_MODULATION:
            self.laser.current_modulation_mode()

    def get_power(self):
        """ Current laser power

        @return float: laser power in W
        """
        return self.laser.get_power()/1000

    def get_power_setpoint(self):
        """ Current laser power setpoint

        @return float: power setpoint in W
        """
        return self.laser.get_power_setpoint()/1000
        
    def get_power_range(self):
        """ Get range for laser power

            @return float[2]: range for laser power
        """
        return 0, self.maxpower/1000

    def set_power(self, power):
        """ Set laser power setpoint in W

        @param float power: desired laser power
        """
        rng = self.get_power_range()
        if rng[0]<=power<=rng[1]:
            self.laser.set_power(power*1000)
        else:
            raise ValueError('Requested power above maximum configured value')

    def get_current_unit(self):
        """ Get unit for current

        return str: unit for laser current
        """
        return 'mA'

    def get_current_range(self):
        """ Get range for laser current

            @return float[2]: range for laser current
        """
        return 0, self.maxcurrent

    def get_current(self):
        """ Get current laser current

        @return float: current laser current
        """
        return self.laser.get_current()

    def get_current_setpoint(self):
        """ Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.laser.get_current_setpoint()

    def set_current(self, current):
        """ Set laser current setpoint

        @param float current_percent: desired laser current setpoint
        @return float: actual laer current setpoint
        """
        rng = self.get_current_range()
        if rng[0]<=current<=rng[1]:
            self.laser.set_current(current)
        else:
            raise ValueError("Requested current outside current range")

    def get_laser_state(self):
        """ Get laser state.

        @return LaserState: current laser state
        """
        state = self.laser.get_state()
        
        if state == 'AutostartWaitingForKeyOn':
            return LaserState.LOCKED
        elif state == 'AutostartLaserOn':
            return LaserState.ON
        elif state == 'AutostartStandby':
            return LaserState.OFF
        else:
            return LaserState.UNKNOWN

    def set_laser_state(self, status):
        """ Set laser state

        @param LaserState status: desited laser state
        @return LaserState: actual laser state
        """
        if self.get_laser_state() != status:
            if status == LaserState.ON:
                self.laser.turn_on()
            elif status == LaserState.OFF:
                self.laser.turn_off()
                
                
    def get_temperature(self):
        return self.laser.send_cmd('TEC1:TEMP?')
        
    def get_temperatures(self):
        return {'Laser':self.laser.send_cmd('TEC1:TEMP?')}