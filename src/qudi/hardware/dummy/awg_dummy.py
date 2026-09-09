import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.pulser_interface import PulserInterface, PulserConstraints


class AWGDummy(PulserInterface):
    """ A dummy hardware module mimicking the Spectrum DN2 AWG (spectrum_DN2.AWG_DN2).

    Allows simple_awg_logic to run without connected hardware. All commands that would
    normally talk to the instrument instead print a message to the console.

    Example Config:

        awg_dummy:
            module.Class: 'dummy.awg_dummy.AWGDummy'
            options:
                default_sample_rate: 1.00e9
                reps: 0
                volts: [0.5, 0.5, 0.5, 0.5]
                ohms: ['low', 'low', 'low', 'low']
                channels: ['a_ch1', 'd_ch1', 'a_ch2', 'd_ch2', 'd_ch3']
    """

    default_sample_rate = ConfigOption('default_sample_rate', 1.0e9, missing='warn')
    reps = ConfigOption('reps', 0, missing='warn')
    voltage = ConfigOption('volts', [0.5, 0.5, 0.5, 0.5], missing='warn')
    resistance = ConfigOption('ohms', ['low', 'low', 'low', 'low'], missing='warn')
    _init_channels = ConfigOption('channels', 'one', missing='warn')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.saved_waveforms = {}
        self.saved_sequences = {}
        self.digital_buffers = {}

        self.analog_channels = {
            'a_ch1': (0, 0),
            'a_ch2': (0, 1),
            'a_ch3': (1, 0),
            'a_ch4': (1, 1),
        }

        self.digital_channels = {
            'd_ch1': (0, 0),
            'd_ch2': (0, 1),
            'd_ch3': (0, 2),
            'd_ch4': (1, 0),
            'd_ch5': (1, 1),
            'd_ch6': (1, 2),
        }

        self.connected = False
        self.running = False

    def on_activate(self):
        self.constraints = self.get_constraints()

        if self.default_sample_rate is not None:
            self.set_sample_rate(self.default_sample_rate)
        else:
            self.log.warning('No parameter "default_sample_rate" found in '
                              'the config! The maximum sample rate is '
                              'used instead.')
            self._sample_rate = self.constraints.sample_rate.max

        self._channel_states = {
            name: False
            for name in (
                list(self.analog_channels.keys()) +
                list(self.digital_channels.keys())
            )
        }

    def turn_on(self):
        print('[AWGDummy] Connecting to dummy AWG...')
        self.connected = True
        self.enable_channel(self._init_channels)
        self.digital_buffers = {}

    def turn_off(self):
        self.digital_buffers = {}
        self.pulser_off()
        if self.connected:
            print('[AWGDummy] Closing connection to dummy AWG')
        self.connected = False

    def on_deactivate(self):
        if self.connected:
            self.turn_off()

    def reset(self):
        print('[AWGDummy] Reset command sent to dummy AWG')

    def get_constraints(self):
        constraints = PulserConstraints()

        constraints.waveform_format = ['wfm']
        constraints.sequence_format = ['seq']

        constraints.sample_rate.min = 1
        constraints.sample_rate.max = 1.25e9
        constraints.sample_rate.step = 1.0e6
        constraints.sample_rate.default = 1.25e8

        constraints.a_ch_amplitude.min = 0.08
        constraints.a_ch_amplitude.max = 2.0
        constraints.a_ch_amplitude.step = 0.001
        constraints.a_ch_amplitude.default = 2.0

        constraints.a_ch_offset.default = 0.0

        constraints.flags = []

        constraints.waveform_length.min = 16
        constraints.waveform_length.max = 32400000
        constraints.waveform_length.step = 1
        constraints.waveform_length.default = 16

        activation_config = dict()

        activation_config['all'] = frozenset({'a_ch1', 'a_ch2', 'a_ch3',
                                               'a_ch4', 'd_ch1', 'd_ch2', 'd_ch3', 'd_ch4', 'd_ch5', 'd_ch6'})
        activation_config['one_d'] = frozenset({'d_ch1'})
        activation_config['one'] = frozenset({'a_ch1', 'd_ch1'})
        activation_config['two'] = frozenset({'a_ch1', 'a_ch2', 'd_ch1'})
        activation_config['three'] = frozenset({'a_ch1', 'a_ch2', 'a_ch3'})

        constraints.activation_config = activation_config

        return constraints

    def enable_channel(self, config_name):
        if isinstance(config_name, str):
            configs = self.constraints.activation_config
            active_names = configs[config_name]
        elif isinstance(config_name, dict):
            active_names = [name for name, state in config_name.items() if state]
        else:
            active_names = config_name

        for name in self._channel_states:
            self._channel_states[name] = (name in active_names)

        print(f'[AWGDummy] Enabled channels: {sorted(active_names)}')

    def disable_channel(self, chnls):
        for name in chnls:
            self._channel_states[name] = False
        print(f'[AWGDummy] Disabled channels: {chnls}')

    def pulser_on(self):
        print(f'[AWGDummy] Applying voltage: {self.voltage}, resistance: {self.resistance}')
        print('[AWGDummy] Starting output (trigger enabled)')
        self.running = True
        return 1, self.get_status()[1]

    def pulser_off(self):
        print('[AWGDummy] Stopping output')
        self.running = False
        return 0, self.get_status()[1]

    def load_waveform(self, load_dict):
        print(f'[AWGDummy] Loading waveform(s): {load_dict}')

    def load_sequence(self, sequence_name):
        print(f'[AWGDummy] Loading sequence: {sequence_name}')

    def get_loaded_assets(self):
        chnl_activation = self.get_active_channels()

        channel_numbers = sorted(int(chnl.split('_ch')[1]) for chnl in chnl_activation if
                                  chnl.startswith('a') and chnl_activation[chnl])

        loaded_assets = dict()
        current_type = 'waveform'
        for chnl_num in channel_numbers:
            loaded_assets[chnl_num] = self.saved_waveforms.get(chnl_num, '')

        return loaded_assets, current_type

    def clear_all(self):
        self.saved_waveforms = {}
        self.saved_sequences = {}
        print('[AWGDummy] Cleared all waveforms and sequences')

    def get_analog_level(self, amplitude=None, offset=None):
        return {}, {}

    def set_analog_level(self, amplitude=None, offset=None):
        print(f'[AWGDummy] Set analog level - amplitude: {amplitude}, offset: {offset}')

    def get_digital_level(self, low=None, high=None):
        return {}, {}

    def set_digital_level(self, low=None, high=None):
        print(f'[AWGDummy] Set digital level - low: {low}, high: {high}')

    def get_active_channels(self, ch=None):
        if ch is None:
            return self._channel_states.copy()

        if isinstance(ch, str):
            return {ch: self._channel_states[ch]}

        return {name: self._channel_states[name] for name in ch}

    def set_active_channels(self, ch=None, state=False):
        temp_states = self._channel_states.copy()

        if isinstance(ch, str):
            temp_states[ch] = state
        else:
            for name in ch:
                temp_states[name] = state

        self.enable_channel(temp_states)

    def write_waveform(self, name, analog_samples, digital_samples, is_first_chunk, is_last_chunk,
                        total_number_of_samples):
        num_samples = 0
        for chnl, data in analog_samples.items():
            num_samples = max(num_samples, len(data))
        for chnl, data in digital_samples.items():
            num_samples = max(num_samples, len(data))

        self.saved_waveforms[name] = {
            'analog_channels': list(analog_samples.keys()),
            'digital_channels': list(digital_samples.keys()),
            'num_samples': num_samples,
        }

        print(f'[AWGDummy] Writing waveform "{name}" '
              f'(analog: {list(analog_samples.keys())}, digital: {list(digital_samples.keys())}, '
              f'samples: {num_samples})')

        return num_samples, [name]

    def write_sequence(self, name, sequence_parameters):
        self.saved_sequences[name] = sequence_parameters
        print(f'[AWGDummy] Writing sequence "{name}"')

    def get_waveform_names(self):
        return list(self.saved_waveforms.keys())

    def get_sequence_names(self):
        return list(self.saved_sequences.keys())

    def delete_waveform(self, waveform_name):
        self.saved_waveforms.pop(waveform_name, None)
        print(f'[AWGDummy] Deleted waveform "{waveform_name}"')

    def delete_sequence(self, sequence_name):
        self.saved_sequences.pop(sequence_name, None)
        print(f'[AWGDummy] Deleted sequence "{sequence_name}"')

    def get_interleave(self):
        return False

    def set_interleave(self, state=False):
        print(f'[AWGDummy] Set interleave: {state}')

    def get_status(self):
        status_dict = {
            0: 'Device has stopped, but can receive commands.',
            1: 'Device is active and running.',
            -1: 'Device communication error.'
        }
        return (1 if self.running else 0), status_dict

    def get_sample_rate(self) -> float:
        return self._sample_rate

    def set_sample_rate(self, value: float) -> None:
        self._sample_rate = value
        print(f'[AWGDummy] Set sample rate: {value}')
