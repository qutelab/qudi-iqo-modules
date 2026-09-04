import time
import os
import re
import numpy as np

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.interface.pulser_interface import PulserInterface, PulserConstraints, SequenceOption

import spcm
from spcm import units

class AWG_DN2(PulserInterface):
    """ A hardware module for Spectrum DN2-66X abitrary wave generator

        Example Config:
        
        spectrum_awg:
            module.Class: 'awg.spectrum_DN2.AWG_DN2'
            options:
                awg_ip_address: ''
                timeout: 0
                default_sample_rate: 1.00e9
                reps: 0
                volts: [0.5, 0.5, 0.5, 0.5]
                ohms: ['low', 'low', 'low', 'low']
                channels: ['a_ch1', 'd_ch1', 'a_ch2', 'd_ch2', 'd_ch3']

        """

    ip_address = ConfigOption('awg_ip_address', missing='error')
    _timeout = ConfigOption('timeout', 0, missing='warn')
    default_sample_rate = ConfigOption('default_sample_rate', missing='warn')
    reps = ConfigOption("reps", 0, missing='warn')
    voltage = ConfigOption("volts", 1, missing='warn')
    resistance = ConfigOption("ohms", 'low', missing='warn')
    _init_channels = ConfigOption("channels", "", missing='warn')
    

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.saved_waveforms = {}
        self.saved_sequences = {}
        self.clocks = None
        self.started = None

        self.analog_channels = {
            "a_ch1": (0, 0),  # card 0, channel 0
            "a_ch2": (0, 1),
            "a_ch3": (1, 0),
            "a_ch4": (1, 1),
        }

        self.digital_channels = {
            'd_ch1': (0, 0),  # card 0, xio0
            'd_ch2': (0, 1),
            'd_ch3': (0, 2),
            'd_ch4': (1, 0),
            'd_ch5': (1,1),
            'd_ch6': (1,2),
        }

        self.connected = False
        self.running = False

    def on_activate(self):
       
        self.constraints = self.get_constraints()

        if not self.default_sample_rate == None:
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
        # self.initialize_outputs()     
                
        self.card_channels = {}
        
        return

    def turn_on(self):
        self.awg = None
        try:  #Manual connection attempt first, fastest.
            # TODO: config entry of number of cards (here 2)
            card_identifiers = [f'TCPIP::{self.ip_address}::inst0::INSTR',f'TCPIP::{self.ip_address}::inst1::INSTR']
            self.awg = spcm.Netbox(card_identifiers=card_identifiers, find_sync=True)
            if self.awg is None:
                raise
        except:
            devices = spcm.Netbox.discover()
            print(devices)
            for device in devices.keys():
                self.log.warning(f'Could not find device at config IP, discovered device: {device}')
                self.awg = spcm.Netbox(card_identifiers=devices[device], find_sync=True)
        
        if self.awg is None:
            self.log.error('Netbox not connected')
        else:
            self.connected = True
                    
        #if not self.connected:
        #    return

        for card_idx, card in enumerate(self.awg.cards):
            self.card_channels[card_idx] = spcm.Channels(card=card)
            self.card_channels[card_idx].enable(False)
            self.init_card(card_idx)

        if not self.started:
            self.started = True
            self.enable_channel(self._init_channels)

        self.digital_buffers = {}

    def turn_off(self):
        self.digital_buffers = {}
        self.pulser_off()
        if self.connected:
            try:
                self.awg.close()
                self.log.info('Closed connection to AWG')
            except:
                self.log.info('Closing AWG connection failed.')
        self.connected = False

    def on_deactivate(self):
        if self.connected:
            self.turn_off()
        return

    def reset(self):
        if self.connected:
            self.netbox.reset()
            self.log.debug('Netbox AWG has been reset')

    def get_constraints(self):
        constraints = PulserConstraints()

        # The file formats are hardware specific.
        constraints.waveform_format = ['wfm']
        constraints.sequence_format = ['seq']

        constraints.sample_rate.min = 10.0e6
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
                                              'a_ch4', 'd_ch1', 'd_ch2', 'd_ch3', 'd_ch4', 'd_ch5', 'c_ch6'})
        activation_config['one_d'] = frozenset({'d_ch1'})
        activation_config['one'] = frozenset({'a_ch1', 'd_ch1'})
        activation_config['two'] = frozenset({'a_ch1', 'a_ch2', 'd_ch1'})
        activation_config['three'] = frozenset({'a_ch1', 'a_ch2', 'a_ch3'})

        # # AWG5002C has possibility for sequence output
        # constraints.sequence_option = SequenceOption.OPTIONAL
        constraints.activation_config = activation_config

        return constraints

    def enable_channel(self, config_name):

        if isinstance(config_name, str):
            configs = self.constraints.activation_config
            active_names = configs[config_name]
        elif isinstance(config_name, dict):
            active_names = []
            for name in config_name.keys():
                if config_name[name] == True:
                    active_names.append(name)
        else:
            active_names = config_name
        
        # disable everything first
        for channels in self.card_channels.values():
            for ch in channels:
                ch.enable(False)

        for name in self._channel_states:
            self._channel_states[name] = (name in active_names) #False
    
        # enable requested channels
        for channel_name in active_names:
            if 'a_' in channel_name:
                card_idx, phys_ch = self.analog_channels[channel_name]
        
                self.card_channels[card_idx][phys_ch].enable(True)
            if 'd_' in channel_name:
                card_idx, phys_ch = self.digital_channels[channel_name]

                self.card_channels[card_idx][0].enable(True)
    
    def disable_channel(self, chnls):

        configs = self.constraints.activation_config
        active_names = configs[config_name]
    
        # disable requested channels
        for analog_name in active_names:
            if 'a_' in analog_name:
                card_idx, phys_ch = self.analog_channels[analog_name]
        
                self.card_channels[card_idx][phys_ch].enable(False)

    def init_card(self, index):
        card = self.awg.cards[index]
        card.card_mode(spcm.SPC_REP_STD_CONTINUOUS)

        if self.reps != 0:
            # card.card_mode(spcm.SPC_REP_STD_SINGLE)
            card.loops(self.reps)
        else:
            # card.card_mode(spcm.SPC_REP_STD_CONTINUOUS)
            card.loops(0)
    
        clock = spcm.Clock(card)
        clock.sample_rate(self._sample_rate * units.Hz)

    def pulser_on(self):
        activation_dict = self.get_active_channels()
        active_channels = [chnl for chnl in activation_dict if activation_dict[chnl]]

        for chnls in active_channels:
            if 'a_' in chnls:
                card_idx, phys_idx = self.analog_channels[chnls]

                if isinstance(self.resistance, str):
                    if self.resistance == 'low':
                        self.card_channels[card_idx][phys_idx].output_load(50 * units.ohm)
                    elif self.resistance == 'high':
                        self.card_channels[card_idx][phys_idx].output_load(units.highZ)
                else:
                    if self.resistance[card_idx * 2 + phys_idx] == 'low':
                        self.card_channels[card_idx][phys_idx].output_load(50 * units.ohm)
                    elif self.resistance[card_idx * 2 + phys_idx] == 'high':
                        self.card_channels[card_idx][phys_idx].output_load(units.highZ)

                if isinstance(self.voltage, int):
                    self.card_channels[card_idx][phys_idx].amp(self.voltage * units.V)
                else:
                    self.card_channels[card_idx][phys_idx].amp(self.voltage[card_idx * 2 + phys_idx] * units.V)

                card = self.awg.cards[card_idx]
                card.timeout(self._timeout * units.s)
        self.running = True
        self.awg.start(spcm.M2CMD_CARD_ENABLETRIGGER)
        return self.awg.cards[0].status()

    def pulser_off(self):
        self.awg.stop()
        self.running = False
        return self.awg.cards[0].status()

    def load_waveform(self, load_dict):

         # for i, card in enumerate(self.awg.cards):
         #     card_sequence = spcm.Sequence(card)

         #     for chn in load_dict.keys():
         #         if (chn < 2 * (i + 1)) and (chn >= 2 * i):
         #             waveform_length = len(load_dict[keys])

         #             segment = card_sequence.add_segemnt(waveform_length)
        pass

    def load_sequence(self, sequence_name):    
        pass

    def get_loaded_assets(self):
        """
        Retrieve the currently loaded asset names for each active channel of the device.
        The returned dictionary will have the channel numbers as keys.
        In case of loaded waveforms the dictionary values will be the waveform names.
        In case of a loaded sequence the values will be the sequence name appended by a suffix
        representing the track loaded to the respective channel (i.e. '<sequence_name>_1').

        @return (dict, str): Dictionary with keys being the channel number and values being the
                             respective asset loaded into the channel,
                             string describing the asset type ('waveform' or 'sequence')
        """
        # Get all active channels
        chnl_activation = self.get_active_channels()

        channel_numbers = sorted(int(chnl.split('_ch')[1]) for chnl in chnl_activation if
                                 chnl.startswith('a') and chnl_activation[chnl])
        # Get assets per channel
        loaded_assets = dict()
        current_type = None

        run_mode = self.awg.cards[0].card_mode()
        if run_mode == spcm.SPC_REP_STD_CONTINUOUS:
            current_type = 'waveform'
            for chnl_num in channel_numbers:
                loaded_assets[chnl_num] = self.saved_waveforms.get(chnl_num, "")

        elif run_mode == spcm.SPC_REP_STD_SEQUENCE:
            current_type = 'sequence'
            for chnl_num in channel_numbers:
                if len(self.saved_sequences) > 0:
                    loaded_assets[chnl_num] = self.saved_sequences[0]

        return loaded_assets, current_type

    def clear_all(self):
        pass

    def get_analog_level(self, amplitude=None, offset=None):
        return {}, {}

    def set_analog_level(self, amplitude=None, offset=None):
        pass

    def get_digital_level(self, low=None, high=None):
        return {}, {}

    def set_digital_level(self, low=None, high=None):
        pass

    def get_active_channels(self, ch=None):
    
        if ch is None:
            return self._channel_states.copy()
    
        if isinstance(ch, str):
            return {ch: self._channel_states[ch]}
    
        return {
            name: self._channel_states[name]
            for name in ch
        }


    def set_active_channels(self, ch=None, state=False):
        # self.digital_buffers = {}
        temp_states = self._channel_states.copy()
        
        if isinstance(ch, str):
            temp_states[ch] = state
        else:
            for name in ch:
                temp_states[name] = state

        self.enable_channel(temp_states)

    def write_waveform(self, name, analog_samples, digital_samples, is_first_chunk, is_last_chunk,
                       total_number_of_samples):

        activation_dict = self.get_active_channels()
        active_channels = [chnl for chnl in activation_dict if activation_dict[chnl]]
        
        memory_allocated = [False, False]

        synchronous_io = [None, None]
        buffer = [None, None]
        data_transfer = [None, None]

        for chnl in active_channels:
            if 'a_' in chnl:
                if chnl in analog_samples.keys():
                    card_idx, phys_ch = self.analog_channels[chnl]
        
                    chnl_signal = analog_samples[chnl]
                    num_samples = len(chnl_signal)
        
                    if num_samples == 0:
                        self.log.debug('No analog samples passed to write_waveform.')
                else:
                    continue

            if 'd_' in chnl:
                
                if chnl in digital_samples.keys():
                    card_idx, phys_ch = self.digital_channels[chnl]
                    dig_signal = digital_samples[chnl]
                    num_samples = len(dig_signal)
    
                    if num_samples == 0:
                        self.log.debug('No digital samples passed to write_waveform.')
                else:
                    continue

            if memory_allocated[card_idx] == False:
                self.init_card(card_idx)
                card = self.awg.cards[card_idx]

                data_transfer[card_idx] = spcm.DataTransfer(card)
                
                data_transfer[card_idx].memory_size(num_samples) # size of memory on the card
                data_transfer[card_idx].allocate_buffer(num_samples) # size of buffer in pc RAM
                memory_allocated[card_idx] = True
                synchronous_io[card_idx] = spcm.SynchronousDigitalIOs(data_transfer[card_idx], self.card_channels[card_idx])
                
                num_dig_channels = 6
                buffer[card_idx] = synchronous_io[card_idx].allocate_buffer(num_buffers=num_dig_channels)  

            if 'a_' in chnl:
                if chnl in analog_samples.keys():
                    if data_transfer[card_idx].bytes_per_sample != 2: raise spcm.SpcmException(text="Non 16-bit DA not supported")
            
                    # self.data_transfer.buffer[card_idx * 2 + phys_ch, :, 0] = chnl_signal    
                    data_transfer[card_idx].buffer[self.card_channels[card_idx][phys_ch], :] = chnl_signal

            if 'd_' in chnl:
                if chnl in digital_samples.keys():
                    if not chnl in self.digital_buffers.keys():
                        self.digital_buffers[chnl] = len(self.digital_buffers.keys())
                    synchronous_io[card_idx].setup(buffer_index=self.digital_buffers[chnl], channel=self.card_channels[card_idx][0], xios=[phys_ch])
                    buffer[card_idx][self.digital_buffers[chnl], :] = dig_signal

        for idx, used_card in enumerate(memory_allocated):
            if used_card == True:
                synchronous_io[idx].process()
                data_transfer[idx].start_buffer_transfer(spcm.M2CMD_DATA_STARTDMA, spcm.M2CMD_DATA_WAITDMA)

        return num_samples, [name]


    def write_sequence(self, name, sequence_parameters):
        pass

    def get_waveform_names(self):
        return list(self.saved_waveforms.keys())

    def get_sequence_names(self):
        return list(self.saved_sequences.keys())

    def delete_waveform(self, waveform_name):
        pass

    def delete_sequence(self, sequence_name):
        pass

    def get_interleave(self):
        return False

    def set_interleave(self, state=False):
        pass
    
    def get_status(self):

        status_dict = {
            0: 'Device has stopped, but can receive commands.',
            1: 'Device is active and running.',
            -1: 'Device communication error.'
        }
    
        return 0, status_dict

    def _is_output_on(self):
        pass

    def get_sample_rate(self) -> float:
        return self._sample_rate
        
    def set_sample_rate(self, value: float) -> None:
        self._sample_rate = value