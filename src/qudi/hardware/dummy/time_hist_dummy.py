# -*- coding: utf-8 -*-

"""
This file contains a dummy hardware module simulating a pulse-timing histogram device.

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

from qudi.util.mutex import RecursiveMutex
from qudi.core.configoption import ConfigOption
from qudi.interface.pulse_time_histogram_interface import PulseTimeHistogramInterface

_TICK_NS = {'100MHz': 10, '20MHz': 50, '100kHz': 10000}


class TimeHistDummy(PulseTimeHistogramInterface):
    """
    A dummy hardware module simulating a pulse-timing histogram device, e.g. for testing
    TimeHistLogic/TimeHistogramGui without real NI hardware attached.

    example config for copy-paste:

    time_hist_dummy:
        module.Class: 'dummy.time_hist_dummy.TimeHistDummy'
        options:
            digital_channels:
                - pfi0
                - pfi1
    """

    _digital_channels = ConfigOption(name='digital_channels', default=['pfi0', 'pfi1'])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self.data = {}
        self._active_channels = list()
        self.__clock_source = '100MHz'
        self.__downsample = 1
        self.__sampling_time_ns = 10_000
        self.__buffer_size = 1_000_000

    def on_activate(self):
        self._digital_channels = set(str(ch).lower() for ch in self._digital_channels)
        self._active_channels = list(self._digital_channels)

    def on_deactivate(self):
        if self.module_state() == 'locked':
            self.stop_buffered_acquisition()

    @property
    def active_channels(self):
        return self._active_channels

    def set_active_channels(self, channels):
        assert hasattr(channels, '__iter__') and not isinstance(channels, str), \
            f'Given input channels {channels} are not iterable'
        assert self.module_state() != 'locked', \
            'Unable to change active channels while acquisition is running.'
        channels = tuple(str(ch).lower() for ch in channels)
        assert set(channels).issubset(self._digital_channels), \
            f'Invalid input channels {set(channels).difference(self._digital_channels)}'
        with self._thread_lock:
            self._active_channels = list(channels)
        print(f'[TimeHistDummy] active_channels set to {self._active_channels}')

    @property
    def clock_source(self):
        return self.__clock_source

    @clock_source.setter
    def clock_source(self, value):
        assert value in _TICK_NS, f'Requested timebase not available: {value}. Choose from {list(_TICK_NS)}'
        self.__clock_source = value
        print(f'[TimeHistDummy] clock_source set to {value}')

    @property
    def _downsample(self):
        return self.__downsample

    @_downsample.setter
    def _downsample(self, value):
        value = int(value)
        assert value >= 1, 'downsample value must be at least 1'
        self.__downsample = value
        print(f'[TimeHistDummy] downsample set to {value}')

    @property
    def _sampling_time_ns(self):
        return self.__sampling_time_ns

    @_sampling_time_ns.setter
    def _sampling_time_ns(self, value):
        value = int(value)
        assert value > 0, 'sampling_time_ns must be > 0'
        self.__sampling_time_ns = value
        print(f'[TimeHistDummy] sampling_time_ns set to {value}')

    @property
    def _buffer_size(self):
        return self.__buffer_size

    @_buffer_size.setter
    def _buffer_size(self, value):
        value = int(value)
        assert value > 0, 'buffer_size must be > 0'
        self.__buffer_size = value
        print(f'[TimeHistDummy] buffer_size set to {value}')

    def start_buffered_acquisition(self):
        assert self.module_state() == 'idle', \
            'Unable to start data acquisition. Data acquisition already in progress.'
        self.module_state.lock()

        tick_ns = _TICK_NS[self.clock_source]
        bin_width_ns = tick_ns * self._downsample
        n_bins = int(self._sampling_time_ns // bin_width_ns)

        self.data = {}
        for chan in self._active_channels:
            self.data[chan] = (
                np.arange(n_bins + 1) * bin_width_ns,  # edges
                np.zeros(n_bins, dtype=np.uint32),     # counts
            )
        print(f'[TimeHistDummy] acquisition started, channels={self._active_channels}')

    def stop_buffered_acquisition(self):
        if self.module_state() == 'locked':
            self.module_state.unlock()
        print('[TimeHistDummy] acquisition stopped')

    def acquire_sample(self):
        with self._thread_lock:
            if not self._active_channels:
                self.log.warning('acquire_sample called while no channels are active')
                return None
            if self.module_state() != 'locked':
                self.log.error('Unable to read data. Device is not running.')
                return None

            # Simulate pulse arrival times drawn from a Poisson distribution centered on 1/4
            # of the sampling window, then bin them the same way the real hardware would.
            mean_arrival_ns = self._sampling_time_ns / 4
            for chan in self._active_channels:
                edges, counts = self.data[chan]
                n_bins = len(counts)
                bin_width_ns = edges[1] - edges[0] if n_bins > 0 else 1

                n_events = np.random.poisson(50)
                arrival_ns = np.random.poisson(lam=mean_arrival_ns, size=n_events)
                bin_idx = (arrival_ns // bin_width_ns).astype(int)
                bin_idx = bin_idx[(bin_idx >= 0) & (bin_idx < n_bins)]
                counts += np.bincount(bin_idx, minlength=n_bins)[:n_bins].astype(counts.dtype)

            return self.data
