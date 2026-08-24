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
from datetime import datetime
import matplotlib.pyplot as plt
from PySide6 import QtCore

from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.util.datastorage import TextDataStorage
from qudi.interface.pulse_time_histogram_interface import PulseTimeHistogramInterface


class TimeHistLogic(LogicBase):
    """
    This is the Logic class for acquiring and displaying live pulse-timing histograms, e.g. from a
    time-tagging/counting device such as the NI X-Series pulse timing input hardware module.

    example config for copy-paste:

    time_hist_logic:
        module.Class: 'time_hist_logic.TimeHistLogic'
        connect:
            data_scanner: ni_pulse_timing_input
            awg: simple_awg_logic  # Optional, for starting/stopping a synchronized AWG
        options:
            poll_interval_ms : 100  # How many ms between polling events to the hardware buffer
            save_thumbnails : True
    """

    # declare connectors
    _data_scanner = Connector(name='data_scanner', interface=PulseTimeHistogramInterface)
    _awg = Connector(name='awg', interface='PulserInterface', optional=True)

    # declare config options
    _poll_interval_ms = ConfigOption(name='poll_interval_ms', default=100)
    _save_thumbnails = ConfigOption(name='save_thumbnails', default=True)

    # declare status variables
    _sample_rate = StatusVar(default='100MHz')  # Select from internal clocks of the hardware
    _downsample = StatusVar(default=1)
    _sampling_time_ns = StatusVar(default=10_000)  # How long to measure for after trigger
    _buffer_size = StatusVar(default=1_000_000)  # Local read buffer size, needs to be >> event_rate * sampling_time
    _active_channels = StatusVar(default=None)

    # Signals
    sigDataAvailable = QtCore.Signal(object)  # {channel: (edges, counts)}
    sigAcquisitionStateChanged = QtCore.Signal(bool)
    sigSettingsUpdated = QtCore.Signal(dict)
    sigSaveComplete = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._scan_active = False
        self.data = {}

    def on_activate(self):
        hardware = self._data_scanner()

        # Push stored settings to the hardware. Fall back to the hardware defaults if rejected.
        try:
            self.set_sample_rate(self._sample_rate)
        except Exception as e:
            self.log.warning(f'Could not apply stored sample rate {self._sample_rate}: {e}')
            self._sample_rate = hardware.clock_source

        try:
            self.set_downsample(self._downsample)
        except Exception as e:
            self.log.warning(f'Could not apply stored downsample {self._downsample}: {e}')

        try:
            self.set_sampling_time_ns(self._sampling_time_ns)
        except Exception as e:
            self.log.warning(f'Could not apply stored sampling time {self._sampling_time_ns}: {e}')

        try:
            self.set_buffer_size(self._buffer_size)
        except Exception as e:
            self.log.warning(f'Could not apply stored buffer size {self._buffer_size}: {e}')

        available = self.available_channels
        channels = self._active_channels
        if not channels:
            channels = available
        else:
            channels = [ch for ch in channels if ch in available]
            if not channels:
                channels = available
        try:
            self.set_active_channels(channels)
        except Exception as e:
            self.log.warning(f'Could not apply stored active channels {channels}: {e}')

    def on_deactivate(self):
        if self.module_state() == 'locked':
            self.stop_acquisition()

    @property
    def available_channels(self):
        """ Returns the list of digital channel names configured on the hardware module. """
        try:
            return sorted(self._data_scanner()._digital_channels)
        except AttributeError:
            return []

    @property
    def active_channels(self):
        return list(self._data_scanner().active_channels)

    @property
    def sample_rate(self):
        return self._sample_rate

    @property
    def downsample(self):
        return self._downsample

    @property
    def sampling_time_ns(self):
        return self._sampling_time_ns

    @property
    def buffer_size(self):
        return self._buffer_size

    @property
    def acquisition_running(self):
        return self.module_state() == 'locked'

    def set_active_channels(self, channels):
        with self._thread_lock:
            assert not self.acquisition_running, \
                'Unable to change active channels while acquisition is running.'
            try:
                self._data_scanner().set_active_channels(channels)
            except Exception as e:
                self.log.error(f'Unable to set active channels: {e}')
                return self.active_channels
            self._active_channels = self.active_channels
            self.sigSettingsUpdated.emit({'active_channels': self._active_channels})
            return self._active_channels

    def set_sample_rate(self, value):
        with self._thread_lock:
            assert not self.acquisition_running, \
                'Unable to change sample rate while acquisition is running.'
            self._data_scanner().clock_source = value
            self._sample_rate = value
            self.sigSettingsUpdated.emit({'sample_rate': value})

    def set_downsample(self, value):
        with self._thread_lock:
            assert not self.acquisition_running, \
                'Unable to change downsample while acquisition is running.'
            value = int(value)
            assert value >= 1, 'downsample must be an integer >= 1'
            self._data_scanner()._downsample = value
            self._downsample = value
            self.sigSettingsUpdated.emit({'downsample': value})

    def set_sampling_time_ns(self, value):
        with self._thread_lock:
            assert not self.acquisition_running, \
                'Unable to change sampling time while acquisition is running.'
            value = int(value)
            assert value > 0, 'sampling_time_ns must be > 0'
            self._data_scanner()._sampling_time_ns = value
            self._sampling_time_ns = value
            self.sigSettingsUpdated.emit({'sampling_time_ns': value})

    def set_buffer_size(self, value):
        with self._thread_lock:
            assert not self.acquisition_running, \
                'Unable to change buffer size while acquisition is running.'
            value = int(value)
            assert value > 0, 'buffer_size must be > 0'
            self._data_scanner()._buffer_size = value
            self._buffer_size = value
            self.sigSettingsUpdated.emit({'buffer_size': value})

    @QtCore.Slot()
    def start_acquisition(self):
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.log.warning('Unable to start acquisition. Acquisition already running.')
                return
            self.module_state.lock()
            try:
                if self._awg() is not None:
                    self._awg().start()
                self._data_scanner().start_buffered_acquisition()
            except Exception as e:
                self.module_state.unlock()
                self.log.error(f'Error while starting acquisition: {e}')
                return

            self._scan_active = True
            self.sigAcquisitionStateChanged.emit(True)
            QtCore.QTimer.singleShot(int(self._poll_interval_ms), self._acquire_data)

    @QtCore.Slot()
    def stop_acquisition(self):
        with self._thread_lock:
            self._scan_active = False
            try:
                self._data_scanner().stop_buffered_acquisition()
            except Exception as e:
                self.log.error(f'Error while stopping acquisition: {e}')
            if self._awg() is not None:
                try:
                    self._awg().stop()
                except Exception as e:
                    self.log.error(f'Error while stopping awg: {e}')
            if self.module_state() == 'locked':
                self.module_state.unlock()
            self.sigAcquisitionStateChanged.emit(False)

    @QtCore.Slot()
    def clear_data(self):
        """ Zero the accumulated histogram counts without stopping a running acquisition. """
        with self._thread_lock:
            for edges, counts in self.data.values():
                counts[:] = 0
            self.sigDataAvailable.emit(self.data)

    @QtCore.Slot()
    def _acquire_data(self):
        if not self._scan_active:
            return

        with self._thread_lock:
            data = self._data_scanner().acquire_sample()
            if data is not None:
                self.data = data
                self.sigDataAvailable.emit(self.data)
            else:
                self.log.error('Acquisition error, stopping acquisition')
                self.stop_acquisition()
                return  # Likely error, the hw will have logged the details.

            if self._scan_active:
                QtCore.QTimer.singleShot(int(self._poll_interval_ms), self._acquire_data)

    @QtCore.Slot(str)
    def save_data(self, tag=None, root_dir=None, metadata=None):
        """ Saves the current histogram data (one file per channel) to disk. """
        with self._thread_lock:
            if not self.data:
                self.log.warning('No histogram data available to save.')
                self.sigSaveComplete.emit(False)
                return

            timestamp = datetime.now()
            if root_dir is None:
                root_dir = self.module_default_data_dir
            tag = f'{tag}_' if tag else ''

            metadata = dict(metadata) if metadata else {}
            metadata['Sample Rate'] = self._sample_rate
            metadata['Downsample'] = self._downsample
            metadata['Sampling Time (ns)'] = self._sampling_time_ns
            metadata['Buffer Size'] = self._buffer_size

            data_storage = TextDataStorage(root_dir=root_dir, column_formats='.6e')

            try:
                for channel, (edges, counts) in self.data.items():
                    edges = np.asarray(edges)[:len(counts)]
                    array = np.column_stack((edges, counts))
                    nametag = f'{tag}TimeHistogram_{channel}'
                    file_path, _, _ = data_storage.save_data(
                        array,
                        metadata=metadata,
                        nametag=nametag,
                        timestamp=timestamp,
                        column_headers=['Time (ns)', 'Counts'],
                        column_dtypes=[float, float],
                    )
                    if self._save_thumbnails:
                        fig = self._draw_figure(edges, counts, channel)
                        data_storage.save_thumbnail(fig, file_path=file_path.rsplit('.', 1)[0])
                        plt.close(fig)
            except Exception as e:
                self.log.error(f'Error while saving histogram data: {e}')
                self.sigSaveComplete.emit(False)
                return

            self.log.info(f'Time histogram data saved to {root_dir}')
            self.sigSaveComplete.emit(True)

    @staticmethod
    def _draw_figure(edges, counts, channel):
        """ Draw a summary figure of a single channel's histogram to save alongside the data. """
        fig, ax = plt.subplots()
        ax.step(edges, counts, where='post')
        ax.set_xlabel('Time (ns)')
        ax.set_ylabel('Counts')
        ax.set_title(f'Channel {channel}')
        return fig
