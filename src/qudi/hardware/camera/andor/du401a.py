# -*- coding: utf-8 -*-
# 2026-03: AM Modified version for DU401A

# FIXME: This module is obviously taken from someone else and altered without attribution.
# Likely based on https://github.com/hamidohadi/pyandor
"""
This hardware module implement the camera spectrometer interface to use an Andor Camera.
It use a dll to interface with instruments via USB (only available physical interface)
This module does aim at replacing Solis.

---

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

from enum import Enum
from ctypes import *
import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.camera_interface import CameraInterface


class ReadMode(Enum):
    FVB = 0
    MULTI_TRACK = 1
    RANDOM_TRACK = 2
    SINGLE_TRACK = 3
    IMAGE = 4


class AcquisitionMode(Enum):
    SINGLE_SCAN = 1
    ACCUMULATE = 2
    KINETICS = 3
    FAST_KINETICS = 4
    RUN_TILL_ABORT = 5


class TriggerMode(Enum):
    INTERNAL = 0
    EXTERNAL = 1
    EXTERNAL_START = 6
    EXTERNAL_EXPOSURE = 7
    SOFTWARE_TRIGGER = 10
    EXTERNAL_CHARGE_SHIFTING = 12


ERROR_DICT = {
    20001: "DRV_ERROR_CODES",
    20002: "DRV_SUCCESS",
    20003: "DRV_VXNOTINSTALLED",
    20006: "DRV_ERROR_FILELOAD",
    20007: "DRV_ERROR_VXD_INIT",
    20010: "DRV_ERROR_PAGELOCK",
    20011: "DRV_ERROR_PAGE_UNLOCK",
    20013: "DRV_ERROR_ACK",
    20024: "DRV_NO_NEW_DATA",
    20026: "DRV_SPOOLERROR",
    20034: "DRV_TEMP_OFF",
    20035: "DRV_TEMP_NOT_STABILIZED",
    20036: "DRV_TEMP_STABILIZED",
    20037: "DRV_TEMP_NOT_REACHED",
    20038: "DRV_TEMP_OUT_RANGE",
    20039: "DRV_TEMP_NOT_SUPPORTED",
    20040: "DRV_TEMP_DRIFT",
    20050: "DRV_COF_NOTLOADED",
    20053: "DRV_FLEXERROR",
    20066: "DRV_P1INVALID",
    20067: "DRV_P2INVALID",
    20068: "DRV_P3INVALID",
    20069: "DRV_P4INVALID",
    20070: "DRV_INIERROR",
    20071: "DRV_COERROR",
    20072: "DRV_ACQUIRING",
    20073: "DRV_IDLE",
    20074: "DRV_TEMPCYCLE",
    20075: "DRV_NOT_INITIALIZED",
    20076: "DRV_P5INVALID",
    20077: "DRV_P6INVALID",
    20083: "P7_INVALID",
    20089: "DRV_USBERROR",
    20091: "DRV_NOT_SUPPORTED",
    20095: "DRV_INVALID_TRIGGER_MODE",
    20099: "DRV_BINNING_ERROR",
    20990: "DRV_NOCAMERA",
    20991: "DRV_NOT_SUPPORTED",
    20992: "DRV_NOT_AVAILABLE"
}


class DU401A(CameraInterface):
    """ Hardware class for Andor DU401A

    Example config for copy-paste:

    andor_camera:
        module.Class: 'camera.andor.du401a.DU401A'
        options:
            dll_location: 'C:\\PATH TO\\atmcd64d_legacy.dll' # path to library file, likely in Andor Solis installation folder
            default_exposure: 1.0
            default_read_mode: 'IMAGE'
            default_temperature: -70
            default_cooler_on: True
            default_acquisition_mode: 'SINGLE_SCAN'
            default_trigger_mode: 'INTERNAL'
            has_shutter: False

    """

    _dll_location = ConfigOption('dll_location', missing='error')
    _default_exposure = ConfigOption('default_exposure', 1.0)
    _default_read_mode = ConfigOption('default_read_mode', 'IMAGE')
    _default_temperature = ConfigOption('default_temperature', -70)
    _default_cooler_on = ConfigOption('default_cooler_on', True)
    _default_acquisition_mode = ConfigOption('default_acquisition_mode', 'SINGLE_SCAN')
    _default_trigger_mode = ConfigOption('default_trigger_mode', 'INTERNAL')
    _has_shutter = ConfigOption('has_shutter', False)

    _exposure = _default_exposure
    _temperature_setpoint = _default_temperature
    _cooler_on = _default_cooler_on
    _read_mode = _default_read_mode
    _acquisition_mode = _default_acquisition_mode
    _trigger_mode = _default_trigger_mode
    _gain = 0
    _det_width = 0
    _det_height = 0
    _acq_width = 0   #Acquisition width/height after binning/readmode
    _acq_height = 0
    _last_acquisition_mode = None  # useful if config changes during acq
    _supported_read_mode = ReadMode # TODO: read this from camera
    _max_cooling = -100
    _live = False
    _camera_name = 'DU401A'
    if _has_shutter: _shutter = 'closed'
    else: _shutter = None
                                         
    _scans = 1 #TODO get from camera

    def on_activate(self):
        """ Initialisation performed during activation of the module.
         """
        self._dll = cdll.LoadLibrary(self._dll_location)
        self._dll.Initialize()
        nx_px, ny_px = c_int(), c_int()
        self._get_detector(nx_px, ny_px)
        self._det_width, self._det_height = nx_px.value, ny_px.value
        xsizeC,ysizeC = c_float(), c_float()
        self._get_pixel_size(xsizeC,ysizeC)
        self._xsize,self._ysize = xsizeC.value,ysizeC.value # in microns
        self.set_read_mode(self._read_mode)
        self._set_acquisition_mode(self._acquisition_mode)
        self._set_trigger_mode(self._trigger_mode)
        self._set_exposuretime(self._exposure)
        self._set_cooler(self._cooler_on)
        self._set_temperature(self._temperature_setpoint)

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.stop_acquisition()
        self._set_cooler(False)
        if self._has_shutter:
            self._set_shutter(0, 0, 0.1, 0.1)
        self._shut_down()

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
        return self._camera_name

    def get_det_size(self):
        """ Retrieve size of the detector in pixels

        @return tuple: Size (width, height)
        """
        return self._det_width, self._det_height
    
    def get_image_size(self):
        """ Retrieve size of the image in pixels

        @return tuple: Size (width, height)
        """
        return self._acq_width, self._acq_height
        
    def get_size(self): #Required for interface.
        return self.get_image_size() 
        
    def get_pixel_size(self):
        """ Retrieve size of the pixels

        @return tuple: Size (width, height) in microns
        """
        return self._xsize,self._ysize                                

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition

        @return bool: True if supported, False if not
        """
        return False

    def start_live_acquisition(self):
        """ Start a continuous acquisition

        @return bool: Success ?
        """
        if self._support_live:
            self._live = True

        return False

    def start_single_acquisition(self):
        """ Start a single acquisition

        @return bool: Success ?
        """
        if self._has_shutter:
            if self._shutter == 'closed':
                msg = self._set_shutter(0, 1, 0.1, 0.1)
                if msg == 'DRV_SUCCESS':
                    self._shutter = 'open'
                else:
                    self.log.error('shutter did not open.{0}'.format(msg))

        if self._live:
            return -1
        else:
            if self.get_ready_state():
                msg = self._start_acquisition()
                if msg != "DRV_SUCCESS":
                    return False

                return True
            else:
                self.log.warning("Acquisition not ready")
                return False

    def stop_acquisition(self):
        """ Stop/abort live or single acquisition

        @return bool: Success ?
        """
        msg = self._abort_acquisition()
        if msg == "DRV_SUCCESS":
            self._live = False
            return True
        else:
            return False

    def get_acquired_data(self,oldest=None):
        """ Return an array of last acquired image.

        oldest: Default: retrieve Newest unless acquisition = RUN_TILL_ABORT then retrieve oldest. If True, retrieve oldest (clearing from buffer), else return newest.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """

        if self._acquisition_mode == 'SINGLE_SCAN':
        #    if get_status() == 'DRV_ACQUIRING':
                #return False
            #while self.get_status() == 'DRV_ACQUIRING': #Do this in a non-blocking way?
            #    pass
            if self.get_status() == 'DRV_ACQUIRING':
                self._dll.WaitForAcquisition()  #This is still blocking, but less resource intense.
        else:
            # Need check for continous acquisition modes if new data is available.
            pass
                
        width = self._acq_width
        height = self._acq_height

        #This no longer necessary
        # if self._read_mode == 'IMAGE':
        #     if self._acquisition_mode == 'SINGLE_SCAN':
        #         dim = width * height
        #     elif self._acquisition_mode == 'KINETICS':
        #         dim = width * height * self._scans
        #     elif self._acquisition_mode == 'RUN_TILL_ABORT':
        #         dim = width * height
        #     else:
        #         self.log.error('Your acquisition mode is not covered currently')
        # elif self._read_mode == 'SINGLE_TRACK' or self._read_mode == 'FVB':
        #     if self._acquisition_mode == 'SINGLE_SCAN':
        #         dim = width
        #     elif self._acquisition_mode == 'KINETICS':
        #         dim = width * self._scans
        #     else:
        #         self.log.error('Your acquisition mode is not covered currently')
        # else:
        #     self.log.error('Your acquisition mode is not covered currently')

        if self._read_mode in ['SINGLE_TRACK', 'FVB', 'IMAGE']:
            dim = width*height
            if self._acquisition_mode == 'KINETICS':
                dim *= self._scans
            elif self._acquisition_mode not in ['SINGLE_SCAN', 'RUN_TILL_ABORT']:
                 self.log.error('Your acquisition mode is not covered currently')
        else:
            self.log.error('Your acquisition mode is not covered currently')

        dim = int(dim)
        image_array = np.zeros(dim)
        cimage_array = c_int * dim
        cimage = cimage_array()

        # this will be a bit hacky
        if self._acquisition_mode == 'RUN_TILL_ABORT':
            error_code = self._dll.GetOldestImage(byref(cimage), dim)
        else:
            error_code = self._dll.GetAcquiredData(byref(cimage), dim)
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            self.log.warning('Couldn\'t retrieve an image. {0}'.format(ERROR_DICT[error_code]))
            return image_array
        else:
            self.log.debug('image length {0}'.format(len(cimage)))
            for i in range(len(cimage)):
                # could be problematic for 'FVB' or 'SINGLE_TRACK' readmode
                image_array[i] = cimage[i]
        
        image_array = np.reshape(image_array, (width, height))

        self._cur_image = image_array
        return image_array

    def set_exposure(self, exposure):
        """ Set the exposure time in seconds

        @param float time: desired new exposure time

        @return bool: Success?
        """
        msg = self._set_exposuretime(exposure)
        if msg == "DRV_SUCCESS":
            self._exposure = exposure
            return True
        else:
            return False

    def get_exposure(self):
        """ Get the exposure time in seconds

        @return float exposure time
        """
        self._get_acquisition_timings()
        return self._exposure

    def get_status(self):
        status = c_int()
        self._get_status(status)
        return ERROR_DICT[status.value]
    
    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        if self.get_status() == 'DRV_IDLE':
            return True
        else:
            return False
            
    def set_read_mode(self,mode):  #Not yet handling binning
        self._acq_width=self._det_width
        if self._set_read_mode(mode):
            if mode in ['FVB','SINGLE_TRACK']:
                self._acq_height=1
            elif mode in ['IMAGE']:
                self._acq_height=self._det_height
            else:
                self.log.warning(f'Read mode {mode} not fully implemented, unknown image height.')
                self._acq_height=self._det_height
                
    def get_gain(self): #The original says it's not really working, so check this out. For now definition required by interface.
        raise NotImplementedError
    def set_gain(self):
        raise NotImplementedError
        

    if False: #Non-functional functions
        # not sure if the distinguishing between gain setting and gain value will be problematic for
        # this camera model. Just keeping it in mind for now.
        #TODO: Not really funcitonal right now.
        def set_gain(self, gain):
            """ Set the gain

            @param float gain: desired new gain

            @return float: new exposure gain
            """
            n_pre_amps = self._get_number_preamp_gains()
            msg = ''
            if (gain >= 0) & (gain < n_pre_amps):
                msg = self._set_preamp_gain(gain)
            else:
                self.log.warning('Choose gain value between 0 and {0}'.format(n_pre_amps-1))
            if msg == 'DRV_SUCCESS':
                self._gain = gain
            else:
                self.log.warning('The gain wasn\'t set. {0}'.format(msg))
            return self._gain

        def get_gain(self):
            """ Get the gain

            @return float: exposure gain
            """
            _, self._gain = self._get_preamp_gain()
            return self._gain
        # soon to be interface functions for using
        # a camera as a part of a (slow) photon counter
        def set_up_counter(self):
            check_val = 0
            if self._has_shutter:
                if self._shutter == 'closed':
                    msg = self._set_shutter(0, 1, 0.1, 0.1)
                    if msg == 'DRV_SUCCESS':
                        self._shutter = 'open'
                    else:
                        self.log.error('Problems with the shutter.')
                        check_val = -1
            ret_val1 = self._set_trigger_mode('EXTERNAL')
            ret_val2 = self._set_acquisition_mode('RUN_TILL_ABORT')
            # let's test the FT mode
            # ret_val3 = self._set_frame_transfer(True)
            error_code = self._dll.PrepareAcquisition()
            error_msg = ERROR_DICT[error_code]
            if error_msg == 'DRV_SUCCESS':
                self.log.debug('prepared acquisition')
            else:
                self.log.debug('could not prepare acquisition: {0}'.format(error_msg))
            self._get_acquisition_timings()
            if check_val == 0:
                check_val = ret_val1 | ret_val2

            if msg != 'DRV_SUCCESS':
                ret_val3 = -1
            else:
                ret_val3 = 0

            check_val = ret_val3 | check_val

            return check_val

        def count_odmr(self, length):
            first, last = self._get_number_new_images()
            self.log.debug('number new images:{0}'.format((first, last)))
            if last - first + 1 < length:
                while last - first + 1 < length:
                    first, last = self._get_number_new_images()
            else:
                self.log.debug('acquired too many images:{0}'.format(last - first + 1))

            images = []
            for i in range(first, last + 1):
                img = self._get_images(i, i, 1)
                images.append(img)
            self.log.debug('expected number of images:{0}'.format(length))
            self.log.debug('number of images acquired:{0}'.format(len(images)))
            return False, np.array(images).transpose()

        def get_down_time(self):
            return self._exposure

        def get_counter_channels(self):
            width, height = self.get_size()
            num_px = width * height
            return [i for i in map(lambda x: 'px {0}'.format(x), range(num_px))]


    #Begin direct interface functions
    
    def _abort_acquisition(self):
        error_code = self._dll.AbortAcquisition()
        return ERROR_DICT[error_code]

    def _shut_down(self):
        error_code = self._dll.ShutDown()
        return ERROR_DICT[error_code]

    def _start_acquisition(self):
        error_code = self._dll.StartAcquisition()
        return ERROR_DICT[error_code]
        


# setter functions

    def _set_shutter(self, typ, mode, closingtime, openingtime):
        """
        @param int typ:   0 Output TTL low signal to open shutter
                          1 Output TTL high signal to open shutter
        @param int mode:  0 Fully Auto
                          1 Permanently Open
                          2 Permanently Closed
                          4 Open for FVB series
                          5 Open for any series
        """
        typ, mode, closingtime, openingtime = c_int(typ), c_int(mode), c_float(closingtime), c_float(openingtime)
        error_code = self._dll.SetShutter(typ, mode, closingtime, openingtime)

        return ERROR_DICT[error_code]

    def _set_exposuretime(self, time):
        """
        @param float time: exposure duration
        @return string answer from the camera
        """
        error_code = self._dll.SetExposureTime(c_float(time))
        return ERROR_DICT[error_code]

    def _set_read_mode(self, mode):
        """
        @param string mode: string corresponding to certain ReadMode
        @return True if set successfully, else False
        """
        
        if hasattr(ReadMode, mode):
            n_mode = getattr(ReadMode, mode).value
            n_mode = c_int(n_mode)
            error_code = self._dll.SetReadMode(n_mode)
            if mode == 'IMAGE':
                self.log.debug("width:{0}, height:{1}".format(self._det_width, self._det_height))
                msg = self._set_image(1, 1, 1, self._det_width, 1, self._det_height)
                if msg != 'DRV_SUCCESS':
                    self.log.warning('{0}'.format(ERROR_DICT[error_code]))
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            self.log.warning('Readmode was not set: {0}'.format(ERROR_DICT[error_code]))
            return False
        else:
            self._read_mode = mode

        return True

    def _set_trigger_mode(self, mode):
        """
        @param string mode: string corresponding to certain TriggerMode
        @return string: answer from the camera
        """
        check_val = 0
        if hasattr(TriggerMode, mode):
            n_mode = c_int(getattr(TriggerMode, mode).value)
            self.log.debug('Input to function: {0}'.format(n_mode))
            error_code = self._dll.SetTriggerMode(n_mode)
        else:
            self.log.warning('{0} mode is not supported'.format(mode))
            check_val = -1
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            check_val = -1
        else:
            self._trigger_mode = mode

        return check_val

    def _set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        """
        This function will set the horizontal and vertical binning to be used when taking a full resolution image.
        Parameters
        @param int hbin: number of pixels to bin horizontally
        @param int vbin: number of pixels to bin vertically. int hstart: Start column (inclusive)
        @param int hend: End column (inclusive)
        @param int vstart: Start row (inclusive)
        @param int vend: End row (inclusive).

        @return string containing the status message returned by the function call
        """
        hbin, vbin, hstart, hend, vstart, vend = c_int(hbin), c_int(vbin),\
                                                 c_int(hstart), c_int(hend), c_int(vstart), c_int(vend)

        error_code = self._dll.SetImage(hbin, vbin, hstart, hend, vstart, vend)
        msg = ERROR_DICT[error_code]
        if msg == 'DRV_SUCCESS':
            self._hbin = hbin.value
            self._vbin = vbin.value
            self._hstart = hstart.value
            self._hend = hend.value
            self._vstart = vstart.value
            self._vend = vend.value
            self._acq_width = int((self._hend - self._hstart + 1) / self._hbin)
            self._acq_height = int((self._vend - self._vstart + 1) / self._vbin)
        else:
            self.log.error('Call to SetImage went wrong:{0}'.format(msg))
        return ERROR_DICT[error_code]

    def _set_output_amplifier(self, typ):
        """
        @param c_int typ: 0: EMCCD gain, 1: Conventional CCD register
        @return string: error code
        """
        error_code = self._dll.SetOutputAmplifier(typ)
        return ERROR_DICT[error_code]

    def _set_preamp_gain(self, index):
        """
        @param c_int index: 0 - (Number of Preamp gains - 1)
        """
        error_code = self._dll.SetPreAmpGain(index)
        return ERROR_DICT[error_code]

    def _set_temperature(self, temp):
        temp = c_int(temp)
        error_code = self._dll.SetTemperature(temp)
        if error_code == 'DRV_SUCCESS':
            self._temperature_setpoint = temp.value
        return  ERROR_DICT[error_code]

    def _set_acquisition_mode(self, mode):
        """
        Function to set the acquisition mode
        @param mode:
        @return:
        """
        check_val = 0
        if hasattr(AcquisitionMode, mode):
            n_mode = c_int(getattr(AcquisitionMode, mode).value)
            error_code = self._dll.SetAcquisitionMode(n_mode)
        else:
            self.log.warning('{0} mode is not supported'.format(mode))
            check_val = -1
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            check_val = -1
        else:
            self._acquisition_mode = mode

        return check_val

    def _set_cooler(self, state):
        if state:
            error_code = self._dll.CoolerON()
            if ERROR_DICT[error_code]=='DRV_SUCCESS':
                self._cooler_on = True
            else:
                self.log.warning('Cooler could not be turned on: {0}'.format(ERROR_DICT[error_code]))
        else:   
            error_code = self._dll.CoolerOFF()
            if ERROR_DICT[error_code]=='DRV_SUCCESS':
                self._cooler_on = False
            else:
                self.log.warning('Cooler could not be turned off: {0}'.format(ERROR_DICT[error_code]))

        return ERROR_DICT[error_code]

    def _set_frame_transfer(self, transfer_mode):
        acq_mode = self._acquisition_mode

        if (acq_mode == 'SINGLE_SCAN') | (acq_mode == 'KINETIC'):
            self.log.debug('Setting of frame transfer mode has no effect in acquisition '
                           'mode \'SINGLE_SCAN\' or \'KINETIC\'.')
            return -1
        else:
            rtrn_val = self._dll.SetFrameTransferMode(transfer_mode)

        if ERROR_DICT[rtrn_val] == 'DRV_SUCCESS':
            return 0
        else:
            self.log.warning('Could not set frame transfer mode:{0}'.format(ERROR_DICT[rtrn_val]))
            return -1

# getter functions
    def _get_status(self, status):
        error_code = self._dll.GetStatus(byref(status))
        return ERROR_DICT[error_code]

    def _get_detector(self, nx_px, ny_px):
        error_code = self._dll.GetDetector(byref(nx_px), byref(ny_px))
        return ERROR_DICT[error_code]
    
    def _get_pixel_size(self,xsize,ysize):
        error_code = self._dll.GetPixelSize(byref(xsize), byref(xsize))
        return ERROR_DICT[error_code]
        
    def _get_camera_serialnumber(self, number):
        """
        Gives serial number
        Parameters
        """
        error_code = self._dll.GetCameraSerialNumber(byref(number))
        return ERROR_DICT[error_code]

    def _get_acquisition_timings(self):
        exposure = c_float()
        accumulate = c_float()
        kinetic = c_float()
        error_code = self._dll.GetAcquisitionTimings(byref(exposure),
                                               byref(accumulate),
                                               byref(kinetic))
        self._exposure = exposure.value
        self._accumulate = accumulate.value
        self._kinetic = kinetic.value
        return ERROR_DICT[error_code]

    def _get_number_amp(self):
        """
        @return int: Number of amplifiers available
        """
        n_amps = c_int()
        self._dll.GetNumberAmp(byref(n_amps))
        return n_amps.value

    def _get_number_preamp_gains(self):
        """
        Number of gain settings available for the pre amplifier

        @return int: Number of gains available
        """
        n_gains = c_int()
        self._dll.GetNumberPreAmpGains(byref(n_gains))
        return n_gains.value

    def _get_preamp_gain(self):
        """
        Function returning
        @return tuple (int1, int2): First int describing the gain setting, second value the actual gain
        """
        index = c_int()
        gain = c_float()
        self._dll.GetPreAmpGain(index, byref(gain))
        return index.value, gain.value

    def _get_temperature_int(self):
        """
        Status of the cooling process + current (integer) temperature
        @return: (int, str) containing current temperature and state of the cooling process
        """
        temp = c_int()
        error_code = self._dll.GetTemperature(byref(temp))
        #if ERROR_DICT[error_code] != 'DRV_TEMP_STABILIZED':  #This function does not return DRV_SUCCESS
        #    self.log.error('_get_temperature error: {}'.format(ERROR_DICT[error_code]))
        return temp.value, ERROR_DICT[error_code]

    def _get_temperature(self):
        """
        Status of the cooling process + current temperature
        @return: (float, str) containing current temperature and state of the cooling process
        """
        temp = c_float()
        error_code = self._dll.GetTemperatureF(byref(temp))

        return temp.value, ERROR_DICT[error_code]

    def _get_size_of_circular_ring_buffer(self):
        index = c_long()
        error_code = self._dll.GetSizeOfCircularBuffer(byref(index))
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            self.log.error('Can not retrieve size of circular ring '
                           'buffer: {0}'.format(ERROR_DICT[error_code]))
        return index.value

    def _get_number_new_images(self):
        first = c_long()
        last = c_long()
        error_code = self._dll.GetNumberNewImages(byref(first), byref(last))
        msg = ERROR_DICT[error_code]
        pass_returns = ['DRV_SUCCESS', 'DRV_NO_NEW_DATA']
        if msg not in pass_returns:
            self.log.error('Can not retrieve number of new images {0}'.format(ERROR_DICT[error_code]))

        return first.value, last.value

    # not working properly (only for n_scans = 1)
    def _get_images(self, first_img, last_img, n_scans):
        """ Return an array of last acquired image.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """

        width = self._acq_width #This accounts for binning
        height = self._acq_height

        # first_img, last_img = self._get_number_new_images()
        # n_scans = last_img - first_img
        dim = width * height * n_scans

        dim = int(dim)
        image_array = np.zeros(dim)
        cimage_array = c_int * dim
        cimage = cimage_array()

        first_img = c_long(first_img)
        last_img = c_long(last_img)
        size = c_ulong(width * height)
        val_first = c_long()
        val_last = c_long()
        error_code = self._dll.GetImages(first_img, last_img, pointer(cimage),
                                        size, byref(val_first), byref(val_last))
        if ERROR_DICT[error_code] != 'DRV_SUCCESS':
            self.log.warning('Couldn\'t retrieve an image. {0}'.format(ERROR_DICT[error_code]))
        else:
            for i in range(len(cimage)):
                # could be problematic for 'FVB' or 'SINGLE_TRACK' readmode
                image_array[i] = cimage[i]

        self._cur_image = image_array
        return image_array
    
    if False: # This could just be done in get_acquired_data
        def _get_oldest_image(self):
            """ Return an array of last acquired image.

            @return numpy array: image data in format [[row],[row]...]

            Each pixel might be a float, integer or sub pixels
            """

            width = self._acq_width  #This accounts for binning
            height = self._acq_width

            if self._read_mode == 'IMAGE':
                if self._acquisition_mode == 'SINGLE_SCAN':
                    dim = width * height
                elif self._acquisition_mode == 'KINETICS':
                    dim = width * height * self._scans
            elif self._read_mode == 'SINGLE_TRACK' or self._read_mode == 'FVB':
                if self._acquisition_mode == 'SINGLE_SCAN':
                    dim = width
                elif self._acquisition_mode == 'KINETICS':
                    dim = width * self._scans

            dim = int(dim)
            image_array = np.zeros(dim)
            cimage_array = c_int * dim
            cimage = cimage_array()
            error_code = self._dll.GetOldestImage(pointer(cimage), dim)
            if ERROR_DICT[error_code] != 'DRV_SUCCESS':
                self.log.warning('Couldn\'t retrieve an image')
            else:
                self.log.debug('image length {0}'.format(len(cimage)))
                for i in range(len(cimage)):
                    # could be problematic for 'FVB' or 'SINGLE_TRACK' readmode
                    image_array[i] = cimage[i]

            image_array = np.reshape(image_array, (int(width), int(height)))
            return image_array
# non interface functions regarding setpoint interface
