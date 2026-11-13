# -*- coding: utf-8 -*-

"""
This module acts like a laser.

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

import math
import time
import random

from qudi.interface.simple_laser_interface import SimpleLaserInterface
from qudi.interface.simple_laser_interface import LaserState, ShutterState, ControlMode


class SimpleLaserDummy(SimpleLaserInterface):
    """ Lazor dummy

    Example config for copy-paste:

    laser_dummy:
        module.Class: 'laser.simple_laser_dummy.SimpleLaserDummy'
    """
    _has_piezo = True

    def __init__(self, **kwargs):
        """ """
        super().__init__(**kwargs)
        self.lstate = LaserState.OFF
        self.shutter = ShutterState.CLOSED
        self.mode = ControlMode.POWER
        self.current_setpoint = 0
        self.power_setpoint = 0
        self._scanning_mode = ControlMode.POWER

    def on_activate(self):
        """ Activate module.
        """
        self.connect()

    def on_deactivate(self):
        """ Deactivate module.
        """
        self.disconnect()

    def connect(self):
        self.connected=True

    def disconnect(self):
        self.connected=False

    @property
    def scanning_mode(self):
        return self._scanning_mode

    @scanning_mode.setter
    def scanning_mode(self,value):
        self._scanning_mode = self._interpret_control_mode(value)

    #Shortcuts so scan module calls the right functions
    def scanning_get_power(self):
        if self.scanning_mode.name=='POWER':
            return self.get_power()
        else:
            return self.get_current()
    
    def scanning_set_power(self, value):
        if self.scanning_mode.name=='POWER':
            return self.set_power(value)
        else:
            return self.set_current(value)

    @property
    def scanning_power_unit(self):
        if self.scanning_mode.name=='POWER':
            return 'W'
        else:
            return self.get_current_unit()

    @property
    def scanning_power_name(self):
        if self.scanning_mode.name=='POWER':
            return 'Power'
        else:
            return 'Current'
    
    def get_power_range(self):
        """ Return optical power range

        @return float[2]: power range (min, max)
        """
        return 0, 0.250

    def get_power(self):
        """ Return laser power

        @return float: Laser power in watts
        """
        return self.power_setpoint * random.gauss(1, 0.01)

    def get_power_setpoint(self):
        """ Return optical power setpoint.

        @return float: power setpoint in watts
        """
        return self.power_setpoint

    def set_power(self, power):
        """ Set power setpoint.

        @param float power: power to set
        """
        self.power_setpoint = power
        self.current_setpoint = math.sqrt(4*self.power_setpoint)*100

    def get_current_unit(self):
        """ Get unit for laser current.

        @return str: unit
        """
        return 'mA'

    def get_current_range(self):
        """ Get laser current range.

        @return float[2]: laser current range
        """
        return 0, 100

    def get_current(self):
        """ Get actual laser current

        @return float: laser current in current units
        """
        return self.current_setpoint * random.gauss(1, 0.05)

    def get_current_setpoint(self):
        """ Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.current_setpoint

    def set_current(self, current):
        """ Set laser current setpoint

        @param float current: desired laser current setpoint
        """
        self.current_setpoint = current
        self.power_setpoint = math.pow(self.current_setpoint/100, 2) / 4

    _piezo_enabled=False
    def get_piezo_enabled(self):
        return self._piezo_enabled

    def set_piezo_enabled(self,state):
        self._piezo_enabled=bool(state)
    
    def get_piezo_voltage(self):
        """ Get actual laser piezo voltage

        @return float: laser piezo voltage
        """
        return self._piezo_voltage_setpoint * random.gauss(1, 0.05)

    def get_piezo_voltage_range(self):
        """ Get laser piezo voltage range.

        @return float[2]: laser piezo voltage range
        """
        return (0,100)

    _piezo_voltage_setpoint=0
    def get_piezo_voltage_setpoint(self):
        """ Get laser piezo voltage setpoint

        @return float: laser piezo voltage setpoint
        """
        return self._piezo_voltage_setpoint

    def set_piezo_voltage(self, piezo_voltage):
        """ Set laser piezo voltage setpoint

        @param float current: desired laser piezo voltage setpoint
        """
        self._piezo_voltage_setpoint = piezo_voltage

    def get_wavelength(self):
        return 740e-9 + self._piezo_voltage_setpoint*100e-12*random.gauss(1,0.05)

    def allowed_control_modes(self):
        """ Get supported control modes

        @return frozenset: set of supported ControlMode enums
        """
        return frozenset({ControlMode.POWER, ControlMode.CURRENT, ControlMode.POWER_MODULATION, ControlMode.CURRENT_MODULATION})

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
        """ Get the currently active control mode

        @return ControlMode: active control mode enum
        """
        return self.mode

    def set_control_mode(self, control_mode):
        """ Set the active control mode

        @param ControlMode control_mode: desired control mode enum
        """
        self.mode = control_mode

    def on(self):
        """ Turn on laser.

            @return LaserState: actual laser state
        """
        time.sleep(1)
        self.lstate = LaserState.ON
        return self.lstate

    def off(self):
        """ Turn off laser.

            @return LaserState: actual laser state
        """
        time.sleep(1)
        self.lstate = LaserState.OFF
        return self.lstate

    def get_laser_state(self):
        """ Get laser state

        @return LaserState: current laser state
        """
        return self.lstate

    def set_laser_state(self, state):
        """ Set laser state.

        @param LaserState state: desired laser state enum
        """
        time.sleep(1)
        self.lstate = state
        return self.lstate

    def get_shutter_state(self):
        """ Get laser shutter state

        @return ShutterState: actual laser shutter state
        """
        return self.shutter

    def set_shutter_state(self, state):
        """ Set laser shutter state.

        @param ShutterState state: desired laser shutter state
        """
        time.sleep(1)
        self.shutter = state
        return self.shutter

    def get_temperatures(self):
        """ Get all available temperatures.

        @return dict: dict of temperature names and value in degrees Celsius
        """
        return {
            'psu': 32.2 * random.gauss(1, 0.1),
            'head': 42.0 * random.gauss(1, 0.2)
        }

    def get_extra_info(self):
        """ Multiple lines of dignostic information

            @return str: much laser, very useful
        """
        return "Dummy laser v0.9.9\nnot used very much\nvery cheap price very good quality"

