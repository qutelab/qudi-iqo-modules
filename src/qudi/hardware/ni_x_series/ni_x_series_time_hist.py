# -*- coding: utf-8 -*-

"""
This file contains the qudi hardware module to use a National Instruments X-series card for input
of data of a certain length at a given sampling rate and data type.

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
import nidaqmx as ni
from nidaqmx.stream_readers import  CounterReader, AnalogMultiChannelReader

from qudi.util.mutex import RecursiveMutex
from qudi.core.configoption import ConfigOption
from qudi.util.helpers import natural_sort
from qudi.interface.pulse_time_histogram_interface import PulseTimeHistogramInterface



class NIXSeriesPulseTimingInput(PulseTimeHistogramInterface):
    """
    A National Instruments device that can detect and count digital pulses to 
     measure their timing distribution after a trigger pulse.

    !!!!!! NI USB 63XX, NI PCIe 63XX and NI PXIe 63XX DEVICES ONLY !!!!!!

    See [National Instruments X Series Documentation](@ref nidaq-x-series) for details.

    Example config for copy-paste:

    ni_pulse_timing_input:
        module.Class: 'ni_x_series.ni_x_series_time_hist.NIXSeriesPulseTimingInput'
        options:
            device_name : Dev1  #NI Name of DAQ device
            # Digital channels can be source or source-trigger ; if trigger provided, trigger_source below is ignored for that combination
            digital_channels :  # Digital channels available to acquire on
                - PFI8
                - PFI8-PFI3
            analog_channels :  # Analog channels available to acquire on
                - AI0
                - AI3
            trigger_source : PFI0  # Source of timing reset (t=0) trigger ; optional if provided as combo above
            trigger_edge : RISING  # Are digital/trigger sources rising/falling edge?

    """

    # config options
    _device_name = ConfigOption(name='device_name', default='Dev1', missing='warn')
    _digital_channels = ConfigOption(name='digital_channels', missing='error')
    _analog_channels = ConfigOption(name='analog_channels', missing='nothing', default = [])
    _analog_voltage_range = ConfigOption(name='analog_voltage_range', missing='nothing', default = 5)
    _trigger_source = ConfigOption(name='trigger_source',  default = None, missing='nothing')
    _trigger_edge = ConfigOption(name='trigger_edge', default="RISING",
                                 constructor=lambda x: ni.constants.Edge[x.upper()], missing='nothing')
    _enable_dig_filter = ConfigOption(name='enable_dig_filter', default=True)
    #_rw_timeout = ConfigOption('read_write_timeout', default=10, missing='nothing')  #Not implemented yet

    # Defaults
    _sample_rate = '100MHz' #If str, select from internal clocks, if value need to create  a clock.
    _downsample = 1
    _sampling_time_ns = 1000  #How long to measure for after trigger, needs to be <= trigger_period
    _buffer_size = 1_000_000 # Local buffer size for each channel readout, needs to be >> event_rate * sampling_time

    __min_tick_ns = 10   #Fastest sampling rate for device

    ## TODO Perhaps: Allow separate trigger sources for each channel (or for same channel), e.g. for seeing event timing for gated counting. 
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # NIDAQmx device handle
        self._device_handle = None
        # Task handles for NIDAQmx tasks
        self._di_task_handles = list()
        self._ai_task_handle = None
        self._clk_task_handle = None
        # nidaqmx stream reader instances to help with data acquisition
        self._di_readers = dict()
        self._ai_reader = None

        # List of all available counters and terminals for this device
        self.__all_counters = tuple()
        self.__all_digital_terminals = tuple()
        self.__all_analog_terminals = tuple()

        self._thread_lock = RecursiveMutex()

        self._active_channels = set()
        self.data = {}
        self._analog_MA_i = 0


    def on_activate(self):
        """
        Starts up the NI-card and performs sanity checks.
        """

        # Check if device is connected and set device to use
        dev_names = ni.system.System().devices.device_names
        if self._device_name.lower() not in set(dev.lower() for dev in dev_names):    
            raise ValueError(
                f'Device name "{self._device_name}" not found in list of connected devices: '
                f'{dev_names}\nActivation of NIXSeriesInStreamer failed!'
            )
        
        for dev in dev_names:  #Check for correct capitalization etc.
            if dev.lower() == self._device_name.lower():
                self._device_name = dev
                break
            
        self._device_handle = ni.system.Device(self._device_name)

        # Get available sources
        self.__available_timebases = [terminal.split('/')[-1] for terminal in self._device_handle.terminals if 'HzTimebase' in terminal]

        self.__all_counters = tuple(
            ctr.split('/')[-1] for ctr in self._device_handle.co_physical_chans.channel_names if
            'ctr' in ctr.lower())
        self.__all_digital_terminals = tuple(
            term.rsplit('/', 1)[-1].lower() for term in self._device_handle.terminals if 'PFI' in term)
        self.__all_analog_terminals = tuple(
            term.rsplit('/', 1)[-1].lower() for term in self._device_handle.ai_physical_chans.channel_names)

        # Check all inputs
        if type(self._digital_channels) is str:
            self._digital_channels = [self._digital_channels]
        self._digital_channels = set([self._extract_terminal(chan) for chan in self._digital_channels])
        
        dc_verified = []
        for channel in self._digital_channels:
            channelVerified=True
            for chI in channel.split('-'):
                if chI not in self.__all_digital_terminals:
                    channelVerified=False
                    self.log.error(f'Channel not found on NI device, omitting: {chI}')
            if channelVerified:
                dc_verified.append(channel)
                
        self._digital_channels = set(dc_verified)

        # if len(self._digital_channels)==0:  # Is having a digital channel strictly required?
        #     raise ValueError(
        #         'No valid digital sources defined in config. Activation of '
        #         'NIXSeriesPulseTimingInput failed!'
        #     )
        if type(self._sample_rate) is not str:  #For implementing using an internal clock as a variable timebase.
            max_digital=3
        else:
            max_digital = 4
        if len(self._digital_channels) > max_digital:
            raise ValueError(
                'Too many digital channels specified. Maximum number of digital channels is 3 (or 4 without internal clock).'
            )

        if type(self._analog_channels) is str:
            self._analog_channels = [self._di_analog_channelsgital_channels]
        self._analog_channels = set([self._extract_terminal(chan) for chan in self._analog_channels])
        
        ac_verified = []
        for channel in self._analog_channels:
            channelVerified=True
            for chI in channel.split('-'):
                if chI not in self.__all_analog_terminals:
                    channelVerified=False
                    self.log.error(f'Channel not found on NI device, omitting: {chI}')
            if channelVerified:
                ac_verified.append(channel)
                
        self._analog_channels = set(ac_verified)
        
        self._active_channels = self._digital_channels | self._analog_channels

        if len(self._active_channels)==0:
            raise ValueError(' No valid digital or analog sources defined in config. Activation of NIXSeriesPulseTimingInput failed.')

        #Typechecking handled herein
        self.clock_source = self._sample_rate  
        self.trigger_source = self._trigger_source
        self.downsample = self._downsample
        self.sampling_time_ns = self._sampling_time_ns


    def on_deactivate(self):
        """ Shut down the NI card.
        """
        self.terminate_all_tasks()
        return

    @property
    def clock_source(self):
        return self._clock_source

    @clock_source.setter
    def clock_source(self,value):
        available_freqs = [tx.split('Timebase')[0] for tx in self.__available_timebases]
        if type(self._sample_rate) != str:
            raise NotImplemented(f'Timebase other than fixed-internal not yet available, choose from {available_freqs}')
        if value+'Timebase' in self.__available_timebases:
            self._clock_source =  value+"Timebase"
        elif value in self.__available_timebases:
            self._clock_source =  value
        else:
            raise ValueError(f'Requested timebase not available: {value}. Choose from {self.__available_timebases}')

    @property
    def trigger_source(self):
        return self._trigger_source

    @trigger_source.setter
    def trigger_source(self, value):
        if value is None:
            for chI in self.active_channels:
                if len(chI).split('-')==1:
                    raise ValueError(f'Trigger source required for active channel {chI}')
            self._trigger_source=value
        else:
            value = self._extract_terminal(value)
            if value not in self.__all_digital_terminals:
                raise ValueError(f'Trigger source not found in digital channels. {value}')
            else:
                self._trigger_source=value

    @property
    def sampling_time_ns(self):
        return self._sampling_time_ns

    @sampling_time_ns.setter
    def sampling_time_ns(self, value):
        if value < self.__min_tick_ns:
            raise ValueError(f'sampling_time_ns must be >{self.__min_tick_ns} ns')
        else:
            self._sampling_time_ns=value//self.__min_tick_ns*self.__min_tick_ns

    @property
    def downsample(self):
        return self._downsample

    @downsample.setter
    def downsample(self,value):
        assert type(value)==int, 'downsample must be int'
        assert value>=1, 'downsample value must be at least 1'
        self._downsample=value

    @property
    def active_channels(self):
        return self._active_channels

    def set_active_channels(self, channels):
        """ Will set the currently active channels. All other channels will be deactivated.

        @param iterable(str) channels: Iterable of channel names to set active.
        """
        assert hasattr(channels, '__iter__') and not isinstance(channels, str), \
            f'Given input channels {channels} are not iterable'

        assert self.module_state() != 'locked', \
            'Unable to change active channels while finite sampling is running. New settings ignored.'

        channels = tuple(self._extract_terminal(chI) for chI in channels)

        assert set(channels).issubset(self._digital_channels|self._analog_channels), \
            f'Trying to set invalid input channels "' \
            f'{set(channels).difference(self._digital_channels|self._analog_channels)}" not defined in config.'

        with self._thread_lock:
            self._active_channels = set(channels)


    def start_buffered_acquisition(self):
        """ Will start the acquisition of a data frame in a non-blocking way.
        Must return immediately and not wait for the data acquisition to finish.

        Must raise exception if data acquisition can not be started.
        """
        assert self.module_state() == 'idle', \
            'Unable to start data acquisition. Data acquisition already in progress.'
        self.module_state.lock()

        # set up tasks
        # if self._init_sample_clock() < 0:
        #     self.terminate_all_tasks()
        #     self.module_state.unlock()
        #     raise NiInitError('Sample clock initialization failed; all tasks terminated')
        if self._init_digital_tasks() < 0:
            self.terminate_all_tasks()
            self.module_state.unlock()
            raise NiInitError('Counter task initialization failed; all tasks terminated')

        if self._init_analog_task() < 0:
            self.terminate_all_tasks()
            self.module_state.unlock()
            raise NiInitError('Analog task initialization failed; all tasks terminated')

        if '100MHz' in self.clock_source: #TODO: interpret timebase programatically.
            tick_ns = 10
        elif '20MHz' in self.clock_source:
            tick_ns = 50
        elif '100kHz' in self.clock_source:
            tick_ns = 10000
        else:
            raise NotImplementedError('Only 100MHz, 20MHz and 100kHz timebases have been implemented')
        # start tasks
        self._data_buffer = np.zeros(self._buffer_size,dtype=np.uint32)
        self.data = {}
        self._analog_MA_i = 0
        if len(self._di_task_handles) > 0:
            try:
                for chan, reader in self._di_readers.items():
                    reader._task.start()
                    bin_width_ns = tick_ns * self.downsample
                    n_bins = int(self.sampling_time_ns // bin_width_ns)
                    self.data[chan] = (
                        np.arange(n_bins + 1) * bin_width_ns, # edges
                        np.zeros(n_bins, dtype=int),    # counts
                    )
            except ni.DaqError as e:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise e

        if self._ai_task_handle is not None:
            try:
                analog_channels= self.active_channels & self._analog_channels
                for num, ai_channel in enumerate(analog_channels):
                    self.data[ai_channel] = (
                        np.arange(self._analog_samples+1) / self._analog_sample_rate * 1e9,  # edges, in ns
                        np.zeros(self._analog_samples,dtype=float)  # values
                    )
                self._ai_task_handle.start()
            except ni.DaqError:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise


        # if not self._sample_on_external_clock:
        #     try:
        #         self._clk_task_handle.start()
        #     except ni.DaqError:
        #         self.terminate_all_tasks()
        #         self.module_state.unlock()
        #         raise

    def stop_buffered_acquisition(self):
        """ Will abort the currently running data frame acquisition.
        Will return AFTER the data acquisition has been terminated without waiting for all samples
        to be acquired (if possible).

        Must NOT raise exceptions if no data acquisition is running.
        """
        if self.module_state() == 'locked':
            self.terminate_all_tasks()
            self.module_state.unlock()

    def acquire_sample(self):
        with self._thread_lock:
            if (len(self._di_readers)==0) and (self._ai_reader is None):
                self.log.warning(f'acquire_sample called while no data_readers were initialized')
                return None
            for chan,reader in self._di_readers.items():
                task = reader._task
                n = task.in_stream.avail_samp_per_chan  # Need to pass the array-view correctly sized to match what's in the buffer.
                if (n==0) and self.module_state() == 'idle':
                    self.log.error('Unable to read data. Device is not running and no data in buffer.')
                    return None
                if n > 0:
                    buffer = self._data_buffer
                    hist =  self.data[chan][1]
                    if n>len(buffer):
                        print('Warning: More samples than buffer size:',n)
                    n = min(n, len(buffer))  # guard against a burst bigger than your scratch buffer
                    reader.read_many_sample_uint32(buffer[:n], number_of_samples_per_channel=n)
                    buffer[n:] = 0

                    bc = np.bincount(buffer[:n]//self.downsample)
                    bc = bc[:len(hist)] 
                    hist[:len(bc)] += bc

            self._acquire_analog()
            return self.data


    def acquire_sample_diff(self):
        with self._thread_lock:
            if (len(self._di_readers)==0) and (self._ai_reader is None):
                self.log.warning(f'acquire_sample called while no data_readers were initialized')
                return None
            for chan,reader in self._di_readers.items():
                task = reader._task
                n = task.in_stream.avail_samp_per_chan  # Need to pass the array-view correctly sized to match what's in the buffer.
                if (n==0) and self.module_state() == 'idle':
                    self.log.error('Unable to read data. Device is not running and no data in buffer.')
                    return None
                if n > 0:
                    buffer = self._data_buffer
                    hist =  self.data[chan][1]
                    if n>len(buffer):
                        print('Warning: More samples than buffer size:',n)
                    n = min(n, len(buffer))  # guard against a burst bigger than your scratch buffer
                    reader.read_many_sample_uint32(buffer[:n], number_of_samples_per_channel=n)
                    buffer[n:] = 0

                    bc = np.bincount(np.diff(buffer[:n])//self.downsample)
                    bc = bc[:len(hist)]   # Hm, do I want sampling time? Or just use the triggers to automatically reset.
                    hist[:len(bc)] += bc
            self._acquire_analog()
            return self.data

    def _acquire_analog(self):
        # Analog acquisition acquires once per poll due to nature of Analog readout being quite different than counter
        if self._ai_reader is not None:
            analog_channels = self.active_channels & self._analog_channels
            data_buffer = np.zeros(self._analog_samples * len(analog_channels))
            read_samples_N = self._ai_reader.read_many_sample(
                data_buffer,
                number_of_samples_per_channel=self._analog_samples,)
                #timeout=self._rw_timeout)
            # if read_samples_N != number_of_samples:
            #     return data
            self._ai_task_handle.stop()  #Re-arm trigger and readout
            self._ai_task_handle.start()
            self._analog_MA_i+=1
            for num, ai_channel in enumerate(analog_channels):
                hist = self.data[ai_channel][1] #Edit array in place
                if self._analog_MA_i==1:
                    hist += data_buffer[num * self._analog_samples:(num + 1) * self._analog_samples]
                else: #Take moving average
                    new_data = data_buffer[num * self._analog_samples:(num + 1) * self._analog_samples]
                    hist *= (1-1/self._analog_MA_i)  
                    hist += new_data*(1/self._analog_MA_i)
                    

    def terminate_all_tasks(self):
        err = 0

        self._di_readers = dict()
        self._ai_reader = None

        while len(self._di_task_handles) > 0:
            try:
                if not self._di_task_handles[-1].is_task_done():
                    self._di_task_handles[-1].stop()
                self._di_task_handles[-1].close()
            except ni.DaqError:
                self._di_task_handles[-1].close()
                self.log.exception('Error while trying to terminate digital counter task.')
                err = -1
            finally:
                del self._di_task_handles[-1]
        self._di_task_handles = list()

        if self._ai_task_handle is not None:
            try:
                if not self._ai_task_handle.is_task_done():
                    self._ai_task_handle.stop()
                self._ai_task_handle.close()
            except ni.DaqError:
                self.log.exception('Error while trying to terminate clock task.')
                err = -1
        self._ai_task_handle = None

        if self._clk_task_handle is not None:
            try:
                if not self._clk_task_handle.is_task_done():
                    self._clk_task_handle.stop()
                self._clk_task_handle.close()
            except ni.DaqError:
                self.log.exception('Error while trying to terminate clock task.')
                err = -1
        self._clk_task_handle = None
        return err

    def reset_hardware(self):
            """
            Resets the NI hardware, so the connection is lost and other programs can access it.
            @return int: error code (0:OK, -1:error)
            """
            try:
                self._device_handle.reset_device()
                self.log.info('Reset device {0}.'.format(self._device_name))
            except ni.DaqError:
                self.log.exception('Could not reset NI device {0}'.format(self._device_name))
                return -1
            return 0

    # =============================================================================================
    # def _init_clock(self):  # TODO: Implement using clock as variable timebase. This isn't being used otherwise.
    #     """
    #     Initialize internal clock

    #     @return int: error code (0: OK, -1: Error)
    #     """
    #     if self._clk_task_handle is not None:
    #         self.log.error('Sample clock task is already running. Unable to set up a new clock '
    #                         'before you close the previous one.')
    #         return -1

    #     if (not self._sample_on_external_clock) or (len(self._external_sample_clock_source)==0):
    #         # Try to find an available counter
    #         for src in self.__all_counters:
    #             # Check if task by that name already exists
    #             task_name = 'SampleClock_{0:d}'.format(id(self))
    #             try:
    #                 task = ni.Task(task_name)
    #             except ni.DaqError:
    #                 self.log.exception(f'Could not create task with name "{task_name}".')
    #                 return -1

    #             # Try to configure the task
    #             try:
    #                 self._clock_channel = task.co_channels.add_co_pulse_chan_freq(
    #                     '/{0}/{1}'.format(self._device_name, src),
    #                     freq=self._sample_rate,
    #                     idle_state=ni.constants.Level.HIGH if self._trigger_edge==ni.constants.Edge.FALLING else ni.constants.Level.LOW)
    #                 task.timing.cfg_implicit_timing(
    #                     sample_mode=ni.constants.AcquisitionType.CONTINUOUS,)  #Sample clock can just start and stop, this removes N+1 buffer warning
    #                     #samps_per_chan=self._frame_size + 1)
    #             except ni.DaqError:
    #                 self.log.exception('Error while configuring sample clock task.')
    #                 try:
    #                     del task
    #                 except NameError:
    #                     pass
    #                 return -1

    #             # Try to reserve resources for the task
    #             try:
    #                 task.control(ni.constants.TaskMode.TASK_RESERVE)
    #             except ni.DaqError:
    #                 # Try to clean up task handle
    #                 try:
    #                     task.close()
    #                 except ni.DaqError:
    #                     pass
    #                 try:
    #                     del task
    #                 except NameError:
    #                     pass

    #                 # Return if no counter could be reserved
    #                 if src == self.__all_counters[-1]:
    #                     self.log.exception('Error while setting up clock. Probably because no free '
    #                                     'counter resource could be reserved.')
    #                     return -1
    #                 continue
    #             break

    #         self._clk_task_handle = task

    #         internal_clock_term = '/{0}InternalOutput'.format(self._clk_task_handle.channel_names[0])
    #         self._clock_channel_term = internal_clock_term
                                                            
    #         if self._physical_sample_clock_output is not None:
    #             ni.system.System().connect_terms(source_terminal=internal_clock_term,
    #                                             destination_terminal='/{0}/{1}'.format(
    #                                                 self._device_name, self._physical_sample_clock_output))

    #     else: #Use only external clock(s), set here default for non-specified inputs.
    #         if '' in self._external_sample_clock_source:
    #             self._clock_channel_term = self._external_sample_clock_source['']
    #         elif 'default' in self._external_sample_clock_source:
    #             self._clock_channel_term = self._external_sample_clock_source['default']
    #         else:
    #             self._clock_channel_term = list(self._external_sample_clock_source.values())[0] #Get first value
    #             if type(self._clock_channel_term) == list:  #In case first value is a list, pick first.
    #                 self._clock_channel_term=self._clock_channel_term[0]
    #         self._clock_channel_term = '/{0}/{1}'.format(self._device_name, self._clock_channel_term)

    #     return 0

    def _init_digital_tasks(self):
        """
        Set up tasks for digital event counting.

        @return int: error code (0:OK, -1:error)
        """

        digital_channels = self.active_channels & self._digital_channels
        if not digital_channels:
            return 0
        if self._di_task_handles:
            self.log.error('_init_digital_tasks called while tasks still running, terminating all tasks'
                            'Setting up counter tasks has failed.')
            self.terminate_all_tasks()
            return -1

        # Set up digital counting tasks
        for i, chan in enumerate(digital_channels):

            task_name = f'{chan}_timing_task'

            if len(chan.split('-'))>1:
                trigger_source = chan.split('-')[1]
                chan = chan.split('-')[0]
            else:
                trigger_source = self.trigger_source
            # Try to find available counter
            for ctr in self.__all_counters:
                ctr_name = self._term_path(ctr)
                try:
                    task = ni.Task(task_name)
                except ni.DaqError:
                    self.log.exception(f'Could not create task with name "{task_name}"')
                    self.terminate_all_tasks()
                    return -1

                try:
                    ci_chan = task.ci_channels.add_ci_count_edges_chan(
                        ctr_name,
                        edge=ni.constants.Edge.RISING) #Counting on internal clock, assume rising edge.

                    ci_chan.ci_count_edges_term = self._term_path(self.clock_source)

                    task.timing.cfg_samp_clk_timing(
                        rate=10_000_000,
                        source=self._term_path(chan),
                        sample_mode=ni.constants.AcquisitionType.CONTINUOUS,
                        active_edge=self._trigger_edge
                    )
                    
                    if self._enable_dig_filter:
                        task.timing.samp_clk_dig_fltr_enable = True
                        task.timing.samp_clk_dig_fltr_min_pulse_width = 20e-9

                    ci_chan.ci_count_edges_count_reset_enable = True
                    ci_chan.ci_count_edges_count_reset_term = self._term_path(trigger_source)
                    ci_chan.ci_count_edges_count_reset_active_edge = self._trigger_edge
                    ci_chan.ci_count_edges_count_reset_reset_cnt = 0

                except:
                    try:
                        task.close()
                        del task
                    except NameError:
                        pass
                    self.terminate_all_tasks()
                    self.log.exception('Something went wrong while configuring digital counter '
                                        'task for channel "{0}".'.format(chan))
                    return -1
                

                try:
                    task.control(ni.constants.TaskMode.TASK_RESERVE)
                except ni.DaqError:
                    try:
                        task.close()
                    except ni.DaqError:
                        self.log.exception('Unable to close task.')
                    try:
                        del task
                    except NameError:
                        self.log.exception('Some weird namespace voodoo happened here...')

                    if ctr == self.__all_counters[-1]:
                        self.log.exception('Unable to reserve resources for digital counting task '
                                            'of channel "{0}". No available counter found!'
                                            ''.format(chan))
                        self.terminate_all_tasks()
                        return -1
                    continue

                try:
                    self._di_readers[chan] = CounterReader(task.in_stream)
                    #self._di_readers[-1].verify_array_shape = False
                except ni.DaqError:
                    self.log.exception(
                        'Something went wrong while setting up the digital counter reader for '
                        'channel "{0}".'.format(chan))
                    self.terminate_all_tasks()
                    try:
                        task.close()
                    except ni.DaqError:
                        self.log.exception('Unable to close task.')
                    try:
                        del task
                    except NameError:
                        self.log.exception('Some weird namespace voodoo happened here...')
                    return -1

                self._di_task_handles.append(task)
                break
        return 0

    
    def _init_analog_task(self):
        """
        Set up task for analog voltage measurement.

        @return int: error code (0:OK, -1:error)
        """
        analog_channels = self.active_channels & self._analog_channels
        if not analog_channels:
            return 0
        if self._ai_task_handle:
            self.log.error(
                'Analog input task has already been generated. Unable to set up analog in task.')
            self.terminate_all_tasks()
            return -1
        # if self._clk_task_handle is None and (len(self._external_sample_clock_source)==0):
        #     self.log.error(
        #         'No sample clock task has been generated and no external clock source specified. '
        #         'Unable to create analog voltage measurement tasks.')
        #     self.terminate_all_tasks()
        #     return -1


        # Set up analog input task
        task_name = 'AnalogIn_{0:d}'.format(id(self))
        try:
            ai_task = ni.Task(task_name)
        except ni.DaqError:
            self.log.exception('Unable to create analog-in task with name "{0}".'.format(task_name))
            self.terminate_all_tasks()
            return -1

        try:
            ai_ch_str = ','.join([self._term_path(c) for c in analog_channels])
            ai_task.ai_channels.add_ai_voltage_chan(ai_ch_str,
                                                    max_val=self._analog_voltage_range,
                                                    min_val=-self._analog_voltage_range,
                                                    terminal_config = ni.constants.TerminalConfiguration.RSE)
            _analog_buffer_size = ai_task.in_stream.input_buf_size
            if _analog_buffer_size == 0:
                _analog_buffer_size = ai_task.in_stream.input_onbrd_buf_size  #Hardware max rather than 'as-configured' size

            _analog_max_sample_rate = ai_task.timing.samp_clk_max_rate  #Max sample rate for Analog
            if self.clock_source == '100kHzTimebase':
                self._analog_sample_rate = min(_analog_max_sample_rate,100_000)
            else:
                self._analog_sample_rate = _analog_max_sample_rate
            self._analog_samples = max(int(self.sampling_time_ns/1e9*self._analog_sample_rate),2)  #Minimum value is 2.
            if self._analog_samples > _analog_buffer_size:
                self.log.warning(f'Requested acquisition time greater than analog buffer, limiting to {_analog_buffer_size} samples')
                self._analog_samples = _analog_buffer_size
            if self._analog_samples==2:
                self.log.warning(f'Only enough time to collect 2 analog sample at analog max {self._analog_sample_rate} Hz')
            ai_task.timing.cfg_samp_clk_timing(rate=self._analog_sample_rate,
                                                sample_mode=ni.constants.AcquisitionType.FINITE,
                                                samps_per_chan=self._analog_samples)
            ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
                                                trigger_source=self._term_path(self._trigger_source),
                                                trigger_edge=self._trigger_edge)
        except ni.DaqError:
            self.log.exception(
                'Something went wrong while configuring the analog-in task.')
            try:
                del ai_task
            except NameError:
                pass
            self.terminate_all_tasks()
            return -1

        try:
            ai_task.control(ni.constants.TaskMode.TASK_RESERVE)
        except ni.DaqError:
            try:
                ai_task.close()
            except ni.DaqError:
                self.log.exception('Unable to close task.')
            try:
                del ai_task
            except NameError:
                self.log.exception('Some weird namespace voodoo happened here...')

            self.log.exception('Unable to reserve resources for analog-in task.')
            self.terminate_all_tasks()
            return -1

        try:
            self._ai_reader = AnalogMultiChannelReader(ai_task.in_stream)
            self._ai_reader.verify_array_shape = False
        except ni.DaqError:
            try:
                ai_task.close()
            except ni.DaqError:
                self.log.exception('Unable to close task.')
            try:
                del ai_task
            except NameError:
                self.log.exception('Some weird namespace voodoo happened here...')
            self.log.exception('Something went wrong while setting up the analog input reader.')
            self.terminate_all_tasks()
            return -1

        self._ai_task_handle = ai_task
        return 0


    @staticmethod
    def _extract_terminal(term_str):
        """
        Helper function to extract the bare terminal name from a string and strip it of the device
        name and dashes.
        Will return the terminal name in lower case.

        @param str term_str: The str to extract the terminal name from
        @return str: The terminal name in lower case
        """
        if len(term_str.split('-'))>1: #Allow joined channels for source-trigger inputs.
            return '-'.join(NIXSeriesPulseTimingInput._extract_terminal(chI) for chI in term_str.split('-'))
        term = term_str.strip('/').lower()
        if 'dev' in term:
            term = term.split('/', 1)[-1]
        return term

    def _term_path(self,terminal):
        return '/{0}/{1}'.format(self._device_name, terminal)

class NiInitError(Exception):
    pass