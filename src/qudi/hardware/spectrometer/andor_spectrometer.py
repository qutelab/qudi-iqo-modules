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
from qudi.interface.spectrometer_interface import SpectrometerInterface
from qudi.interface.camera_interface import CameraInterface

from ctypes import *
import numpy as np


ERROR_DICT = {
    20201: "SHAMROCK_COMMUNICATION_ERROR",
    20202: "SHAMROCK_SUCCESS",
    20266: "SHAMROCK_P1INVALID",
    20267: "SHAMROCK_P2INVALID",
    20268: "SHAMROCK_P3INVALID",
    20269: "SHAMROCK_P4INVALID",
    20270: "SHAMROCK_P5INVALID",
    20275: "SHAMROCK_NOT_INITIALIZED"    
}

class AndorSpectrometer(SpectrometerInterface):
    """ Hardware module for reading spectra from the Andor Shamrock+DU401A spectrometer.
    This depends on the camera module (DU401A), so make sure to set defaults there too.
    Example config for copy-paste:

    myspectrometer:
        module.Class: 'spectrometer.andor_spectrometer.AndorSpectrometer'
        connect:
            camera: 'andor_camera'
        options:
            dll_location: 'C:\\PATH TO\\atspectrograph.dll' # path to library file, likely in Andor Solis installation folder
            ini_location: 'C:\\PATH TO\\SPECTROG.ini' # # Optional (?), path to detector INI file, likely in Andor Solis installation folder
            exposure_time: 0.1 #Optional, integration time in seconds, default=0.1
        #    spectrometer_serial: None  # TODO check how to choose a spec when more than one

    """
    _dll_location = ConfigOption('dll_location', missing='error')
    _ini_location = ConfigOption('ini_location', missing='')
    _exposure_time = StatusVar(name='exposure_time', default=1)
    _camera = Connector(name='camera', interface='CameraInterface')
    _idx = 0  # Spectrometer Index, only supporting one spectrometer for now.
    #_serial = ConfigOption(name='spectrometer_serial', default=None, missing='warn')
    
    #Setting maps
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
        self._spectrometer = None
        self.wavelengths = None
        self.grating_dict = {}

    def on_activate(self):
        """ Activate module.
        """
        self._dll = cdll.LoadLibrary(self._dll_location)
        self._dll.ShamrockInitialize(self._ini_location)

        #Setup Spectrometer-Camera link, detector parameters (number of pixels, pixel width) from the camera
        self.exposure_time = self._exposure_time
        pixel_size=self._camera().get_pixel_size()  # um
        num_pixels=self._camera().get_size()
        self.pixel_width = pixel_size[0]  # input is um as integer
        self.number_pixels = num_pixels[0]
        self.load_calibration()
        self.grating_dict = self._get_grating_dict()


    def on_deactivate(self):
        """ Deactivate module.
        """
        self._dll.ShamrockClose()

    def record_spectrum(self):
        """ Record spectrum from Andor spectrometer.

            @return []: spectrum data
        """
        self.load_calibration()
        specdata = np.empty((2, len(self.wavelengths)))
        self._camera().start_single_acquisition()
        specdata[0] = self.wavelengths
        specdata[1] = self._camera().get_acquired_data()[:,0] #Camera will be set to 1 row (either single or FVB), but returns 2D array.
        return specdata

    def load_calibration(self):
        cal = self._get_calibration()
        self.wavelengths = np.array([calI for calI in cal])*1e-9 # nm -> m

    @property
    def number_pixels(self):
        """ Get number of pixels.
            @return int: number of pixels
        """
        return self._get_number_pixels()

    @number_pixels.setter
    def number_pixels(self, value):
        """ Set number of pixels.
            @param int value: number of pixels
        """
        assert isinstance(value, int), f'number_pixels needs to be an integer, but was {value}'
        self._set_number_pixels(value)

    @property
    def pixel_width(self):
        """ Get pixel width.
            @return float: pixel width in um
        """
        return self._get_pixel_width()
    
    @pixel_width.setter
    def pixel_width(self, value):
        """ Set pixel width.
            @param float value: pixel width in um
        """
        assert isinstance(value, (float, int)), f'pixel_width needs to be a float in um, but was {value}'
        self._set_pixel_width(value)
    
    @property
    def wavelength(self):
        """ Get wavelength.
            @return float: wavelength in nm
        """
        return self._get_wavelength()
    
    @wavelength.setter
    def wavelength(self, value):
        """ Set wavelength.
            @param float value: wavelength in nm
        """
        assert isinstance(value, (float, int)), f'wavelength needs to be a float in nm, but was {value}'
        self._set_wavelength(value)
        self.load_calibration()
    
    @property
    def number_gratings(self):
        """ Get number of gratings.
            @return int: number of gratings
        """
        return self._get_number_gratings()

    @property
    def grating(self):
        """ Get grating index.
            @return int: grating index, starting at 1
        """
        return self._get_grating()
    
    @grating.setter
    def grating(self, value):
        """ Set grating index.
            @param int value: grating index, starting at 1
        """
        assert isinstance(value, int), f'grating needs to be an integer index starting at 1, but was {value}'
        if (value < 1) or (value > self.number_gratings):
            self.log.error(f'grating index out of range, needs to be between 1 and {self.number_gratings}, but was {value}')
            return
        self._set_grating(value)
        self.load_calibration()

    @property
    def output_port(self):
        """ Get output port.
            @return str: output port, either 'DIRECT' or 'SIDE'
        """
        return self._get_output_port()
    
    @output_port.setter
    def output_port(self, value):
        """ Set output port.
            @param str value: output port, either 'DIRECT' or 'SIDE'
        """
        if isinstance(value, str):
            if value.upper() not in ['DIRECT', 'SIDE']:
                self.log.error(f'output_port needs to be "DIRECT" or "SIDE", but was {value}')
                return
        elif isinstance(value, int):
            if value not in [0,1]:
                self.log.error(f'output_port needs to be 0 (direct) or 1 (side), but was {value}')
                return
        else:
            self.log.error(f'output_port needs to be 0 (direct) or 1 (side), but was {value}')
            return
        self._set_output_port(value)

    # Camera property shortcuts
    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time in seconds
        """
        return self._camera().get_exposure()

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._camera().set_exposure(float(value))

    @property 
    def camera_temperature(self):
        return self._camera()._get_temperature()[0]

    @property
    def camera_temperature_status(self):
        return self._camera()._get_temperature()[1]
    
    @property
    def camera_temperature_stable(self):
        return self.camera_temperature_status() == 'DRV_TEMP_STABILIZED'
        
    @property 
    def camera_temperature_setpoint(self):
        return self._camera()._temperature_setpoint

    @camera_temperature_setpoint.setter
    def camera_temperature_setpoint(self, value):
        error = self._camera()._set_temperature(float(value))
        if error != 'DRV_SUCCESS':
            self.log.warning(f'Error setting camera temperature: {error}')
        
    @property
    def camera_cooler_on(self):
        '''Boolean indicating whether camera cooling is enabled'''
        return self._camera()._cooler_on
    
    @camera_cooler_on.setter
    def camera_cooler_on(self, value):
        error = self._camera()._set_cooler(bool(value))
        if error != 'DRV_SUCCESS':
            self.log.warning(f'Error setting camera cooler state: {error}')

    # dll calls
    def _get_number_pixels(self):
        npx = c_int()
        msg = ERROR_DICT[self._dll.ShamrockGetNumberPixels(self._idx, byref(npx))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting number of pixels: {msg}')
        return npx.value
    
    def _set_number_pixels(self,num_pixels):
        msg = ERROR_DICT[self._dll.ShamrockSetNumberPixels(self._idx, int(num_pixels))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error setting number of pixels: {msg}')
        
    def _get_pixel_width(self):
        '''' Returns pixel width in um'''
        pxw = c_float()
        msg = ERROR_DICT[self._dll.ShamrockGetPixelWidth(self._idx, byref(pxw))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting pixel width: {msg}')
        return pxw.value
        
    def _set_pixel_width(self,pixel_size):
        ''' Set pixel width in um'''
        msg = ERROR_DICT[self._dll.ShamrockSetPixelWidth(self._idx, c_float(pixel_size))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error setting pixel width: {msg}')

    def _get_calibration(self):
        npx = self._get_number_pixels()
        cal = (c_float*npx)()
        msg = ERROR_DICT[self._dll.ShamrockGetCalibration(self._idx, byref(cal), npx)]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting calibration: {msg}')

        return cal

    def _set_wavelength(self, wavelength):
        ''' Set wavelength in nm'''
        msg = ERROR_DICT[self._dll.ShamrockSetWavelength(self._idx, c_float(wavelength))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error setting wavelength: {msg}')

    def _get_wavelength(self):
        ''' Returns wavelength in nm'''
        wavelength = c_float()
        msg = ERROR_DICT[self._dll.ShamrockGetWavelength(self._idx, byref(wavelength))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting wavelength: {msg}')
        return wavelength.value

    def _get_number_gratings(self):
        n_gratings = c_int()
        msg = ERROR_DICT[self._dll.ShamrockGetNumberGratings(self._idx, byref(n_gratings))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting number of gratings: {msg}')
        return n_gratings.value
    
    def _get_grating_info(self, index):
        """
        Get info of a given grating (by default, current grating).

        Return tuple ``(lines, blaze_wavelength, home, offset)`` (blazing wavelength is in nm).
        """
        lines,blaze_wavelength,home,offset=self._dll.ShamrockGetGratingInfo(self._idx,index)
        return {'lines': lines.value, 'blaze_wavelength': blaze_wavelength.value, 'home': home.value, 'offset': offset.value}
    
    def _get_grating_dict(self):
        '''Get grating enum values and return as dict {name: value}'''
        n_gratings = self.number_gratings
        grating_dict = {}
        grating_dict['by_name'] = {}
        grating_dict['by_index'] = {}
        for i in range(1, n_gratings+1):
            info = self._get_grating_info(i)
            name = f"{info['lines']} lines/mm, blaze {info['blaze_wavelength']} nm"
            grating_dict['by_index'][i] = name
            grating_dict['by_name'][name] = i
        return grating_dict
    
    def _set_grating(self, grating):
        ''' Set grating by index, starting at 1'''
        msg = ERROR_DICT[self._dll.ShamrockSetGrating(self._idx, c_int(grating))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error setting grating: {msg}')

    def _get_grating(self):
        ''' Get grating index, starting at 1'''
        grating = c_int()
        msg = ERROR_DICT[self._dll.ShamrockGetGrating(self._idx, byref(grating))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting grating: {msg}')
        return grating.value
    
    def _set_output_port(self, port):
        ''' Set output port, 0 for direct, 1 for side'''
        flipper = c_int(self.output_port_dict['by_name']['OUTPUT'])
        if type(port) == str:
            if port.upper() in self.output_port_dict['by_name']:
                port = self.output_port_dict['by_name'][port.upper()]
            else:
                self.log.error(f'Invalid output port: {port}, needs to be in {list(self.output_port_dict["by_name"].keys())}')
                return
        else:
            if port not in self.output_port_dict['by_index']:
                self.log.error(f'Invalid output port: {port}, needs to be in {list(self.output_port_dict["by_index"].keys())}')
                return

        msg = ERROR_DICT[self._dll.ShamrockSetFlipperMirror(self._idx, flipper, c_int(port))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error setting output port: {msg}')
    
    def _get_output_port(self):
        ''' Get output port, DIRECT or SIDE'''
        flipper = c_int(self.output_port_dict['by_name']['OUTPUT']) 
        port = c_int()
        msg = ERROR_DICT[self._dll.ShamrockSetFlipperMirror(self._idx, flipper, byref(port))]
        if msg != "SHAMROCK_SUCCESS":
            self.log.error(f'Error getting output port: {msg}')

        try:
            port = self.output_port_dict['by_index'][port.value]
        except:
            port = port.value

        return port

    