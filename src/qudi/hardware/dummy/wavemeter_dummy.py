# -*- coding: utf-8 -*-

"""
Dummy wavemeter hardware module for simulated wavelength measurements.

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

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from scipy.constants import lambda2nu

from qudi.core.configoption import ConfigOption
from qudi.interface.data_instream_interface import (
    DataInStreamConstraints,
    DataInStreamInterface,
    SampleTiming,
    StreamingMode,
)
from qudi.util.constraints import ScalarConstraint
from qudi.util.mutex import Mutex


class WavemeterDummy(DataInStreamInterface):
    """Simulated HighFinesse-style wavemeter streaming 735-740 nm measurements.

    Example config:

        wavemeter_dummy:
            module.Class: 'dummy.wavemeter_dummy.WavemeterDummy'
            options:
                channels:
                    red_laser:
                        switch_ch: 1
                        unit: 'm'
    """

    _wavemeter_ch_config: Dict[str, Dict[str, object]] = ConfigOption(
        name='channels',
        default={'default_channel': {'switch_ch': 1, 'unit': 'm'}},
        missing='info',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = Mutex()
        self._constraints: Optional[DataInStreamConstraints] = None
        self._active_channels: List[str] = []
        self._channel_units: Dict[str, str] = {}
        self._channel_buffer_size = 1024**2
        self._sample_rate = 100.0
        self._stream_start: Optional[float] = None
        self._generated_samples = 0
        self._sample_buffer: Deque[Tuple[np.ndarray, float]] = deque()

    def on_activate(self) -> None:
        channel_units: Dict[str, str] = {}
        switch_channels = set()
        for name, info in self._wavemeter_ch_config.items():
            switch_ch = info.get('switch_ch')
            if not isinstance(switch_ch, int) or switch_ch <= 0:
                raise ValueError(f'Invalid switch channel for {name}: {switch_ch!r}')
            if switch_ch in switch_channels:
                raise ValueError(f'Duplicate wavemeter switch channel: {switch_ch}')
            switch_channels.add(switch_ch)

            unit = info.get('unit', 'm')
            if unit in ('Hz', 'THz'):
                channel_units[name] = 'Hz'
            elif unit in ('m', 'nm'):
                channel_units[name] = 'm'
            else:
                self.log.warning(f'Invalid unit: {unit}. Valid units are Hz and m. Using m as default.')
                channel_units[name] = 'm'

        if not channel_units:
            raise ValueError('At least one wavemeter channel must be configured.')

        self._channel_units = channel_units
        self._active_channels = list(channel_units)
        self._constraints = DataInStreamConstraints(
            channel_units=channel_units,
            sample_timing=SampleTiming.TIMESTAMP,
            streaming_modes=[StreamingMode.CONTINUOUS],
            data_type=np.float64,
            channel_buffer_size=ScalarConstraint(
                default=1024**2,
                bounds=(128, 1024**3),
                increment=1,
                enforce_int=True,
            ),
            sample_rate=ScalarConstraint(default=10.0, bounds=(0.01, 1e3)),
        )
        self._channel_buffer_size = self._constraints.channel_buffer_size.default
        self._sample_rate = self._constraints.sample_rate.default

    def on_deactivate(self) -> None:
        if self.module_state() == 'locked':
            self.stop_stream()
        with self._lock:
            self._stream_start = None
            self._sample_buffer.clear()

    @property
    def constraints(self) -> DataInStreamConstraints:
        if self._constraints is None:
            raise RuntimeError('Wavemeter dummy is not activated.')
        return self._constraints

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    @property
    def channel_buffer_size(self) -> int:
        return self._channel_buffer_size

    @property
    def streaming_mode(self) -> StreamingMode:
        return StreamingMode.CONTINUOUS

    @property
    def active_channels(self) -> List[str]:
        return self._active_channels.copy()

    @property
    def available_samples(self) -> int:
        with self._lock:
            if self.module_state() != 'locked':
                return 0
            self._generate_samples()
            return len(self._sample_buffer)

    def configure(self,
                  active_channels: Sequence[str],
                  streaming_mode: Union[StreamingMode, int],
                  channel_buffer_size: int,
                  sample_rate: float) -> None:
        with self._lock:
            if self.module_state() == 'locked':
                raise RuntimeError('Unable to configure data stream while it is already running.')

            if active_channels is not None:
                channels = list(active_channels)
                if not channels or len(set(channels)) != len(channels):
                    raise ValueError('Select one or more unique wavemeter channels.')
                unknown = set(channels).difference(self._channel_units)
                if unknown:
                    raise ValueError(f'Unknown wavemeter channels: {sorted(unknown)}')
                self._active_channels = channels

            if streaming_mode is not None:
                mode = StreamingMode(getattr(streaming_mode, 'value', streaming_mode))
                if mode != StreamingMode.CONTINUOUS:
                    self.log.warning('Only continuous streaming is supported, ignoring this setting.')

            if channel_buffer_size is not None:
                self.constraints.channel_buffer_size.check(channel_buffer_size)
                self._channel_buffer_size = channel_buffer_size

            if sample_rate is not None:
                self.constraints.sample_rate.check(sample_rate)
                self._sample_rate = float(sample_rate)

    def start_stream(self) -> None:
        with self._lock:
            if self.module_state() != 'idle':
                self.log.warning('Unable to start input stream. It is already running.')
                return
            self.module_state.lock()
            self._sample_buffer.clear()
            self._generated_samples = 0
            self._stream_start = time.perf_counter()

    def stop_stream(self) -> None:
        with self._lock:
            if self.module_state() == 'locked':
                self.module_state.unlock()
                self._stream_start = None
            else:
                self.log.warning('Unable to stop wavemeter input stream as nothing is running.')

    def read_data_into_buffer(self,
                              data_buffer: np.ndarray,
                              samples_per_channel: int,
                              timestamp_buffer: Optional[np.ndarray] = None) -> None:
        self._validate_buffers(data_buffer, samples_per_channel, timestamp_buffer)
        while True:
            with self._lock:
                if self.module_state() != 'locked':
                    raise RuntimeError('Unable to read data. Stream is not running.')
                self._generate_samples()
                if len(self._sample_buffer) >= samples_per_channel:
                    data, timestamps = self._consume_samples(samples_per_channel)
                    data_buffer[:data.size] = data
                    timestamp_buffer[:samples_per_channel] = timestamps
                    return
            time.sleep(1.0 / self._sample_rate)

    def read_available_data_into_buffer(self,
                                        data_buffer: np.ndarray,
                                        timestamp_buffer: Optional[np.ndarray] = None) -> int:
        with self._lock:
            if self.module_state() != 'locked':
                raise RuntimeError('Unable to read data. Stream is not running.')
            self._generate_samples()
            sample_count = min(
                len(self._sample_buffer),
                data_buffer.size // len(self._active_channels),
            )
            self._validate_buffers(data_buffer, sample_count, timestamp_buffer)
            data, timestamps = self._consume_samples(sample_count)
            data_buffer[:data.size] = data
            timestamp_buffer[:sample_count] = timestamps
            return sample_count

    def read_data(self,
                  samples_per_channel: Optional[int] = None
                  ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        if samples_per_channel is None:
            samples_per_channel = self.available_samples
        data = np.empty(samples_per_channel * len(self.active_channels), dtype=np.float64)
        timestamps = np.empty(samples_per_channel, dtype=np.float64)
        self.read_data_into_buffer(data, samples_per_channel, timestamps)
        return data, timestamps

    def read_single_point(self) -> Tuple[np.ndarray, Optional[np.float64]]:
        data, timestamps = self.read_data(1)
        return data, timestamps[0]

    def read_last_value_1CH(self):
        return self.read_single_point()[0][-1]

    def _generate_samples(self) -> None:
        if self._stream_start is None:
            return

        elapsed = time.perf_counter() - self._stream_start
        target_sample = int(elapsed * self._sample_rate)
        sample_count = target_sample - self._generated_samples
        if sample_count <= 0:
            return
        if len(self._sample_buffer) + sample_count > self._channel_buffer_size:
            raise OverflowError(
                'Streaming buffer overflowed. Increase the buffer size or read data more frequently.'
            )

        wavelengths = np.random.uniform(
            735e-9,
            740e-9,
            (sample_count, len(self._active_channels)),
        )
        samples = np.empty_like(wavelengths)
        for index, channel in enumerate(self._active_channels):
            channel_wavelengths = wavelengths[:, index]
            samples[:, index] = (
                channel_wavelengths
                if self._channel_units[channel] == 'm'
                else lambda2nu(channel_wavelengths)
            )
        timestamps = np.arange(
            self._generated_samples + 1,
            target_sample + 1,
            dtype=np.float64,
        ) / self._sample_rate
        self._sample_buffer.extend(zip(samples, timestamps))
        self._generated_samples = target_sample

    def _consume_samples(self, sample_count: int) -> Tuple[np.ndarray, np.ndarray]:
        samples = [self._sample_buffer.popleft() for _ in range(sample_count)]
        if samples:
            data = np.asarray([sample for sample, _ in samples], dtype=np.float64).ravel()
            timestamps = np.asarray([timestamp for _, timestamp in samples], dtype=np.float64)
        else:
            data = np.empty(0, dtype=np.float64)
            timestamps = np.empty(0, dtype=np.float64)
        return data, timestamps

    def _validate_buffers(self,
                          data_buffer: np.ndarray,
                          samples_per_channel: int,
                          timestamp_buffer: Optional[np.ndarray]) -> None:
        if samples_per_channel < 0 or samples_per_channel > self._channel_buffer_size:
            raise ValueError(
                f'samples_per_channel must be between 0 and {self._channel_buffer_size}.'
            )
        if not isinstance(data_buffer, np.ndarray) or data_buffer.dtype != self.constraints.data_type:
            raise TypeError(f'data_buffer must be a numpy.ndarray with dtype {self.constraints.data_type}.')
        required_data_size = samples_per_channel * len(self._active_channels)
        if data_buffer.size < required_data_size:
            raise ValueError(f'data_buffer must hold at least {required_data_size} values.')
        if not isinstance(timestamp_buffer, np.ndarray) or timestamp_buffer.dtype != np.float64:
            raise TypeError('A float64 timestamp_buffer is required for the wavemeter.')
        if timestamp_buffer.size < samples_per_channel:
            raise ValueError(f'timestamp_buffer must hold at least {samples_per_channel} values.')
