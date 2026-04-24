# -*- coding: utf-8 -*-
"""
This module contains fake spectrometer.

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

from qudi.interface.spectrometer_interface import SpectrometerInterface

from time import strftime, localtime

import time
import numpy as np
from time import sleep  #Imitate time to change settings.

class SpectrometerDummy(SpectrometerInterface):
    """ Dummy spectrometer module.

    Shows a silicon vacancy spectrum at liquid helium temperatures.

    Example config for copy-paste:

    spectrometer_dummy:
        module.Class: 'spectrometer.spectrometer_dummy.SpectrometerInterfaceDummy'

    """
    #Class placeholders and defaults
    wavelengths = None
    grating_dict = {}

    output_port_dict = {
            'by_name': {
                'DIRECT': 0,
                'SIDE': 1
            },
            'by_index': {
                0: 'DIRECT',
                1: 'SIDE'
            }
        }
    
    flipper_dict = {
        'by_name': {
            'INPUT': 1,
            'OUTPUT': 2
        },
        'by_index': {
            1: 'INPUT',
            2: 'OUTPUT'
        }   
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._exposure = 0.5

    def on_activate(self):
        """ Activate module.
        """
        self.grating_dict = self._get_grating_dict()
        self.load_calibration()

    def on_deactivate(self):
        """ Deactivate module.
        """
        pass

    def record_spectrum(self):
        """ Record a dummy spectrum.

            @return ndarray: 1024-value ndarray containing wavelength and intensity of simulated spectrum
        """
        length = 1024

        self.load_calibration()
        data = np.empty((2, length), dtype=np.double)
        data[0] = self.wavelengths
        data[1] = np.random.uniform(0, 2000, length)

        # lorentz, params = self._fitLogic.make_multiplelorentzian_model(no_of_functions=4)
        # sigma = 0.05
        # params.add('l0_amplitude', value=2000)
        # params.add('l0_center', value=736.46)
        # params.add('l0_sigma', value=1.5 * sigma)
        # params.add('l1_amplitude', value=5800)
        # params.add('l1_center', value=736.545)
        # params.add('l1_sigma', value=sigma)
        # params.add('l2_amplitude', value=7500)
        # params.add('l2_center', value=736.923)
        # params.add('l2_sigma', value=sigma)
        # params.add('l3_amplitude', value=1000)
        # params.add('l3_center', value=736.99)
        # params.add('l3_sigma', value=1.5 * sigma)
        # params.add('offset', value=50000.)
        #
        # data[1] += lorentz.eval(x=data[0], params=params)

        time.sleep(self.exposure_time)
        return data

    @property
    def exposure_time(self):
        """ Get exposure time.
        """
        return self._exposure

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure time.
        """
        print('Exposure time set to', value, 's')
        self._exposure = float(value)

    _grating_info = {
        # Sample gratings
        1: {'lines': 600, 'blaze_wavelength': 650},  #lines/mm, blaze wavelength in nm
        2: {'lines': 1200, 'blaze_wavelength': 400},
    }
    
    def _get_grating_dict(self): #for making selector in GUI
        '''Get grating enum values and return as dict {name: value}'''
        n_gratings = self.number_gratings
        grating_dict = {}
        grating_dict['by_name'] = {}
        grating_dict['by_index'] = {}
        for i in range(1, n_gratings+1):
            info = self._grating_info[i]
            name = f"{info['lines']} lines/mm, blaze {info['blaze_wavelength']} nm"
            grating_dict['by_index'][i] = name
            grating_dict['by_name'][name] = i
        return grating_dict

    def load_calibration(self):
        num_pixels = 1024
        pixel_width = 20e-6
        cam_distance = 50e-2
        grat_spacing = 1/(self._grating_info[self.grating]['lines']*1e3)
        center_angle = np.arcsin( (self.wavelength*1e-9)/grat_spacing )
        pixel_angles = center_angle + np.arctan( (np.arange(num_pixels)-num_pixels/2)*pixel_width / cam_distance )
        cal = np.sin(pixel_angles) * grat_spacing
        self.wavelengths = np.array([calI for calI in cal])

    _wavelength = 736.5
    @property
    def wavelength(self):
        """ Get wavelength.
            @return float: wavelength in nm
        """
        return self._wavelength
    
    @wavelength.setter
    def wavelength(self, value):
        """ Set wavelength.
            @param float value: wavelength in nm
        """
        assert isinstance(value, (float, int)), f'wavelength needs to be a float in nm, but was {value}'
        self._wavelength = float(value)
        self.load_calibration()
        print('Wavelength set to', value, 'nm')
    
    @property
    def number_gratings(self):
        """ Get number of gratings.
            @return int: number of gratings
        """
        return len(self._grating_info)

    _grating=1
    @property
    def grating(self):
        """ Get grating index.
            @return int: grating index, starting at 1
        """
        return self._grating
    
    @grating.setter
    def grating(self, value):
        """ Set grating index.
            @param int value: grating index, starting at 1
        """
        assert isinstance(value, int), f'grating needs to be an integer index starting at 1, but was {value}'
        self._grating = int(value)
        sleep(5)
        self.load_calibration()
        print('Grating set to', value, '(', self.grating_dict["by_index"][value], ')')

    _output_port = 'DIRECT'
    @property
    def output_port(self):
        """ Get output port.
            @return str: output port, either 'DIRECT' or 'SIDE'
        """
        return self._output_port
    
    @output_port.setter
    def output_port(self, value):
        """ Set output port.
            @param str value: output port, either 'DIRECT' or 'SIDE'
        """
        if isinstance(value, str):
            if value.upper() not in ['DIRECT', 'SIDE']:
                self.log.error(f'output_port needs to be "DIRECT" or "SIDE", but was {value}')
                return
            self._output_port = value.upper()
        elif isinstance(value, int):
            if value not in [0,1]:
                self.log.error(f'output_port needs to be 0 (direct) or 1 (side), but was {value}')
                return
            self._output_port = 'DIRECT' if value == 0 else 'SIDE'
        else:
            self.log.error(f'output_port needs to be 0 (direct) or 1 (side), but was {value}')
            return
        print('Output port set to', self._output_port)

    # Camera dummy properties
    @property 
    def camera_temperature(self):
        if self.camera_cooler_on:
            return self.camera_temperature_setpoint + np.random.random() - 0.5
        else:
            return 20 + np.random.random()*4 - 2

    @property
    def camera_temperature_status(self):
        if self.camera_cooler_on:
            return 'DRV_TEMP_STABILIZED'
        else:
            return 'DRV_TEMP_OFF'
    
    _temperature_setpoint = -70
    @property
    def camera_temperature_stable(self):
        return self.camera_temperature_status == 'DRV_TEMP_STABILIZED'
        
    @property 
    def camera_temperature_setpoint(self):
        return self._temperature_setpoint

    @camera_temperature_setpoint.setter
    def camera_temperature_setpoint(self, value):
        self._temperature_setpoint = float(value)
        print('Camera temperature setpoint set to', value, '°C')
    
    _cooler_on = False
    @property
    def camera_cooler_on(self):
        '''Boolean indicating whether camera cooling is enabled'''
        return self._cooler_on
    
    @camera_cooler_on.setter
    def camera_cooler_on(self, value):
        self._cooler_on = bool(value)
        print('Camera cooler turned', 'ON' if self._cooler_on else 'OFF')