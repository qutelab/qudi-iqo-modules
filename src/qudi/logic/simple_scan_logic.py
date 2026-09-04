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

from qudi.interface.microwave_interface import MicrowaveInterface

from time import sleep


class SimpleScanLogic(LogicBase):
    """
    This is the Logic class for simple device scans, e.g. laser piezo.
    Each scan device must be configured in on_activate.

    example config for copy-paste:

    simple_scan_logic:
        module.Class: 'simple_scan_logic.SimpleScanLogic'
        connect:
            laser: laser_dummy
            microwave: microwave_dummy
            data_scanner: finite_sampling_input_dummy
            awg: simple_awg_logic
    """

    # declare connectors
    _data_scanner = Connector(name='data_scanner', interface=FiniteSamplingInputInterface)
    _laser = Connector(name='laser', interface=SimpleLaserInterface, optional=True)
    _microwave = Connector(name='microwave', interface=MicrowaveInterface, optional=True)
    _awg = Connector(name='awg', interface='SimpleAWGLogic', optional=True)

    # declare config options
    _save_thumbnails = ConfigOption(name='save_thumbnails', default=True)

    # declare status variables
    _device_select = StatusVar(default='Laser')
    _x_range = StatusVar(default={})  #start, end, n-steps
    _time_per = StatusVar(default=1)
    _time_wait = StatusVar(default=0.1) #Time to wait at each step before counting
    _number_scans = StatusVar(default=1)
    _shuffle_x = StatusVar(default=False)
    _device_settings_store = StatusVar(default={})

    _fit_configs = StatusVar(name='fit_configs', default=None)

    # Internal signals
    _sigNextLine = QtCore.Signal()
    _sigNextPoint = QtCore.Signal()

    # Update signals, e.g. to send updates to GUI module
    sigScanParametersUpdated = QtCore.Signal(dict)
    sigDeviceUpdated = QtCore.Signal(str)
    sigScanStateUpdated = QtCore.Signal(bool)  #True when running, False when not
    sigScanDataUpdated = QtCore.Signal()
    sigScanComplete = QtCore.Signal(bool)   #True if successful, False if unsucessful
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
        def __init__(self, name:str, x_setter:Callable, y_getter:Callable=None, len_y:int=None, 
                     data_labels:list[str]=None, data_units:list[str]=None, 
                     static_read_parameters:dict=dict(), static_set_parameters:dict=dict(),
                     start_function:Callable=None, end_function:Callable=None, dependencies=None, parent=None):
            '''
            Build the connection to the scan device:
            name: the name that will be listed/logged
            x_setter: function that takes in a float and applies it to the device
            y_getter: Optional, function that retrieves the data point(s) at given x, excluding from main scanner which is handled separately. 
                        Returns once per x_point, but can return multiple values. Values will be joined with scanner value.
            len_y: Semi-optional, number of values that are returned by y_getter. If None, inferred from lenth of data_labels, but if that is None and y_getter is set, then raises error.
            data_labels/data_units: Optional, the headers will be recorded. Should be a list of [x,y,y2,...]. 
                                    Again, scanner value will be handled separately
            static_read_parameters: Optional, dict of Label: (read function, unit) for any parameters that are static across the scan but should be recorded in the data header.
            static_set_parameters: Optional, dict of Label: (set function, default, unit) or (set function, default, unit, constraints) 
                 for any parameters that are static across the scan but need to be set at the start of the scan. If constraints provided,
                 use tuple for (min,max), list for specific choices. These will be included in  the data header and saved with the data.
                 Defaults are only used the first time the function is loaded, later using the StatusVar saved from the last run.
            start_function: Optional, function that will be called at the start of the scan.
            end_function: Optional, function that will be called at the end of the scan.
            dependencies: Optional, List of what modules are required for operation. str, e.g. 'laser' for _laser
            '''
            
            #Verify inputs
            if y_getter is not None:
                if len_y is None:
                    if data_labels is not None:
                        len_y = len(data_labels)-1
                    else:
                        raise ValueError('len_y must be provided if y_getter is set and data_labels is not provided.')
                else:
                    if data_labels is not None and len(data_labels) != len_y+1:
                        raise ValueError('data_labels length must be equal to len_y+1 (for x value)')
                    elif data_labels is None:
                        data_labels = ['x'] + [f'y{i}' for i in range(len_y)]
                    if data_units is not None and len(data_units) != len_y+1:
                        raise ValueError('data_units length must be equal to len_y+1 (for x value)')
                    elif data_units is None:
                        data_units = [''] * (len_y+1)
            else:
                if data_labels is None:
                    data_labels = ['x']
                if data_units is None:
                    data_units = ['']
                if len(data_labels) != len(data_units):
                    raise ValueError('data_labels and data_units must have the same length.')
                len_y = 0

            # TODO: More type checking, e.g. for static_set
            self.name = name
            self._x_setter = x_setter
            self._y_getter = y_getter
            self._len_y = len_y
            self._data_labels=data_labels
            self._data_units=data_units
            self._static_read_parameters=static_read_parameters
            self._static_set_parameters=static_set_parameters
            self._start_function = start_function
            self._end_function = end_function
            self._scanDevice_ = True  #Will be included in list of scan devices
            self._metadata = {}
            self._dependencies = dependencies
            self._parent = parent
            if parent is None:
                class x:  # Throwaway so the code below doesn't need extra checks.
                    _device_settings_store = {}
                self._parent = x()

            if len(self._static_set_parameters)>0:
                if self.name not in self._parent._device_settings_store:
                    self._parent._device_settings_store[self.name] = {}
                else:
                    for label, val in self._static_set_parameters.items():
                        if label in self._parent._device_settings_store[self.name]:
                            #Update starting value from StatusVar
                            self.update_static_set_parameter_value(label,self._parent._device_settings_store[self.name][label])


        def set_x(self,value):
            if self._x_setter is not None:
                self._x_setter(value)
        
        def get_y(self):
            if self._y_getter is not None:
                y = self._y_getter()
                if y is None: return None
                
                if np.asarray(y).ndim == 0:  #Force into a list if single value
                    y = [y]
                if len(y) != self._len_y:
                    raise RuntimeError(f'Length of y_getter output ({len(y)}) does not match expected length {self._len_y}.')
                return y
            else: 
                return None

        @property
        def len_y(self):
            return self._len_y

        def update_static_set_parameter_value(self,label,value):
            if label in self._static_set_parameters:
                self._static_set_parameters[label] = (self._static_set_parameters[label][0], value, *self._static_set_parameters[label][2:])
            else:
                raise ValueError(f'Label {label} not found in {self.name} parameters')

        
        def start_scan(self, first_value=None, leave_x=False):
            if first_value is None and not leave_x:
                raise ValueError('first_value must be provided if leave_x is False.')
            
            if len(self._static_set_parameters)>0:
                if self.name not in self._parent._device_settings_store:
                    self._parent._device_settings_store[self.name] = {}
                for label, val in self._static_set_parameters.items():
                    if len(val)==3:
                        set_func, value, unit = val
                        constraint=None
                    elif len(val)==4:
                        set_func, value, constraint, unit = val
                    else:
                        raise RuntimeError(f'Unexpected length of values for static_set_paramters, must be 3 or 4')
                    if constraint:
                        if type(constraint) == tuple:
                            if value<constraint[0] or value>constraint[1]:
                                raise ValueError(f'Set parameter {label} to {value} outside range {constraint}')
                        elif type(constraint) == list:
                            if value not in constraint:
                                raise ValueError(f'Set parameter {label} to {value} not in list {constraint}')
                        else:
                            raise NotImplementedError(f'Constraint type {type(constraint)} not implemented.')
                    #print('Setting static parameter', label, 'to', value, unit)
                    set_func(value)
                    self._parent._device_settings_store[self.name][label] = value
                    self._metadata[f'{label} ({unit})'] = value

            if self._start_function is not None:
                self._start_function()

            if not leave_x:
                self.set_x(first_value)

            if len(self._static_read_parameters)>0:
                for label, (read_func, unit) in self._static_read_parameters.items():
                    value = read_func()
                    self._metadata[f'{label} ({unit})'] = value

        def end_scan(self):
            if self._end_function is not None:
                self._end_function()


    dummyDevice = ScanDevice('Dummy', lambda x: None, lambda: None, len_y=1)

    class ScanWorker(QtCore.QObject):  # Connect scan device to this worker, and send it to a separate thread to allow contiuous data status polling without UI blocking.
        from time import sleep  #This is a separate thread, so sleep is okay here.
        sigWorkerFinished = QtCore.Signal(object)

        def __init__(self,scanner):
            super().__init__()
            self.scanner = scanner
            self._running = False
            self.result = None

        def acquire_frame(self,wait_time=0):
            self._running = True
            self.sleep(wait_time)
            try:
                #self.result = self.scanner().get_buffered_samples(self.scanner().frame_size)
                self.result = self.scanner().acquire_frame()
                self._running = False
                self.sigWorkerFinished.emit(None)
            except Exception as e:
                self.result=None
                self._running = False
                self.sigWorkerFinished.emit(e)
            
            
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

        #Below is where we set up the scan devices. Each device needs a name, a function to set the x value, 
        #  and optionally a function to get y value(s) and labels/units for the data. The x setter will be called
        #  every time we want to get a new data point, and the y getter will be called after setting x and waiting,
        #  to retrieve any additional data from the device that is not included in the main scanner data. This
        #  allows for flexibility in what devices can be scanned and what data is recorded, as well as keeping
        #  the main scanner loop separate from device-specific code.
        # 
        # Required: x_setter, function thats called each line to set the value
        # Optional:
        # y_getter: Function that retrieves additonal data point(s) at each x.
        # y_len: If y_getter is used, how many values does it return?
        # data_labels/units, One for x and each included y value
        # static_read_parameters: Dict of Label: (read function, unit) for any parameters that are static across the scan
        # static_set_parameters: Dict of Label: (set function, default_value, unit) for any parameters that are static across the scan
        # These will be included in the data header and saved with the data
        # (start/end)_function: Called at start and end of scan, e.g. power on/off if necessary.
        # dependencies: Optional, List of what modules are required for operation. str of variable name e.g. '_laser'
        # Order of operations: Set all static_set_parameters, set to first scan value, call start_function, 
        #                      read static_read_parameters, scan, then call end_function. 
        # Any interruption will also call end_function.
        
        self.laserScanner = self.ScanDevice('Laser',
                lambda x: self._laser().set_piezo_voltage(x),
                lambda : self._laser().get_wavelength(),
                data_labels=['Piezo Voltage','Wavelength'], # x, y1, y2,...
                data_units=['V','m'],
                static_read_parameters={},
                static_set_parameters={'Laser Power': (self._laser().set_power, 1e-6, 'W')},
                start_function=None,
                end_function=None,
                dependencies=['_laser'],
                parent = self
        )
        
        #This ODMR version just scans frequency manually in CW mode.

        self.odmrScanner = self.ScanDevice('ODMR',
                lambda x: setattr(self._microwave(), 'cw_frequency', x),
                data_labels=['Frequency'], # x, y1, y2,...
                data_units=['Hz'],
                static_read_parameters={},
                static_set_parameters={'RF Power': (lambda power: setattr(self._microwave(), 'cw_power', power), -60, 'dBm')},
                start_function=lambda : (self._microwave().set_cw(), self._microwave().cw_on()),
                end_function=lambda : self._microwave().cw_off(),
                dependencies=['_microwave'],
                parent = self
        )

        #This ODMR version scans frequency manually in Pulsed mode.
        #Set up channels for ratio
        clockO = self._data_scanner()._gate_on_external_clock
        self._data_scanner()._gate_on_external_clock = True  #For retrieving gated channel list
        scanner_channels_G = list(self._data_scanner().active_channels)
        self._data_scanner()._gate_on_external_clock = clockO  #Reset
        scanner_channels_G.sort()
        self._pulsed_numerator_channel = scanner_channels_G[0] #Default
        if len(scanner_channels_G)>1:
            self._pulsed_denominator_channel = scanner_channels_G[1] #Default
        else:
            self._pulsed_denominator_channel = scanner_channels_G[0] #Default
        #print('Scanner Channels',scanner_channels_G)

        def _pulsed_ODMR_getY(self):
            # Get ratio of digital channels as selected
            currentPoint = self._raw_data[self._line_counter][self._point_order[self._point_counter]]
            dev_y_len = self.pulsedOdmrScanner.len_y
            numIdx = 1+dev_y_len + self._scanner_channels.index(self._pulsed_numerator_channel)
            denIdx = 1+dev_y_len + self._scanner_channels.index(self._pulsed_denominator_channel)
            if currentPoint[denIdx]==0:
                return 0
            else:
                return currentPoint[numIdx]/currentPoint[denIdx]

        def _pulsed_start_scan(self):
            self._pulsed_initialGate = self._data_scanner()._gate_on_external_clock
            self._data_scanner()._gate_on_external_clock = True
            if self._microwave().cw_frequency < 400e6:
                self._microwave().set_pulsed(frequency=1e8)
            else:
                self._microwave().set_pulsed()
            if self._awg() is not None:  #Just for dummy capability.
                self._awg().start_output()
            self._microwave().cw_on()

        def _pulsed_end_scan(self):
            self._microwave().cw_off()
            if self._awg() is not None:
                self._awg().stop_output()
            try:
                self._data_scanner()._gate_on_external_clock = self._pulsed_initialGate
                del self._pulsed_initialGate
            except:
                pass  #Likely the start was never run
            

        self.pulsedOdmrScanner = self.ScanDevice('Pulsed ODMR',
                lambda x: setattr(self._microwave(), 'cw_frequency', x),
                lambda : _pulsed_ODMR_getY(self),
                data_labels=['Frequency','Ratio'], # x, y1, y2,...
                data_units=['Hz',''],
                static_read_parameters={},
                static_set_parameters={'RF Power': (lambda power: setattr(self._microwave(), 'cw_power', power), -60, 'dBm'),
                                       'Ratio Numerator': (lambda channel: setattr(self,'_pulsed_numerator_channel', channel), 
                                                           self._pulsed_numerator_channel, '', scanner_channels_G),
                                       'Ratio Denominator': (lambda channel: setattr(self,'_pulsed_denominator_channel', channel), 
                                                             self._pulsed_denominator_channel, '', scanner_channels_G),},
                start_function=lambda : _pulsed_start_scan(self),
                end_function=lambda : _pulsed_end_scan(self),
                dependencies=['_awg','_microwave'],
                parent = self
        )
        self.pulsedRabiScanner = self.ScanDevice('Rabi',
            lambda x: self._awg().set_pulse_time(x),
            lambda : _pulsed_ODMR_getY(self),
            data_labels=['Time','Ratio'], # x, y1, y2,...
            data_units=['s',''],
            static_read_parameters={},
            static_set_parameters={'RF Power': (lambda power: setattr(self._microwave(), 'cw_power', power), -60, 'dBm'),
                                   'Frequency': (lambda frequency: setattr(self._microwave(), 'cw_frequency', frequency), 2.7e9, 'Hz'),
                                   'Ratio Numerator': (lambda channel: setattr(self,'_pulsed_numerator_channel', channel), 
                                                       self._pulsed_numerator_channel, '', scanner_channels_G),
                                   'Ratio Denominator': (lambda channel: setattr(self,'_pulsed_denominator_channel', channel), 
                                                         self._pulsed_denominator_channel, '', scanner_channels_G),},
            start_function=lambda : _pulsed_start_scan(self),
            end_function=lambda : _pulsed_end_scan(self),
            dependencies=['_awg','_microwave'],
            parent = self
        )


        self.device_dict = {} # For populating list
        for v in self.__dict__.values():
            if hasattr(v, '_scanDevice_'):
                deps = v._dependencies
                if deps is not None:
                    if type(deps) is str:
                        deps = [deps]
                    for dep in deps:
                        if not hasattr(self,dep):
                            self.log.error(f'Device {v.name} has undeclared dependency: {dep}')
                            continue  #Dependency not found
                        if getattr(self,dep) is None:
                            self.log.info(f'Device {v.name} missing dependency: {dep}')
                            continue  #Dependency not found
                self.device_dict[v.name] = v  


        # # Set up fit model and container
        # self._fit_config_model = FitConfigurationsModel(parent=self)
        # self._fit_config_model.load_configs(self._fit_configs)
        # self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)


        # Connect signals
        self.sigLineReady.connect(self._process_data)
        self._sigAcquire.connect(self._scan_worker.acquire_frame)
        self._scan_worker.sigWorkerFinished.connect(
            self._on_worker_finished,
            QtCore.Qt.ConnectionType.QueuedConnection
        )


    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # Stop measurement if it is still running
        self.sigLineReady.disconnect(self._process_data)
        self._sigAcquire.disconnect()
        self._scan_worker.sigWorkerFinished.disconnect(self._on_worker_finished)
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
        #print("setting device to",value)
        if value in self.device_dict.keys():
            self._device_select = value
            self.sigDeviceUpdated.emit(value)
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
        if self._device_select not in self._x_range:
            return (0,0,0)
        return self._x_range[self._device_select]
    
    @x_range.setter
    def x_range(self,value):
        self._x_range[self._device_select] = value
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
        assert value>=0, 'time_wait must be greater than or equal to 0'
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
    def set_static_set_parameter_value(self,device,label,value):
        self.device_dict[device].update_static_set_parameter_value(label,value)
        self.sigScanParametersUpdated.emit({f'{device}/{label}' : value})

    @QtCore.Slot()
    def set_scan_parameter_value(self,label,value):
        if f'{self.scan_device}/' in label:
            self.set_static_set_parameter_value(self.scan_device,label,value)
        else:
            if label in ['x_range','number_scans','time_per','time_wait','shuffle_x']:
                setattr(self,label,value)
            else:
                raise ValueError('Unexpected label request to be set:',label)


    @QtCore.Slot()
    def start_scan(self):
        """ Starting a scan.        
        """
        
        sleep(0.1)  #Brief pause to allow settings to set in case start clicked on immediately from other setting. Maybe better way of doing this?
        if self.x_range[2] == 0:
            self.log.error('X range not set for device, cannot start scan.')
            return
        with self._threadlock:
            if self.module_state() != 'idle':
                self.log.warning('Can not start scan. Measurement is already running.')
                return

            self.module_state.lock()

            try:
                scanner = self._data_scanner()
                device = self.device_dict[self._device_select]

                if self._time_per >1:  #DAQ has min rate of 1 Hz, so collect multiple and average.
                    scanner.set_sample_rate(100/self._time_per)
                    scanner.set_frame_size(100)
                else:
                    scanner.set_sample_rate(1/self._time_per)
                    scanner.set_frame_size(1)

                self._x_data = np.linspace(*self.x_range)

                device.start_scan(self._x_data[0])  # This will set any static parameters, set the device to the first x value, and start the device.

                self._scanner_channels = list(scanner.active_channels)
                self.initialize_data()

                self.sigScanDataUpdated.emit()
                self.sigScanStateUpdated.emit(True)

                self._scan()  # Start the scanner loop.
            except Exception as e:
                self.stop_scan()  # Stop device, clear lock
                self.log.error(f'Error while starting scan: {e}')


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
            self.device_dict[self._device_select].start_scan(leave_x=True)
            self.sigScanStateUpdated.emit(True)
            self._scan()  # Re-start the scanner loop.

    @QtCore.Slot()
    def stop_scan(self):
        """ Stop the scan.
        """
        with self._threadlock:
            if self.module_state() == 'locked':
                self.module_state.unlock()  #Stop scanning before turning off device.
            try:
                self.device_dict[self._device_select].end_scan()
            except Exception as e:
                self.log.error(f'Error stopping scan: {e}')
            
            self.sigScanStateUpdated.emit(False)

    @QtCore.Slot()
    def initialize_data(self):
        """ Initialize/clear the data """
        with self._threadlock:
            #self.clear_all_fits()
            scanner = self._data_scanner()
            device = self.device_dict[self._device_select]
            self._metadata = device._metadata if device._metadata is not None else {}
            self._data_labels = device._data_labels + self._scanner_channels
            self._data_units = device._data_units + [scanner._channel_units[key.split('-')[0]] for key in self._scanner_channels]
            self._data_header = [f'{self._data_labels[ii]} ({self._data_units[ii]})' for ii in range(len(self._data_labels))]
            self._raw_data = np.full((self._number_scans,len(self._x_data),len(self._data_header)),np.nan)
            self._line_counter=0
            self._point_counter=0
            self.sigScanDataUpdated.emit()

    
    @QtCore.Slot()
    def _on_worker_finished(self, error=None):
        """Handle worker completion in logic thread and continue scan loop."""
        if error is None:
            self._scan(True)
        else:
            self.log.error(f'Error acquiring scan frame: {error}')
            self.stop_scan()

    @QtCore.Slot(bool)
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
                # Scanner data first, though it's after device data in the raw_data
                dev_y_len = device.len_y
                res = [np.mean(self._scan_worker.result[channel]) for channel in self._scanner_channels]    
                self._raw_data[self._line_counter][self._point_order[self._point_counter]][1+dev_y_len:] = res

                #Device data
                self._raw_data[self._line_counter][self._point_order[self._point_counter]][0] = self._x_data[self._point_order[self._point_counter]]
                if dev_y_len>0:
                    devY = device.get_y()
                    if devY is not None:
                        dev_y_len = len(devY)
                        self._raw_data[self._line_counter][self._point_order[self._point_counter]][1:1+dev_y_len] = devY

                self._point_counter+=1
                self.sigDataPointReady.emit(True)
            
            if self.module_state() != 'locked':  #Scan was stopped, stop here
                return
            try:
                if self._scan_worker._running:
                    raise RuntimeError('_scan_worker already running, cannot get new data point.') #This is caught below to log.
                
                if (self._point_counter==0):
                    self._point_order = np.arange(len(self._x_data))
                    if self._shuffle_x:
                        np.random.shuffle(self._point_order)


                if self._point_counter>=len(self._x_data):
                    self.sigLineReady.emit(True)
                    #print('Done scanning line',self._line_counter)
                    self._line_counter+=1
                    if self._line_counter>=self._number_scans:
                        self.sigScanComplete.emit(True)
                        self.stop_scan()  #Call end of scan function and unlock.
                        return
                    else:
                        self._point_counter=0
        
                device.set_x(self._x_data[self._point_order[self._point_counter]])
                self._sigAcquire.emit(self._time_wait)
                
            except Exception as e:
                self.stop_scan()  #Stop device, clear lock
                self.log.error(f'Error while getting data point: {e}')
                #These can be used by other components to communicate an error has occured and no data is incoming.
                self.sigDataPointReady.emit(False)
                self.sigLineReady.emit(False)
                self.sigScanComplete.emit(False)
                return
                
    @QtCore.Slot()
    def _process_data(self): #This just builds the signal (average) data array
        data = np.array(self._raw_data)
        mask_incomplete = np.all(np.isfinite(data), axis=(1,2))
        if np.any(mask_incomplete):
            self._signal_data = np.mean(data[mask_incomplete], axis=0)
        else:
            self._signal_data = np.full((data.shape[1], data.shape[2]), np.nan)
    
    @QtCore.Slot(str)
    def save_data(self, tag=None, root_dir=None, metadata=None):
        """ Saves the current data to a file."""
        with self._threadlock:
            # Create and configure storage helper instance
            timestamp = datetime.now()
            if root_dir is None:
                root_dir = self.module_default_data_dir
            tag = tag + '_' if tag else ''

            metadata = metadata if metadata else {}
            metadata['Number of Scans'] = self.raw_data.shape[0]
            metadata['Steps per line'] = self.raw_data.shape[1]
            metadata['Time per point (s)'] = self.time_per
            metadata['Wait time (s)'] = self.time_wait
            metadata['Shuffle Enabled?'] = self.shuffle_x
            metadata.update(self._metadata)

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
            
            #column_headers = self._get_signal_column_headers()
            nametag = f'{tag}{dev_name}_signal'
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


    
