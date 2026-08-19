# -*- coding: utf-8 -*-
"""
This file contains the Qudi logic class that captures and processes fluorescence spectra.

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

from PySide6 import QtCore
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import traceback

from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.util.mutex import Mutex
from qudi.util.network import netobtain
from qudi.core.module import LogicBase
from qudi.util.datastorage import TextDataStorage
from qudi.util.datafitting import FitContainer, FitConfigurationsModel


class SpectrometerLogic(LogicBase):
    """This logic module gathers data from the spectrometer. Note: Camera connection made in spectrometer hardware.

    Demo config:

    spectrumlogic:
        module.Class: 'spectrometer_logic.SpectrometerLogic'
        connect:
            spectrometer: 'myspectrometer'
            ###modulation_device: 'my_odmr' #Not sure if this still works
    """

    # declare connectors
    spectrometer = Connector(interface='SpectrometerInterface')  #Spectrometer also controls camera
    modulation_device = Connector(interface='ModulationInterface', optional=True)

    # declare status variables

    _background_correction = StatusVar(name='background_correction', default=False)
    _number_spectra = StatusVar(name='_number_spectra', default=1)
    _number_background = StatusVar(name='_number_background', default=1)
    _differential_spectrum = StatusVar(name='differential_spectrum', default=False)
    _fit_region = StatusVar(name='fit_region', default=[0, 1])
    _axis_type_frequency = StatusVar(name='axis_type_frequency', default=False)

    _fit_config = StatusVar(name='fit_config', default=dict())

    # Internal signals
    _sig_get_spectrum = QtCore.Signal(object, object, object, bool)  #Need object to pass None.
    _sig_get_background = QtCore.Signal(object, bool)

    # External signals eg for GUI module
    sig_data_updated = QtCore.Signal()
    sig_state_updated = QtCore.Signal()
    sig_fit_updated = QtCore.Signal(str, object)
    sig_acquisition_complete = QtCore.Signal(str)

    def __init__(self, **kwargs):
        """ Create SpectrometerLogic object with connectors.

          @param dict kwargs: optional parameters
        """
        super().__init__(**kwargs)
        self.refractive_index_air = 1.00028823
        self.speed_of_light = 2.99792458e8 / self.refractive_index_air
        self._fit_config_model = None
        self._fit_container = None

        # locking for thread safety
        self._lock = Mutex()

        self._spectrum = [None, None]
        self._wavelength = None
        self._wavelength_bkg = None
        self._background = None
        self._repetitions_spectrum = 0
        self._repetitions_background = 0
        self._stop_acquisition = False
        self._acquisition_running = False
        self._fit_results = None
        self._fit_method = ''
        self._live = False

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._create_links()
        self._fit_config_model = FitConfigurationsModel(parent=self)
        self._fit_config_model.load_configs(self._fit_config)
        self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)
        self.fit_region = self._fit_region

        self._sig_get_spectrum.connect(self.get_spectrum, QtCore.Qt.ConnectionType.QueuedConnection)
        self._sig_get_background.connect(self.get_background, QtCore.Qt.ConnectionType.QueuedConnection)


    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self._sig_get_spectrum.disconnect()
        self._sig_get_background.disconnect()
        self._fit_config = self._fit_config_model.dump_configs()

    def stop(self):
        self._stop_acquisition = True

    def run_get_spectrum(self, number_spectra=None, differential_spectrum=None, live=None, reset=True):  #Call this to queue the acquisition
        if reset:
            self._stop_acquisition = False    
        self._sig_get_spectrum.emit(number_spectra, differential_spectrum, live, reset)

    def get_spectrum(self, number_spectra=None, differential_spectrum=None, live=None, reset=True):  
        '''
        Call this to directly acquire the spectrum
        number_spectra: number to record, if not provided, uses currently set value.
        differential_spectrum: Enable to use modulation for differential, if not provided, uses currently set value.
        reset: Resets the data first
        live: continuously records, and saves only latest number_spectra values.
        '''
        if number_spectra is not None:
            if number_spectra > 0:  #sig_get_background emits only ints, so 0 is passed instead of None.
                self.number_spectra = int(number_spectra)
        if differential_spectrum is not None:
            self.differential_spectrum = bool(differential_spectrum)

        if live is not None:
            self._live = bool(live)
        
        if reset:
            self._spectrum = [None, None]  # Main spectrum, differential spectrum
            self._wavelength = None
            self._repetitions_spectrum = 0
            self._spec_parameters_at_start = {key:getattr(self,key) for key in ['exposure_time', 'grating', 
                                                            'output_port', 'wavelength', 'camera_temperature']}
            self._spec_timestamp = datetime.now()

        self._acquisition_running = True
        self.sig_state_updated.emit()

        if self.differential_spectrum_available and self._differential_spectrum:
            self.modulation_device().modulation_on()

        # get data from the spectrometer
        data = np.array(netobtain(self.spectrometer().record_spectrum()))
        with self._lock:
            if self._spectrum[0] is None:
                self._spectrum[0] = np.full((self.number_spectra,data.shape[-1]), np.nan) #Pre-populate array
            if (self._repetitions_spectrum < self.number_spectra):
                self._spectrum[0][self._repetitions_spectrum] = data[1, :]
            else:
                self._spectrum[0][:-1]=self._spectrum[0][1:]  # Manual rolling of data to maintain order, hopefully not to slow.
                self._spectrum[0][-1] = data[1, :]
            
            self._wavelength = data[0, :]
            self._repetitions_spectrum += 1

        if self.differential_spectrum_available and self._differential_spectrum:
            self.modulation_device().modulation_off()
            data = np.array(netobtain(self.spectrometer().record_spectrum()))
            with self._lock:
                if self._spectrum[1] is None:
                    self._spectrum[1] = np.full((self.number_spectra,data.shape[-1]), np.nan) #Pre-populate array
                if (self._repetitions_spectrum < self.number_spectra):
                    self._spectrum[1][self._repetitions_spectrum] = data[1, :]
                else:
                    self._spectrum[1][:-1]=self._spectrum[1][1:]  # Manual rolling of data to maintain order, hopefully not to slow.
                    self._spectrum[1][-1] = data[1, :]
                
        else:
            with self._lock:
                self._spectrum[1] = None
        self.sig_data_updated.emit()
        
        if ((self._repetitions_spectrum < self.number_spectra) or (self._live)) and not self._stop_acquisition:
            self.run_get_spectrum(reset=False)
        else:
            self._acquisition_running = False
            self._stop_acquisition = False
            self.fit_region = self._fit_region  #Call the setter
            self.sig_state_updated.emit()
            self.sig_acquisition_complete.emit('spectrum')

    def run_get_background(self, number_background=None, reset=True):
        if reset:
            self._stop_acquisition = False
        self._sig_get_background.emit(number_background,reset)

    def get_background(self, number_background=None, reset=True):
        if number_background is not None:
            if number_background > 0:  #sig_get_background emits only ints, so 0 is passed instead of None.
                self.number_background = int(number_background)

        if reset:
            self._background = None
            self._wavelength_bkg = None
            self._repetitions_background = 0
            self._bkg_parameters_at_start = {key:getattr(self,key) for key in ['exposure_time', 'grating', 
                                                            'output_port', 'wavelength', 'camera_temperature']}
            self._bkg_timestamp = datetime.now()

        self._acquisition_running = True
        self.sig_state_updated.emit()

        # get data from the spectrometer
        data = np.array(netobtain(self.spectrometer().record_spectrum()))
        with self._lock:
            if self._background is None:
                self._background = np.full((self.number_background,data.shape[-1]), np.nan) #Pre-populate array
            self._background[self._repetitions_background] = data[1, :]
            self._wavelength_bkg = data[0, :]
            self._repetitions_background += 1
        self.sig_data_updated.emit()
        
        if ((self._repetitions_background < self.number_background) or (self.number_background == -1)) and not self._stop_acquisition:
            self.run_get_background(reset=False)
        else:
            self._acquisition_running = False
            self._stop_acquisition = False
            self.sig_state_updated.emit()
            self.sig_acquisition_complete.emit('background')

    @property
    def acquisition_running(self):
        return self._acquisition_running
    

    @property
    def spectrum(self):
        if self._spectrum[0] is None:
            return None
        data = np.copy(self._spectrum[0])
        if self._differential_spectrum and self._spectrum[1] is not None:
            data = data - self._spectrum[1]

        mask_incomplete = np.all(np.isfinite(data), axis=1)
        data = data[mask_incomplete]
        if data.shape[0]<=2: #Only 1 or 2 spectra, take simple mean
            data = np.mean(data,axis=0)
        else:
            # Simple outlier cut to remove cosmic rays from mean.
            dataMean = []
            for dI in data.T:
                cut = np.full(len(dI),True)
                for ii in range(3):
                    diCut = dI[cut]
                    if len(diCut)>=5:
                        # Remove extreme points from mean/std calculation
                        if len(diCut)<20: 
                            diCut = np.sort(diCut)[1:-1]
                        else:
                            i10 = int(len(diCut)*0.1)
                            i90 = int(len(diCut)*0.9)
                            diCut = np.sort(diCut)[i10:i90]
                    mean = np.mean(diCut)
                    std = np.std(diCut)
                    #if std==0:
                    #    break
                    cut = np.abs(dI-mean)<5*std+1e-15  #Add small offset in case std = 0
                dataMean.append(np.mean(dI[cut]))
            data = np.array(dataMean)

        if self._background_correction:
            if not np.all(self._wavelength_bkg == self._wavelength):
                self.log.warning('Background not updated at this wavelength, disabling background correction')
                self._background_correction = False
            else:
                background = self.background
                if background is None:
                    self.log.warning('Background not available, disabling background correction')
                    self._background_correction = False
                else:
                    data = data - background

        return data

    def get_spectrum_at_x(self, x):
        if self.x_data is None or self.spectrum is None:
            return -1
        if self.axis_type_frequency:
            return np.interp(x, self.x_data[::-1], self.spectrum[::-1])
        else:
            return np.interp(x, self.x_data, self.spectrum)

    @property
    def background(self):
        if self._background is None:
            return None
        
        data = np.copy(self._background)

        mask_incomplete = np.all(np.isfinite(data), axis=1)
        data = data[mask_incomplete]

        if data.shape[0]<=2: #Only 1 or 2 spectra, take simple mean
            data = np.mean(data,axis=0)
        else:
            # Simple outlier cut to remove cosmic rays from mean.
            dataMean = []
            for dI in data.T:
                cut = np.full(len(dI),True)
                for ii in range(3):
                    diCut = dI[cut]
                    if len(diCut)>=5:
                        # Remove extreme points from mean/std calculation
                        if len(diCut)<20: 
                            diCut = np.sort(diCut)[1:-1]
                        else:
                            i10 = int(len(diCut)*0.1)
                            i90 = int(len(diCut)*0.9)
                            diCut = np.sort(diCut)[i10:i90]
                    mean = np.mean(diCut)
                    std = np.std(diCut)
                    #if std==0:
                    #    break
                    cut = np.abs(dI-mean)<5*std+1e-15  #Add small offset in case std = 0
                dataMean.append(np.mean(dI[cut]))
            data = np.array(dataMean)
        
        return data


    @property
    def x_data(self):
        if self._axis_type_frequency:
            if self._wavelength is not None:
                return self.speed_of_light / self._wavelength
        else:
            return self._wavelength

    @property
    def x_data_bkg(self):
        if self._axis_type_frequency:
            if self._wavelength_bkg is not None:
                return self.speed_of_light / self._wavelength_bkg
        else:
            return self._wavelength_bkg

    @property
    def repetitions(self):
        return self._repetitions_spectrum

    @property
    def background_correction(self):
        return self._background_correction

    @background_correction.setter
    def background_correction(self, value):
        self._background_correction = bool(value)
        self.sig_state_updated.emit()
        self.sig_data_updated.emit()

    @property
    def number_spectra(self):
        return self._number_spectra

    @number_spectra.setter
    def number_spectra(self, value):
        assert value > 0
        self._number_spectra = int(value)
        self.sig_state_updated.emit()

    @property
    def number_background(self):
        return self._number_background

    @number_background.setter
    def number_background(self, value):
        assert value > 0
        self._number_background = int(value)
        self.sig_state_updated.emit()

    @property
    def differential_spectrum_available(self):
        return self.modulation_device() is not None

    @property
    def differential_spectrum(self):
        return self._differential_spectrum

    @differential_spectrum.setter
    def differential_spectrum(self, value):
        self._differential_spectrum = bool(value)
        if self._differential_spectrum and not self.differential_spectrum_available:
            self.log.warning(f'differential_spectrum was requested, but no modulation device was connected.')
            self._differential_spectrum = False
        self.sig_state_updated.emit()

    def save_all_data(self, name_tag='', root_dir=None, metadata=None):
        self.save_spectrum_data(processed=True, name_tag=name_tag, root_dir=root_dir, metadata=metadata)
        if self._background is not None:
            self.save_spectrum_data(background=True, name_tag=name_tag, root_dir=root_dir, metadata=metadata)
        self.save_spectrum_data(name_tag=name_tag, root_dir=root_dir, metadata=metadata)

    def save_spectrum_data(self, processed = False, background=False, name_tag='', root_dir=None, metadata=None):
        """ Saves the current spectrum data to a file.

        @param bool processed: Save the processed (mean with BG correction and differential if available)
        @param bool background: Whether this is a background spectrum (dark field) or not. Ignored if processed=True
        @param string name_tag: postfix name tag for saved filename.
        @param string root_dir: overwrite the file position in necessary
        @param dict metadata: additional metadata to add to the saved file
        """

        # write experimental parameters
        metadata = metadata if metadata else {}
        if background:
            metadata.update(self._bkg_parameters_at_start)
        else:
            metadata.update(self._spec_parameters_at_start)
        if processed:
            metadata.update( {'acquisition repetitions': self.repetitions,
                        'differential_spectrum'  : self.differential_spectrum,
                        'background_correction'  : self.background_correction,
                        })
            if self.fit_method != 'No Fit' and self.fit_results is not None:
                metadata['fit_method'] = self.fit_method
                metadata['fit_results'] = self.fit_results.params
                metadata['fit_region'] = self.fit_region
        

        if background:
            x_data = self.x_data_bkg
        else:
            x_data = self.x_data
        if self._axis_type_frequency:
            data = [x_data * 1e-12, ]
            header = ['Frequency (THz)', ]
        else:
            data = [x_data * 1e9, ]
            header = ['Wavelength (nm)', ]

        # prepare the data
        if processed:
            spectrum = self.spectrum
            if spectrum is None:
                self.log.error('No spectrum to save.')
                return
            timestamp = self._spec_timestamp
            background_data = self.background
            if background_data is not None:
                if np.all(self._wavelength == self._wavelength_bkg):
                    data.append(background_data)
                    header.append('Background')
            data.append(spectrum)
            header.append('Signal')
            file_label = 'spectrum' + name_tag
        elif background:
            if self._background is None:
                self.log.error('No background to save.')
                return
            timestamp = self._bkg_timestamp
            raw_data = self._background
            mask_incomplete = np.all(np.isfinite(raw_data), axis=1)
            raw_data = raw_data[mask_incomplete]
            for ii in range(len(raw_data)):
                data.append(raw_data[ii])
                header.append(f'Background {ii+1}')
            file_label = 'background_raw' + name_tag
        else:
            if self._spectrum is None:
                self.log.error('No spectrum to save.')
                return
            timestamp = self._spec_timestamp
            raw_data,raw_diff = self._spectrum
            mask_incomplete = np.all(np.isfinite(raw_data), axis=1)
            raw_data = raw_data[mask_incomplete]
            if raw_diff is not None:
                raw_diff = raw_diff[mask_incomplete]
            for ii in range(len(raw_data)):
                data.append(raw_data[ii])
                header.append(f'Spectrum {ii+1}')
                if raw_diff is not None:
                    data.append(raw_diff[ii])
                    header.append(f'Spectrum-Off {ii+1}')
            file_label = 'spectrum_raw' + name_tag

        # save the date to file
        ds = TextDataStorage(root_dir=self.module_default_data_dir if root_dir is None else root_dir)

        file_path, _, _ = ds.save_data(np.array(data).T,
                                       column_headers=header,
                                       metadata=metadata,
                                       nametag=file_label,
                                       timestamp=timestamp,
                                       column_dtypes=[float] * len(header))
        self.log.info(f'Spectrum saved to:{file_path}')

        if processed:
            # save the figure into a file
            figure, ax1 = plt.subplots()
            rescale_factor, prefix = self._get_si_scaling(np.max(data[1]))

            ax1.plot(data[0],
                    data[1] / rescale_factor,
                    linestyle=':',
                    linewidth=0.5
                    )

            if self.fit_method != 'No Fit' and self.fit_results is not None:
                if self._axis_type_frequency:
                    x_data = self.fit_results.high_res_best_fit[0] * 1e-12
                else:
                    x_data = self.fit_results.high_res_best_fit[0] * 1e9

                ax1.plot(x_data,
                        self.fit_results.high_res_best_fit[1] / rescale_factor,
                        linestyle=':',
                        linewidth=0.5
                        )

            ax1.set_xlabel(header[0])
            ax1.set_ylabel('Intensity ({} arb. u.)'.format(prefix))
            figure.tight_layout()

            ds.save_thumbnail(figure, file_path=file_path.rsplit('.', 1)[0])

        

    @staticmethod
    def _get_si_scaling(number):

        prefix = ['', 'k', 'M', 'G', 'T', 'P']
        prefix_index = 0
        rescale_factor = 1

        # Rescale spectrum data with SI prefix
        while number / rescale_factor > 1000:
            rescale_factor = rescale_factor * 1000
            prefix_index = prefix_index + 1

        intensity_prefix = prefix[prefix_index]
        return rescale_factor, intensity_prefix

    @property
    def axis_type_frequency(self):
        return self._axis_type_frequency

    @axis_type_frequency.setter
    def axis_type_frequency(self, value):
        self._axis_type_frequency = bool(value)
        self._fit_method = 'No Fit'
        self._fit_results = None
        self.fit_region = (0, 1e20)
        self.sig_data_updated.emit()

    ############################
    #Spectrometer settings links
    ############################

    _hw_lock=False
    def _hw_property_wrapper(self,name):
        hw_object = self.spectrometer()
        hw_class = hw_object.__class__
        def _fset(self,val):
            if self._hw_lock:
                self.log.error('Cannot set spectrometer, currently locked')
                return False
            self._hw_lock=True
            res = setattr(hw_object, name, val)
            self.sig_state_updated.emit()
            self._hw_lock=False
            return res
        if hasattr(hw_object,name):
            return property(
                fget = lambda self : getattr(hw_object, name),
                fset = _fset,
                doc = getattr(hw_class, name).__doc__
            )
        else:
            return property(fget = lambda self: None)

    def _create_links(self):
        #This should probably be done through the interface or something, but I can't be bothered.
        prop_list = ['exposure_time', 'grating_dict', 'grating', 'output_port_dict', 'output_port', 'wavelength',
                      'camera_temperature', 'camera_temperature_status', 'camera_temperature_stable',
                        'camera_temperature_setpoint', 'camera_cooler_on'
                     ]
        for prop in prop_list:  #Properties need to be on the class, not the instance.
            setattr(self.__class__, prop, self._hw_property_wrapper(prop))


    if False:
        @property
        def exposure_time(self):
            return self.spectrometer().exposure_time

        @exposure_time.setter
        def exposure_time(self, value):
            self.spectrometer().exposure_time = float(value)

        @property
        def grating_dict(self):
            if hasattr(self.spectrometer(), 'grating_dict'):
                return self.spectrometer().grating_dict
            else: 
                return None

        @property
        def grating(self):
            if hasattr(self.spectrometer(), 'grating'):
                return self.spectrometer().grating
            else: 
                return None
        
        @grating.setter
        def grating(self, value):
            if hasattr(self.spectrometer(), 'grating'):
                self.spectrometer().grating = value
            else: 
                self.log.warning('Trying to set grating, but spectrometer does not have this property.')
        
        @property
        def output_port(self):
            if hasattr(self.spectrometer(), 'output_port'):
                return self.spectrometer().output_port
            else: 
                return None
        
        @output_port.setter
        def output_port(self, value):
            if hasattr(self.spectrometer(), 'output_port'):
                self.spectrometer().output_port = value
            else: 
                self.log.warning('Trying to set output port, but spectrometer does not have this property.')
        
        @property
        def central_wavelength(self):
            if hasattr(self.spectrometer(), 'wavelength'):
                return self.spectrometer().wavelength
            else: 
                return None
        
        @central_wavelength.setter
        def central_wavelength(self, value):
            if hasattr(self.spectrometer(), 'wavelength'):
                self.spectrometer().wavelength = value
            else: 
                self.log.warning('Trying to set central wavelength, but spectrometer does not have this property.')
    
        @property 
        def camera_temperature(self):
            if hasattr(self.spectrometer(), 'camera_temperature'):
                return self.spectrometer().camera_temperature
            else: 
                return None
            
        @property
        def camera_temperature_status(self):
            if hasattr(self.spectrometer(), 'camera_temperature_status'):
                return self.spectrometer().camera_temperature_status
            else: 
                return None
        
        @property 
        def camera_temperature_setpoint(self):
            if hasattr(self.spectrometer(), 'camera_temperature_setpoint'):
                return self.spectrometer().camera_temperature_setpoint
            else: 
                return None

        @camera_temperature_setpoint.setter
        def camera_temperature_setpoint(self, value):
            if hasattr(self.spectrometer(), 'camera_temperature_setpoint'):
                self.spectrometer().camera_temperature_setpoint = float(value)
            else: 
                self.log.warning('Trying to set camera temperature setpoint, but spectrometer does not have this property.')

        @property
        def camera_cooler_on(self):
            if hasattr(self.spectrometer(), 'camera_cooler_on'):
                return self.spectrometer().camera_cooler_on
            else: 
                return None
        
        @camera_cooler_on.setter
        def camera_cooler_on(self, value):
            if hasattr(self.spectrometer(), 'camera_cooler_on'):
                self.spectrometer().camera_cooler_on = bool(value)
            else: 
                self.log.warning('Trying to set camera cooler on/off, but spectrometer does not have this property.')

    ################
    # Fitting things

    @property
    def fit_config_model(self):
        return self._fit_config_model

    @property
    def fit_container(self):
        return self._fit_container

    def do_fit(self, fit_method):
        if fit_method == 'No Fit':
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        self.fit_region = self._fit_region
        if self.x_data is None or self.spectrum is None:
            self.log.error('No data to fit.')
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        if self._axis_type_frequency:
            start = len(self.x_data) - np.searchsorted(self.x_data[::-1], self._fit_region[1], 'left')
            end = len(self.x_data) - np.searchsorted(self.x_data[::-1], self._fit_region[0], 'right')
        else:
            start = np.searchsorted(self.x_data, self._fit_region[0], 'left')
            end = np.searchsorted(self.x_data, self._fit_region[1], 'right')

        if end - start < 2:
            self.log.error('Fit region limited the data to less than two points. Fit not possible.')
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        x_data = self.x_data[start:end]
        y_data = self.spectrum[start:end]

        try:
            self._fit_method, self._fit_results = self._fit_container.fit_data(fit_method, x_data, y_data)
        except:
            self.log.exception(f'Data fitting failed:\n{traceback.format_exc()}')
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        self.sig_fit_updated.emit(self._fit_method, self._fit_results)
        return self._fit_method, self._fit_results

    @property
    def fit_results(self):
        return self._fit_results

    @property
    def fit_method(self):
        return self._fit_method

    @property
    def fit_region(self):
        return self._fit_region

    @fit_region.setter
    def fit_region(self, fit_region):
        assert len(fit_region) == 2, f'fit_region has to be of length 2 but was {type(fit_region)}'

        if self.x_data is None:
            return
        fit_region = fit_region if fit_region[0] <= fit_region[1] else (fit_region[1], fit_region[0])
        new_region = (max(min(self.x_data), fit_region[0]), min(max(self.x_data), fit_region[1]))
        self._fit_region = new_region
        self.sig_state_updated.emit()


