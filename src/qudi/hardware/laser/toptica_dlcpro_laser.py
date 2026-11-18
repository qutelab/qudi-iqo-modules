# -*- coding: utf-8 -*-
"""
This module controls Toptica DLC Pro lasers.

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
from qudi.interface.simple_laser_interface import ControlMode, LaserState, ShutterState
import toptica  # type: ignore
#from toptica.lasersdk.dlcpro.v2_4_0 import DLCpro, NetworkConnection  # type: ignore  #high-level api, badly documented
from toptica.lasersdk.client import Client, NetworkConnection # type: ignore   ## low-level api


class DLCPro(SimpleLaserInterface):
    """ Toptica DLCPro laser.

    Example config for copy-paste:

    dlcpro_laser:
        module.Class: 'laser.toptica_dlcpro_laser.DLCPro'
        options:            
            ip_address: 192.168.1.4
            max_current: 88 # in mA
            max_piezo_voltage: 140  # in V
            #min_piezo_voltage: 0  # in V, default 0

    """
    

    #serial_interface = ConfigOption(name='interface', default='COM3', missing='warn')
    #_maxpower = ConfigOption(name='maxpower', default=40.0, missing='warn')
    _ip_address = ConfigOption(name='ip_address', missing='error')
    _max_current = ConfigOption(name='max_current', missing='error')
    _max_piezo_voltage = ConfigOption(name='max_piezo_voltage', missing='error')
    _min_piezo_voltage = ConfigOption(name='min_piezo_voltage', default=0, missing='nothing')
    _has_piezo = True


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
            self.laser = Client(NetworkConnection(self._ip_address))
            self.laser.open()
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
            self.laser.close()
            self.connected=False

    def allowed_control_modes(self):
        """ Control modes for this laser

            @return ControlMode: available control modes
        """
        return {ControlMode.CURRENT} #, ControlMode.CURRENT, ControlMode.POWER_MODULATION, ControlMode.CURRENT_MODULATION
    
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
        return self._interpret_control_mode('CURRENT')

    def set_control_mode(self, mode):
        if mode != ControlMode.CURRENT:
            raise ValueError('DLC Pro only supports current control')

    def get_shutter_state(self):
        return ShutterState.NO_SHUTTER

    def set_shutter_state(self, state):
        raise NotImplementedError('DLC Pro has no shutter')

    def get_extra_info(self):
        return 'Toptica DLC Pro'

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

    # def get_power(self):
    #     """ Current laser power

    #     @return float: laser power in %
    #     """
    #     return None

    # def get_power_setpoint(self):
    #     """ Current laser power setpoint

    #     @return float: power setpoint in %
    #     """
    #     return 0# self.laser.get_power_setpoint()/1000
        
    # def get_power_range(self):
    #     """ Get range for laser power

    #         @return float[2]: range for laser power
    #     """
    #     return 0, 100

    # def set_power(self, power):
    #     """ Set laser power setpoint in %

    #     @param float power: desired laser power
    #     """
    #     rng = self.get_power_range()
    #     if rng[0]<=power<=rng[1]:
    #         self.laser.write_intensity(power)
    #     else:
    #         raise ValueError('Requested power above maximum configured value')

    #Shortcuts so scan module calls the right functions
    def scanning_get_power(self):
        return self.get_current()
    
    def scanning_set_power(self, value):
        self.set_current(value)

    @property
    def scanning_power_unit(self):
        return self.get_current_unit()

    @property
    def scanning_power_name(self):
        return 'Current'

    def get_current_unit(self):
        """ Get unit for current

        return str: unit for laser current
        """
        return 'mA'

    def get_current_range(self):
        """ Get range for laser current

            @return float[2]: range for laser current
        """
        return 0, self._max_current

    def get_current(self):
        """ Get current laser current

        @return float: current laser current
        """
        return self.laser.get('laser1:dl:cc:current-act', float)

    def get_current_setpoint(self):
        """ Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.laser.get('laser1:dl:cc:current-set', float)

    def set_current(self, current):
        """ Set laser current setpoint

        @param float current_percent: desired laser current setpoint
        @return float: actual laer current setpoint
        """
        rng = self.get_current_range()
        if rng[0]<=current<=rng[1]:
            self.laser.set('laser1:dl:cc:current-set', current)
        else:
            raise ValueError("Requested current outside current range")

    # def get_percent(self):
    #     """ Get current laser current

    #     @return float: current laser current
    #     """
    #     self.laser.read()
    #     return self.laser.get_intensity()

    # def get_percent_setpoint(self):
    #     """ Get laser current setpoint

    #     @return float: laser current setpoint
    #     """
    #     return self.laser.get_intensity()

    # def set_percent(self, percent):
    #     """ Set laser current setpoint

    #     @param float current_percent: desired laser current setpoint
    #     @return float: actual laer current setpoint
    #     """
    #     if 0<=percent<=100:
    #         self.laser.write_intensity(percent)
    #     else:
    #         raise ValueError("Requested percent outside range 0-100")

    def get_laser_state(self):
        """ Get laser state.

        @return LaserState: current laser state
        """
        emission = self.laser.get('laser1:dl:cc:emission', bool)
        unlocked = self.laser.get('emission-button-enabled', bool)
        if emission:
            return LaserState.ON
        elif unlocked:  #
            return LaserState.OFF
        else:
            return LaserState.LOCKED

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
                self.laser.set('laser1:dl:cc:enabled', True)
            elif status == LaserState.OFF:
                self.laser.set('laser1:dl:cc:enabled', False)

    def get_piezo_enabled(self):
        """
        return bool: piezo control enabled
        """
        return self.laser.get('laser1:dl:pc:enabled', bool)

    def set_piezo_enabled(self, state):
        """
        param bool: piezo control enabled
        """
        assert type(state)==bool, "state must be input as bool"
        self.laser.set('laser1:dl:pc:enabled', state)

    def get_piezo_voltage(self):
        """ Get actual laser piezo voltage

        @return float: laser piezo voltage
        """
        return self.laser.get('laser1:dl:pc:voltage-act', float)

    def get_piezo_voltage_range(self):
        """ Get laser piezo voltage range.

        @return float[2]: laser piezo voltage range
        """
        return self._min_piezo_voltage, self._max_piezo_voltage

    def get_piezo_voltage_setpoint(self):
        """ Get laser piezo voltage setpoint

        @return float: laser piezo voltage setpoint
        """
        return self.laser.get('laser1:dl:pc:voltage-set', float)

    def set_piezo_voltage(self, piezo_voltage):
        """ Set laser piezo voltage setpoint

        @param float current: desired laser piezo voltage setpoint
        """
        if self._min_piezo_voltage<=piezo_voltage<=self._max_piezo_voltage:
            self.laser.set('laser1:dl:pc:voltage-set', piezo_voltage)
        else:
            raise ValueError(f'Piezo voltage not in range {self._min_piezo_voltage} - {self._max_piezo_voltage} V')
                
    def get_temperature(self):
        return self.laser.get('laser1:dl:tc:temp-act',float)
        
    def get_temperatures(self):
        return {'Laser': self.laser.get('laser1:dl:tc:temp-act',float),
                'Piezo': self.laser.get('laser1:dl:pc:heatsink-temp',float)}