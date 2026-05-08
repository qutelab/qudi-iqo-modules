# -*- coding: utf-8 -*-

"""
This file contains the Qudi Logic module base class.

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

import numpy as np
import time
from datetime import datetime
import matplotlib.pyplot as plt
from PySide6 import QtCore
from collections.abc import Callable

from qudi.util.datafitting import FitContainer, FitConfigurationsModel
from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.util.units import ScaledFloat
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.util.datastorage import TextDataStorage
from qudi.interface.finite_sampling_input_interface import FiniteSamplingInputInterface
from qudi.util.enums import SamplingOutputMode

#Below list all interfaces  used for control, make sure to add to connections and program a class with required function links.
from qudi.interface.simple_laser_interface import SimpleLaserInterface


class SimpleScanLogic(LogicBase):
    """
    This is the Logic class for simple device scans, e.g. laser piezo.

    example config for copy-paste:

    simple_scan_logic:
        module.Class: 'simple_scan_logic.SimpleScanLogic'
        connect:
            laser: <laser_name>
            data_scanner: <data_scanner_name>
    """

    # declare connectors
    _laser = Connector(name='laser', interface=SimpleLaserInterface)
    _data_scanner = Connector(name='data_scanner', interface=FiniteSamplingInputInterface)

    # declare config options
    _save_thumbnails = ConfigOption(name='save_thumbnails', default=True)

    # declare status variables
    _device_select = StatusVar(default='Laser')
    _x_range = StatusVar(default=(0,1,10))  #start, end, n-steps
    _time_per = StatusVar(default=1)
    _time_wait = StatusVar(default=0.1) #Time to wait at each step before counting
    _number_scans = StatusVar(default=1)
    _shuffle_x = StatusVar(default=False)

    _fit_configs = StatusVar(name='fit_configs', default=None)

    # Internal signals
    _sigNextLine = QtCore.Signal()
    _sigNextPoint = QtCore.Signal()

    # Update signals, e.g. for GUI module
    sigScanParametersUpdated = QtCore.Signal(dict)
    sigScanStateUpdated = QtCore.Signal(bool)
    sigScanDataUpdated = QtCore.Signal()
    sigScanComplete = QtCore.Signal(bool)
    sigLineReady = QtCore.Signal(bool) #True if successful, False if unsucessful
    sigDataPointReady = QtCore.Signal(bool)  #True if successful, False if unsucessful
    sigFitUpdated = QtCore.Signal(object, str, int)
    _sigAcquire = QtCore.Signal(float)

    __default_fit_configs = (
        {'name'             : 'Gaussian Dip',
         'model'            : 'Gaussian',
         'estimator'        : 'Dip',
         'custom_parameters': None},

        {'name'             : 'Two Gaussian Dips',
         'model'            : 'DoubleGaussian',
         'estimator'        : 'Dips',
         'custom_parameters': None},

        {'name'             : 'Lorentzian Dip',
         'model'            : 'Lorentzian',
         'estimator'        : 'Dip',
         'custom_parameters': None},

        {'name'             : 'Two Lorentzian Dips',
         'model'            : 'DoubleLorentzian',
         'estimator'        : 'Dips',
         'custom_parameters': None},
    )
    
    class ScanDevice:
        def __init__(self, name:str, x_setter:Callable, y_getter:Callable=None, len_y:int=1, data_labels:list[str]=None, data_units:list[str]=None, init:Callable=None):
            '''
            Build the connection to the scan device:
            name: the name that will be listed/logged
            x_setter: function that takes in a float and applied it to the device
            y_getter: Optional, function that retrieves the data point(s) at given x, excluding from main scanner which is handled separately. 
                        Returns once per x_point, but can return multiple values. Values will be joined with scanner value.
            len_y: Optional, number of values that are returned by y_getter
            data_labels/data_units: Optional, the headers will be recorded. Should be a list of [x,y,y2,...]. Again, scanner value will be handled separately
            init: function that will be called on initialization.
            '''
            self.name = name
            self._x_setter = x_setter
            self._y_getter = y_getter
            self.len_y = len_y
            self.data_labels=data_labels
            self.data_units=data_units
            self._scanDevice_ = True  #Will be included in list of scan devices

            if init is not None:
                init()

        def set_x(self,value):
            if self._x_setter is not None:
                self._x_setter(value)
        
        def get_y(self):
            if self._y_getter is not None:
                return self._y_getter()
            else: 
                return None
        


    dummyDevice = ScanDevice('Dummy', lambda x: None, lambda: None)

    class ScanWorker(QtCore.QObject):  # Connect scan device to this worker, and send it to a separate thread to allow contiuous data status polling without UI blocking.
        from time import sleep  #This is a separate thread, so sleep is okay here.
        sigWorkerFinished = QtCore.Signal()

        def __init__(self,scanner):
            super().__init__()
            self.scanner = scanner
            self._running = False
            self.result = None

        def acquire_frame(self,wait_time=0):
            self._running = True
            self.sleep(wait_time)
            self.result = self.scanner().acquire_frame()
            self._running = False
            self.sigWorkerFinished.emit()

            
    #Begin SimpleScanLogic main code
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._threadlock = RecursiveMutex()

        self._raw_data = None
        self._x_data = None
        self._signal_data = None
        
        self._line_counter = 0
        self._point_counter = 0        

        # self._fit_container = None
        # self._fit_config_model = None
        # self._fit_results = None



    def on_activate(self):
        """
        Initialisation performed during activation of the module.
        """
        self._acquire_thread = QtCore.QThread()
        self._scan_worker = self.ScanWorker(self._data_scanner)
        self._scan_worker.moveToThread(self._acquire_thread)
        self._acquire_thread.start()


        self.laserScanner = self.ScanDevice('Laser',
                            lambda x: self._laser().set_piezo_voltage(x),
                            lambda : self._laser().get_wavelength(),
                            data_labels=['Piezo Voltage','Wavelength'], # x, y1, y2,...
                            data_units=['V','m'],
                            )

        self.device_dict = {v.name: v for v in self.__dict__.values() if hasattr(v, '_scanDevice_')} # For populating list


        # # Set up fit model and container
        # self._fit_config_model = FitConfigurationsModel(parent=self)
        # self._fit_config_model.load_configs(self._fit_configs)
        # self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)


        # Connect signals
        self.sigLineReady.connect(self._process_data)
        self._sigAcquire.connect(self._scan_worker.acquire_frame)


    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # Stop measurement if it is still running
        self.sigLineReady.disconnect(self._process_data)
        self._sigAcquire.disconnect()
        self._acquire_thread.quit()
        if self.module_state() == 'locked':
            self.stop_scan()


    # @_fit_configs.representer
    # def __repr_fit_configs(self, value):
    #     configs = self.fit_config_model.dump_configs()
    #     if len(configs) < 1:
    #         configs = None
    #     return configs

    # @_fit_configs.constructor
    # def __constr_fit_configs(self, value):
    #     if not value:
    #         return self.__default_fit_configs
    #     return value

    # @property
    # def fit_config_model(self):
    #     return self._fit_config_model

    # @property
    # def fit_container(self):
    #     return self._fit_container

    # @property
    # def fit_results(self):
    #     return self._fit_results.copy()
    
    # def clear_all_fits(self):
    #     if self._fit_results is not None:
    #         for channel, results in self._fit_results.items():
    #             for range_index in range(len(results)):
    #                 self._fit_results[channel][range_index] = None
    #                 self.sigFitUpdated.emit(self._fit_results[channel][range_index], channel, range_index)

    @property
    def scan_device(self):
        return self._device_select
    
    @scan_device.setter
    def scan_device(self,value):
        print("setting device to",value)
        if value in self.device_dict.keys():
            self._device_select = value
        else:
            self.log.error(f'Invalid device, {value} not in device_dict')


    @property
    def signal_data(self):
        return self._signal_data.copy()

    @property
    def raw_data(self):
        return self._raw_data.copy()

    @property
    def x_data(self):
        return self._x_data.copy()
    
    @property
    def x_range(self):
        return self._x_range
    
    @x_range.setter
    def x_range(self,value):
        self._x_range = value
        self.sigScanParametersUpdated.emit({'x_range' : value})

    @property
    def number_scans(self):
        return self._number_scans
    
    @number_scans.setter
    def number_scans(self,value):
        assert (value>0) and (type(value) is int), 'number_scans must be integer >0'
        self._number_scans=value
        self.sigScanParametersUpdated.emit({'number_scans' : value})

    @property
    def time_per(self):
        return self._time_per
    
    @time_per.setter
    def time_per(self,value):
        assert value>0, 'time_per must be greater than 0'
        self._time_per = value
        self.sigScanParametersUpdated.emit({'time_per' : value})

    @property
    def time_wait(self):
        return self._time_wait
    
    @time_wait.setter
    def time_wait(self,value):
        assert value>0, 'time_wait must be greater than 0'
        self._time_wait = value
        self.sigScanParametersUpdated.emit({'time_wait' : value})

    @property
    def shuffle_x(self):
        return self._shuffle_x

    @shuffle_x.setter
    def shuffle_x(self,value):        
        assert type(value) == bool, "shuffle_x value must be bool"
        self._shuffle_x = value
        self.sigScanParametersUpdated.emit({'shuffle_x' : value})


    @QtCore.Slot()
    def start_scan(self):
        """ Starting a scan.        
        """
        with self._threadlock:
            if self.module_state() != 'idle':
                self.log.warning('Can not start scan. Measurement is already running.')
                return

            self.module_state.lock()
            
            scanner = self._data_scanner()
            device = self.device_dict[self._device_select]

            scanner.set_sample_rate(1/self._time_per)
            scanner.set_frame_size(1)  # Minimum two values at a time (NIDAQ requirement)

            self._x_data = np.linspace(*self._x_range)

            self.initialize_data()
            
            self.sigScanDataUpdated.emit()
            self.sigScanStateUpdated.emit(True)

            self._scan()  # Start the scanner loop.



    #Button logic could be as follows Button 1: Start -> Stop -> Continue ; Button 2: Reset data (which sets button 1 back to start, only available if stopped/data is taken)
    @QtCore.Slot()
    def continue_scan(self):
        """ Continue scan.

        @return int: error code (0:OK, -1:error)
        """
        with self._threadlock:
            if self.module_state() == 'locked':
                self.log.error('Can not continue scan. Measurement is already running.')
                self.sigScanStateUpdated.emit(True)
                return
    
            self.module_state.lock()
            self.sigScanStateUpdated.emit(True)
            self._scan()  # Re-start the scanner loop.

    @QtCore.Slot()
    def stop_scan(self):
        """ Stop the scan.

        @return int: error code (0:OK, -1:error)
        """
        with self._threadlock:
            if self.module_state() == 'locked':
                self.module_state.unlock()
            self.sigScanStateUpdated.emit(False)

    @QtCore.Slot()
    def initialize_data(self):
        """ Initialize/clear the data """
        with self._threadlock:
            #self.clear_all_fits()
            scanner = self._data_scanner()
            device = self.device_dict[self._device_select]
            self._scanner_channels = list(scanner.active_channels)
            self._data_labels = device.data_labels + self._scanner_channels
            self._data_units = device.data_units + [scanner._channel_units[key] for key in self._scanner_channels]
            self._data_header = [f'{self._data_labels[ii]} ({self._data_units[ii]})' for ii in range(len(self._data_labels))]
            self._raw_data = np.full((self._number_scans,len(self._x_data),len(self._data_header)),np.nan)
            self._line_counter=0
            self._point_counter=0
            self.sigScanDataUpdated.emit()

    
    @QtCore.Slot(bool,bool)
    def _scan(self, point_ready=False):
        """ 
        Method to scan data. Iterating through _x_data and _number_scans, this will repeatedely call itself until the scan is complete.
        For each data point, after setting x_value, it will first wait _time_wait, then signal itself to actually record the data.
        After each data point is collected, sigDataPointReady(True) is emitted, then after the line is finished, sigLineReady(True) is emitted.
        When full scan is complete, sigScanComplete(True) is emitted.
        If an error occurs, all three signals will be emitted with False.
        """
        #self._point_order allows for randomization of x_points. If enabled, data will be collected in a random order for each line, but stored in the correct spot.
        with self._threadlock:
            scanner = self._data_scanner()
            device = self.device_dict[self._device_select]
            
            if point_ready: 
                # _raw_data is initialized in start_scan, so we just need to populate it here.
                self._raw_data[self._line_counter][self._point_order[self._point_counter]][0] = self._x_data[self._point_order[self._point_counter]]
                devY = device.get_y()
                if devY is not None:
                    try:
                        len(devY)
                    except:
                        devY=[devY]
                    self._raw_data[self._line_counter][self._point_order[self._point_counter]][1:1+len(devY)] = devY
                res = [self._scan_worker.result[channel][0] for channel in self._scanner_channels]
                self._raw_data[self._line_counter][self._point_order[self._point_counter]][1+len(devY):] = res
                self._point_counter+=1
                self.sigDataPointReady.emit(True)
            
            if self.module_state() != 'locked':  #Scan was stopped, stop here
                self._scan_worker.sigWorkerFinished.disconnect()
                return
            try:
                if self._scan_worker._running:
                    raise RuntimeError('_scan_worker already running, cannot get new data point.') #This is caught below to log.
                
                if (self._point_counter==0):
                    if (self._line_counter==0): #First data point, make connection
                        try: #Disconnect everything from signal, but don't throw an error if nothing's connected.
                            self._scan_worker.sigWorkerFinished.disconnect()
                        except:
                            pass
                        self._scan_worker.sigWorkerFinished.connect(lambda: self._scan(True))
                    self._point_order = np.arange(len(self._x_data))
                    if self._shuffle_x:
                        np.random.shuffle(self._point_order)


                if self._point_counter>=len(self._x_data):
                    self.sigLineReady.emit(True)
                    print('Done scanning line',self._line_counter)
                    self._line_counter+=1
                    if self._line_counter>=self._number_scans:
                        self.sigScanComplete.emit(True)
                        self._scan_worker.sigWorkerFinished.disconnect()
                        self.module_state.unlock()
                        return
                    else:
                        self._point_counter=0
        
                device.set_x(self._x_data[self._point_order[self._point_counter]])
                self._sigAcquire.emit(self._time_wait)
                
            except Exception as e:
                self.module_state.unlock()
                self.log.exception(f'Error while getting data point: {e}')
                self._scan_worker.sigWorkerFinished.disconnect()
                #These can be used by other components to communicate an error has occured and no data is incoming.
                self.sigDataPointReady.emit(False)
                self.sigLineReady.emit(False)
                self.sigScanComplete.emit(False)
                return
                
    @QtCore.Slot()
    def _process_data(self): #This just builds the signal (average) data array
        data = np.array(self._raw_data)
        mask_incomplete = np.all(np.isfinite(data), axis=(1,2))
        self._signal_data = np.mean(data[mask_incomplete],axis=0)
    
    @QtCore.Slot(str)
    def save_data(self, tag=None, root_dir=None, metadata=None):
        """ Saves the current data to a file."""
        with self._threadlock:
            # Create and configure storage helper instance
            timestamp = datetime.now()
            #metadata = self._get_metadata()
            if root_dir is None:
                root_dir = self.module_default_data_dir
            tag = tag + '_' if tag else ''

            metadata = metadata if metadata else {}

            # Save raw data in a separate file per data channel
            data_storage = TextDataStorage(root_dir=root_dir,
                                           column_formats='.15e')
            
            #metadata['Channel Name'] = channel
            column_headers = self._data_header
            dev_name = self._device_select
            nametag = f'{tag}{dev_name}_raw'
            data = self._raw_data
            data = data.reshape((data.shape[0]*data.shape[1],data.shape[2])) #Flatten from 3D to 2D array, all scans will be sequential

            # Save raw data for channel
            file_path, _, _ = data_storage.save_data(data,
                                                        metadata=metadata,
                                                        nametag=nametag,
                                                        timestamp=timestamp,
                                                        column_headers=column_headers,
                                                        column_dtypes=float)

            # Save signal data
            #metadata['Averaged Scans (#)'] = self._scans_to_average
            #column_headers = self._get_signal_column_headers()
            nametag = f'{tag}Scan_signal'
            self._process_data()  #Ensure data processing complete.
            data = self.signal_data

            if self._signal_data is not None:
                data_storage.save_data(data,
                                   metadata=metadata,
                                   nametag=nametag,
                                   timestamp=timestamp,
                                   column_headers=column_headers,
                                   column_dtypes=[float] * len(column_headers))
            
            self.log.info(f'Scan data saved to {file_path}')

             # Save plot images if required. This takes by far the most time to complete.
            if self._save_thumbnails:
                for idx in range(1,self._raw_data.shape[2]):
                    fig_path = f"{file_path.rsplit('_raw.', 1)[0]}_{self._data_labels[idx]}"
                    fig = self._draw_figure(0, idx)
                    data_storage.save_thumbnail(fig, file_path=fig_path)
            

    def _draw_figure(self, xidx, yidx):
        """ Draw the summary figure to save with the data.

        @param str channel: The data channel name to plot data for.
        @param int range_index: The index for chosen channel data scan range

        @return matplotlib.figure.Figure: a matplotlib figure object to be saved to file.
        """

        x_data = self._raw_data[0,:,0]  #For 2D plot, x_axis needs to be constant, so used the fixed parameter. Signal plot can show selected x-axis
        y_data = self._raw_data[...,yidx]  #[:, :self._elapsed_sweeps]
        signal_x_data = self._signal_data[:,xidx]
        signal_y_data = self._signal_data[:,yidx]


        
        # fit_result = self._fit_results[channel][range_index]
        # if fit_result is not None:
        #     fit_x, fit_y = fit_result[1].high_res_best_fit
        # unit = self.data_constraints.channel_units[channel]

        # Determine SI unit scaling for signal
        scaled = ScaledFloat(np.max(signal_x_data))
        signal_xunit_prefix = scaled.scale
        if signal_xunit_prefix:
            signal_x_data = signal_x_data / scaled.scale_val
            # if fit_result is not None:
            #     fit_y = fit_y / scaled.scale_val
        signal_xlabel = f'{self._data_labels[xidx]} ({signal_xunit_prefix}{self._data_units[xidx]})'

        scaled = ScaledFloat(np.max(signal_y_data))
        signal_yunit_prefix = scaled.scale
        if signal_yunit_prefix:
            signal_y_data = signal_y_data / scaled.scale_val
            # if fit_result is not None:
            #     fit_y = fit_y / scaled.scale_val
        signal_ylabel = f'{self._data_labels[yidx]} ({signal_yunit_prefix}{self._data_units[yidx]})'

        # Determine SI unit scaling for raw x-axis
        scaled = ScaledFloat(np.nanmax(x_data))
        x_unit_prefix = scaled.scale
        if x_unit_prefix:
            x_data = x_data / scaled.scale_val
            # if fit_result is not None:
            #     fit_x = fit_x / scaled.scale_val
        x_label = f'{self._data_labels[0]} ({x_unit_prefix}{self._data_units[0]})'

        # Determine SI unit scaling for raw y-axis
        scaled = ScaledFloat(np.nanmax(y_data))
        y_unit_prefix = scaled.scale
        if y_unit_prefix:
            y_data = y_data / scaled.scale_val
        y_label = f'{self._data_labels[yidx]} ({y_unit_prefix}{self._data_units[yidx]})'

        # Create figure
        fig, (ax_signal, ax_raw) = plt.subplots(nrows=2, ncols=1)

        # plot signal data
        ax_signal.plot(signal_x_data, signal_y_data, linestyle=':', linewidth=0.5, marker='o')
        # Include fit curve if there is one
        # if fit_result is not None:
        #     ax_signal.plot(fit_x, fit_y, marker='None')
        ax_signal.set_xlabel(signal_xlabel)
        ax_signal.set_ylabel(signal_ylabel)
        ax_signal.set_xlim(min(x_data), max(x_data))

        # plot raw data
        y_data_plot = ax_raw.imshow(y_data,
                                      cmap=plt.get_cmap('inferno'),
                                      origin='lower',
                                      vmin=np.nanmin(y_data),
                                      vmax=np.nanmax(y_data),
                                      extent=[min(x_data),
                                              max(x_data),
                                              -0.5,
                                              y_data.shape[1] - 0.5],
                                      aspect='auto',
                                      interpolation='nearest')
        ax_raw.set_xlabel(x_label)
        ax_raw.set_ylabel('Scan Index')

        # Adjust subplots to make room for colorbar
        fig.subplots_adjust(right=0.8)
        # Add colorbar axis to figure
        colorbar_ax = fig.add_axes([0.85, 0.15, 0.02, 0.7])
        # Draw colorbar
        colorbar = fig.colorbar(y_data_plot, cax=colorbar_ax)
        colorbar.set_label(y_label)
        # remove ticks from colorbar for cleaner image
        colorbar.ax.tick_params(which=u'both', length=0)
        # If we have percentile information, draw that to the figure
        # if percentile_range is not None:
        #     colorbar.ax.annotate(str(percentile_range[0]),
        #                          xy=(-0.3, 0.0),
        #                          xycoords='axes fraction',
        #                          horizontalalignment='right',
        #                          verticalalignment='center',
        #                          rotation=90)
        #     colorbar.ax.annotate(str(percentile_range[1]),
        #                          xy=(-0.3, 1.0),
        #                          xycoords='axes fraction',
        #                          horizontalalignment='right',
        #                          verticalalignment='center',
        #                          rotation=90)
        #     colorbar.ax.annotate('(percentile)',
        #                          xy=(-0.3, 0.5),
        #                          xycoords='axes fraction',
        #                          horizontalalignment='right',
        #                          verticalalignment='center',
        #                          rotation=90)
        return fig
    

    if False: #None of these from ODMR scan have been updated yet.
        @QtCore.Slot(str, str, int)
        def do_fit(self, fit_config, channel, range_index):
            """
            Execute the currently configured fit on the measurement data. Optionally on passed data
            """
            if fit_config != 'No Fit' and fit_config not in self._fit_config_model.configuration_names:
                self.log.error(f'Unknown fit configuration "{fit_config}" encountered.')
                return

            x_data = self._frequency_data[range_index]
            y_data = self._signal_data[channel][range_index]

            try:
                fit_config, fit_result = self._fit_container.fit_data(fit_config, x_data, y_data)
            except:
                self.log.exception('Data fitting failed:')
                return

            if fit_result is not None:
                self._fit_results[channel][range_index] = (fit_config, fit_result)
            else:
                self._fit_results[channel][range_index] = None
            self.sigFitUpdated.emit(self._fit_results[channel][range_index], channel, range_index)

        def _get_metadata(self):
            metadata = {'Number of Frequency Sweeps (#)': self._elapsed_sweeps,
                        'Start Frequencies (Hz)': tuple(rng[0] for rng in self._scan_frequency_ranges),
                        'Stop Frequencies (Hz)': tuple(rng[1] for rng in self._scan_frequency_ranges),
                        'Step sizes (Hz)': tuple(rng[2] for rng in self._scan_frequency_ranges),
                        'Data Rate (Hz)': self._data_rate,
                        'Oversampling factor (Hz)': self._oversampling_factor,
                        'Channel Name': ''}
            for fit_channel in self._fit_results:
                for ii, fit_result in enumerate(self._fit_results[fit_channel]):
                    if fit_result:
                        export_dict = FitContainer.dict_result(fit_result[1])
                        metadata[f'fit result (channel "{fit_channel}" range {ii})'] = export_dict
            return metadata

        def _get_raw_column_headers(self, data_channel):
            channel_unit = self.data_constraints.channel_units[data_channel]
            return 'Frequency (Hz)', f'Scan Data ({channel_unit})'

        def _get_signal_column_headers(self):
            channel_units = self.data_constraints.channel_units
            column_headers = ['Frequency (Hz)']
            column_headers.extend(f'{ch} ({channel_units[ch]})' for ch in self._signal_data)
            return tuple(column_headers)

        def _join_channel_raw_data(self, channel):
            """ join raw data for one channel with corresponding frequency data into a single numpy
            array for saving.

            @param str channel: The channel name for which to join the raw data
            """
            channel_data = self._raw_data[channel]
            # Filter raw data to get rid of invalid values (nan or inf)
            joined_data = np.concatenate([raw[:, :self._elapsed_sweeps] for raw in channel_data],
                                        axis=0)
            # add frequency data as first column
            return np.column_stack((np.concatenate(self._frequency_data), joined_data))


    
