import numpy as np

from qtpy import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
import time
import copy

class SimpleAWGLogic(LogicBase):
    """Logic module for controlling spectrum AWG hardware spectrum_DN2
    
        Provides:
        - Pulse train creation logic
        - Control over AWG states
        - Creating and uploading pulse trains to AWG
    
        example config for copy-paste:

        simple_awg_logic:
            module.Class: 'simple_awg_logic.SimpleAWGLogic'
            connect:
                awg: 'spectrum_awg'
    """

    awg = Connector(interface='PulserInterface')
    # pulse_gen = Connector(interface='MicrowaveInterface')

    sigWaveformUpdated = QtCore.Signal(dict)
    sigStatusUpdated = QtCore.Signal(str)
    sigAwgStateReady = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.waveform = {}
        self._awg_running = False
        self.length_mode = 'padding'
        self.i_channel = None
        self.q_channel = None
        self.awg_ready = False
        self.sigAwgStateReady.emit(self.awg_ready)

    def on_activate(self):
        self._awg = self.awg()
        # self.microwave = self.pulse_gen()
        # self.setup_microwave()

    def on_deactivate(self):
        self._awg.on_deactivate()
        # self.microwave.on_deactivate()
        
    # def get_microwave_power(self):
    #     """ Get the current microwave power in dBm """
    #     return self.microwave.cw_power()

    # def set_microwave_power(self, power):
    #     """ Set the current microwave power in dBm """
    #     self.microwave._write(f'AMPR {power:f}')

    # def get_microwave_frequency(self):
    #     """ Get the current microwave frequency in Hz """
    #     return self.microwave._cw_frequency

    # def set_microwave_frequency(self, freq):
    #     """ Set the current microwave frequency in Hz """
    #     self.microwave._write(f'FREQ {freq:f}')

    # -------------------------------------------------
    # Load waveform from CSV
    # -------------------------------------------------

    def load_waveform_file(self, filepath, channel_key):
        """ Load the chosen waveform into the channel. filepath can be a actual file or a numpy array """
        try:
            self.log.debug("Loading waveform")

            # Swap behavior depending on variable type of filepath
            if isinstance(filepath, str):
                temp_data = np.loadtxt(filepath, delimiter=',')
            else:
                temp_data = filepath

            data = self._process_channel_data(temp_data, channel_key)

            self.waveform[channel_key] = data
            graph_waveform = {channel_key: data[:min(1000000, len(data))]} # for preformance reasons limit how much is graphed
            self.sigWaveformUpdated.emit(graph_waveform)

            if isinstance(filepath, str):
                self.sigStatusUpdated.emit(
                    f'Loaded waveform: {filepath}'
                )
            else:
                self.sigStatusUpdated.emit(
                    f'Loaded created waveform'
                )

        except Exception as err:

            self.sigStatusUpdated.emit(
                f'Failed to load waveform: {err}'
            )

    def _process_channel_data(self, temp_data, channel_key):
        """ Scales/casts/pads raw samples for a single channel without any GUI signal emission """
        data = temp_data

        # Differentiate behavior between analog and digital
        if 'a_' in channel_key:
            if temp_data.ndim > 1:
                temp_data = temp_data[:, 0]

            if np.max(temp_data) <= 1 and np.min(temp_data) >= -1:
                temp_data = temp_data * 32767 # Scales to max amplitude
                temp_data = np.asarray(temp_data, dtype=np.int16)
            else:
                temp_data = np.asarray(temp_data, dtype=np.int16)

            temp_data = np.clip(temp_data, -32767, 32767)
            # Pad to multiple of 32 samples
            remainder = len(temp_data) % 32

            if remainder != 0:
                pad_len = 32 - remainder

                data = np.pad(
                    temp_data,
                    (0, pad_len),
                    mode='constant',
                    constant_values=0
                )
            else:
                data = temp_data

        if 'd_' in channel_key:
            if temp_data.ndim > 1:
                temp_data = temp_data[:, 0]
            temp_data = np.where(temp_data > 0.5, 1, 0) # Set all data to 1 or 0

            # Pad to multiple of 32 samples
            remainder = len(temp_data) % 32

            if remainder != 0:
                pad_len = 32 - remainder

                data = np.pad(
                    temp_data,
                    (0, pad_len),
                    mode='constant',
                    constant_values=0
                )
            else:
                data = temp_data

        return data

    def load_waveform_set(self, waveforms):
        """ Replaces the entire waveform dictionary with the given {channel: samples} data.

        Any channel not present in `waveforms` is dropped, so channels that no longer have a
        step in the newly compiled sequence/block don't keep stale data from a previous load.

        Processes all channels first and emits a single combined update instead of one signal
        (and GUI plot refresh) per channel, which otherwise dominates the runtime for sequences
        with many channels.
        """
        self.waveform = {}
        graph_waveform = {}
        for channel, data in waveforms.items():
            processed = self._process_channel_data(data, channel)
            self.waveform[channel] = processed
            graph_waveform[channel] = processed[:min(1000000, len(processed))]

        self.sigWaveformUpdated.emit(graph_waveform)
        self.sigStatusUpdated.emit('Loaded created waveform')

    # -------------------------------------------------
    # Upload waveform
    # -------------------------------------------------

    def upload_waveform(self):
        """ Uploads the loaded waveform into AWG memory.

        Any active channel that no longer has a created waveform is uploaded with zeros so
        that stale data from a previous upload does not keep running on the hardware.
        """
        if not self.waveform:
            self.sigStatusUpdated.emit(
                'No waveform loaded'
            )
            return
            
        if self._awg.connected:
            self.awg_ready = True
            self.sigAwgStateReady.emit(self.awg_ready)

        try:
            self.log.debug("Writing waveform to memory")
            analog_samples = {}
            digital_samples = {}
            
            max_length = max(len(wf) for wf in self.waveform.values())

            active_channels = self._awg.get_active_channels()
            enabled_channels = {ch for ch, enabled in active_channels.items() if enabled}
            channels_to_write = set(self.waveform.keys()) | enabled_channels

            for channel in channels_to_write:
                if channel in self.waveform:
                    channel_length = len(self.waveform[channel])

                    amplitude_factor = 1
                    if self.length_mode == 'padding':
                        self.waveform[channel] = np.pad(
                            self.waveform[channel],
                            (0, max_length - channel_length),
                            mode='constant',
                            constant_values=0
                        )
                    channel_data = amplitude_factor * self.waveform[channel]
                else:
                    # channel is active but has no created waveform - clear it instead of leaving stale data
                    channel_data = np.zeros(max_length)

                if 'd_' in channel:
                    digital_samples[channel] = channel_data
                if 'a_' in channel:
                    analog_samples[channel] = np.asarray(channel_data, dtype=np.int16)

            self._awg.write_waveform(
                name='custom_waveform',
                analog_samples=analog_samples,
                digital_samples=digital_samples,
                is_first_chunk=True,
                is_last_chunk=True,
                total_number_of_samples=max_length
            )

            self.sigStatusUpdated.emit(
                'Waveform uploaded'
            )
            
        except Exception as err:

            self.sigStatusUpdated.emit(
                f'Upload failed: {err}'
            )

    def clear_waveforms(self):
        self.waveform = {}
        self.sigWaveformUpdated.emit(self.waveform)
        self.awg_ready = False
        self.sigAwgStateReady.emit(self.awg_ready)

    def start_awg(self):
        if not self._awg.connected:
            self._awg.turn_on()
            self._awg_running = self._awg.connected
    
    def stop_awg(self):
        if self._awg.connected:
            self._awg.turn_off()
            self._awg_running = self._awg.connected
            self.awg_ready = self._awg.connected
            self.sigAwgStateReady.emit(self.awg_ready)
        
    def is_awg_running(self):
        return self._awg_running

    def get_active_channels(self):
        try:
            active_channels = self._awg.get_active_channels()

            return [
                channel
                for channel, enabled in active_channels.items()
                if enabled
            ]

        except Exception as err:
    
            self.log.error(
                f'Failed to get active channels: {err}'
            )

        return []

    # -------------------------------------------------
    # Playback control
    # -------------------------------------------------

    def start_output(self):
        try:
            if self.awg_ready:
                self._awg.pulser_on()
                self.sigStatusUpdated.emit(
                    'Output started'
                )
        except Exception as err:
            #TODO THIS ERROR NEEDS TO BE HANDLED IN THE HW, NO SPCM DEPENDENCY
            #if isinstance(err, spcm.SpcmTimeout):
            #    self._awg.pulser_off()
            #else:
            self.sigStatusUpdated.emit(
                f'Start failed: {err}'
            )

    def stop_output(self):
        try:
            self._awg.pulser_off()

            self.sigStatusUpdated.emit(
                'Output stopped'
            )
        except Exception as err:
            self.sigStatusUpdated.emit(
                f'Stop failed: {err}'
            )

    # def setup_microwave(self, freq=2.7e9, power=-120):
    #     """ Setup microwave modulation, power, and frequency """
    #     self.microwave._write(f"ENBL 0")
    #     if power >= -110:
    #         self.microwave_power(power)

    #     self.microwave._write(f"FREQ {freq:f}")
    #     self.microwave._write(f"TYPE 7")
    #     self.microwave._write(f"QFNC 5")
    #     self.microwave._write(f"MODL 1")

    # def scan_frequencies(self, power, start_freq, end_freq, steps):
    #     """ Loops through set frequency range at given microwave power. Current loaded AWG sequence is run each time """
    #     if not self.awg_ready:
    #         return
            
    #     freqs = np.linspace(start_freq, end_freq, steps)
    #     self.set_microwave_power(power)

    #     self.microwave = self.pulse_gen()
    #     self.microwave._write(f"TYPE 7")
    #     self.microwave._write(f"QFNC 5")
    #     self.microwave._write(f"MODL 1")
    #     self.microwave._write(f"ENBR 1")
        
    #     for freq in freqs:
    #         self.set_microwave_frequency(freq)
    #         self.start_output()

    #     self.microwave._write(f"ENBR 0")  

    def get_channel_state(self, channel):
        """ Query the awg to get the available channels """
        return self._awg.get_active_channels(channel)[channel]

    def set_channel_state(self, channel, state):
        """ Communicate with awg to change channel states """
        self._awg.set_active_channels(channel, state)

    def set_iq_channels(self, i_channel, q_channel):
        """ This is used to track which channels are being used for I and Q"""
        self.i_channel = i_channel
        self.q_channel = q_channel

    def get_sample_rate(self):
        """ Query the awg for its current sample rate """
        return self._awg.get_sample_rate()

    def set_sample_rate(self, sample_rate):
        """ Set the awg hardware sample rate """
        self._awg.set_sample_rate(sample_rate)

    def set_pulse_time(self, pulse_time):
        if not self.awg_ready:
            return
        self.stop_output()
        #print("Pulse Time: ", pulse_time)
        pulse_blocks = copy.deepcopy(self.pulse_blocks)
        sequence = copy.deepcopy(self.sequence)
        
        if self._awg.connected:
            for step in sequence:
                current_block = step['block']
                current_params = pulse_blocks[current_block]

                if current_params[0] == "Variable Pulses":
                    # used_pulse_blocks.append(current_block)
                    if current_params[1] == self.selected_param:
                        #current_params[0] = "Pulses"
                        current_params[1] = pulse_time #* 1e-9
                    if current_params[2] == self.selected_param:
                        #current_params[0] = "Pulses"
                        current_params[2] = pulse_time #* 1e-9

                    pulse_blocks[current_block] = current_params
            compiler = PulseCompiler(sequence, pulse_blocks, self, steps_per_iter=10000)
            waveforms = compiler.compile()
            
            self.load_waveform_set(waveforms)
            self.upload_waveform()
            
            self.start_output()
            
    def update_pulses_and_sequences(self, sequence, pulse_blocks):
        if not sequence is None:
            self.sequence = sequence
            params = self.get_variable_params(sequence)
            if len(params) > 0:
                self.selected_param = params[0]
            else:
                self.selected_param = None
        self.pulse_blocks = pulse_blocks
        
    def get_variable_params(self, sequence):
        avail_params = []
        for step in sequence:
            current_block = step['block']
            if isinstance(current_block, str):
                current_params = self.pulse_blocks[current_block]
            else:
                current_params = current_block
            if current_params[0] == "Variable Pulses":
                if current_params[1] != "":
                    avail_params.append(current_params[1])
                else:
                    current_params[1] = 0
                    
                if current_params[2] != "":
                    avail_params.append(current_params[2])
                else:
                    current_params[2] = 0

        return avail_params
        
    def create_pulse_vars(self, pulse_type, variables):
        if pulse_type == "pulse":
            return ["Pulses", variables["length"], 0, variables["iterate"], 0, variables["amp"]]
        elif pulse_type == "delay":
            return ["Pulses", 0, variables["length"], 0, variables["iterate"], variables["amp"]]
        elif pulse_type == "varPulse":
            return ["Variable Pulses", variables["length"], 0, 0, 0, variables["amp"]]
        elif pulse_type == "varDelay":
            return ["Variable Pulses", 0, variables["length"], 0, 0, variables["amp"]]
        else:
            return ["Other", variables["pulse shape"]]

    def read_pulse_line(self, line, variables):
        line_content = line.split(" ")
        value = line_content[0]
        if "$" in value:
            value = variables[value[1:]]
        elif not value[:-1].isdecimal():
            pass
        elif value[-1] == 'm':
            value = float(value[:-1]) * 1e-3
        elif value[-1] == 'u':
            value = float(value[:-1]) * 1e-6
        elif value[-1] == 'n':
            value = float(value[:-1]) * 1e-9

        length = value
        
        channels = []
        pointer = 1
        while "_" in line_content[pointer] or "IQ" in line_content[pointer]:
            channels.append(line_content[pointer])
            pointer += 1
            
        pulse = line_content[pointer]
        pulse = pulse[:-1]
        pulse = pulse.split("(")
        
        pulse_type = pulse[0]
        if len(pulse) > 1:
            pulse_variables = pulse[1][:].split(",")
            amplitude = variables[pulse_variables[0][1:]]
        else:
            amplitude = 1
        pointer += 1
        recieve = int(line_content[pointer])
        
        pointer += 1
        send = int(line_content[pointer])
        
        if len(line_content) > pointer + 1:
            phase = float(line_content[pointer + 1])
        else:
            phase = 0
            
        return channels, pulse_type, length, amplitude, recieve, send, phase

    def read_sequence_file(self, file_path):
        try:
            lines = []
            with open(file_path, "r") as file:
                for line in file:
                    target = line.strip()
                    if len(target) > 0:
                        lines.append(target)
                    
            variables = {}
            for line in lines: #Extract variables from file
                if line[0] == "$" and not " " in line:
                    var = line[1:].split("=")
                    value = var[1]
                    if value[-1] == 'm':
                        value = float(value[:-1]) * 1e-3
                    elif value[-1] == 'u':
                        value = float(value[:-1]) * 1e-6
                    elif value[-1] == 'n':
                        value = float(value[:-1]) * 1e-9
                    else:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    variables[var[0]] = value

            sequence = []
            num_iters = 1
            for line in lines:
                if "%" in line:
                    continue

                if "iterate" in line:
                    num_iters = int(line.split(" ")[1][:-1])
                    continue
                elif "inline" in line:
                    continue
                elif "evaluate" in line:
                    continue
                elif ".pf" in line:
                    pass
                elif "$" in line:
                    if not " " in line:
                        continue
                    channels, pulse_type, pulse_length, amplitude, recieve, send, phase = self.read_pulse_line(line, variables)
                    
                    pulse_vars = {
                        "length": pulse_length,
                        "amp": amplitude,
                        "iterate": 0
                    }
                    
                    sequence.append({
                        "block": self.create_pulse_vars(pulse_type, pulse_vars),
                        "channels": channels,
                        "repetitions": num_iters,
                        "Send Trig": send,
                        "Receive Trig": recieve,
                        "IQ Phase": phase
                    })
                    
                    if num_iters > 1:
                        num_iters = 1
                    continue
                elif " " in line:
                    channels, pulse_type, pulse_length, amplitude, recieve, send, phase = self.read_pulse_line(line, variables)
                    
                    pulse_vars = {
                        "length": pulse_length,
                        "amp": amplitude,
                        "iterate": 0
                    }
                    
                    
                    sequence.append({
                        "block": self.create_pulse_vars(pulse_type, pulse_vars),
                        "channels": channels,
                        "repetitions": num_iters,
                        "Send Trig": send,
                        "Receive Trig": recieve,
                        "IQ Phase": phase
                    })
                    
                    if num_iters > 1:
                        num_iters = 1
                    continue
            return sequence
        except Exception as e:
            print(f"Error reading sequence {e}")
            return {}

class PulseCompiler:
    """ Simple class to convert steps into actual numpy data"""
    def __init__(self, sequence_data, pulse_data, logic, steps_per_iter=1, sample_rate=1e9):
        #Set values
        self.fs = sample_rate # Typically 1GHz
        self.pulse_blocks = pulse_data 
        self.all_steps = sequence_data # Steps used in this sequence
        self._logic = logic # Needed because this is mainly used from GUI
        self.steps_per_iter = steps_per_iter #Denotes how many times a block needs to be run before being iterated

        if not self.all_steps is None:
            # Extract unique channels
            self.all_channels = sorted(list(set(
                ch for step in self.all_steps for ch in step.get('channels', [])
            )))
            for i in range(len(self.all_channels)):
                if self.all_channels[i] == 'IQ': # Remove IQ and replace with actual channels
                    self.all_channels.pop(i)
                    if not self._logic.i_channel in self.all_channels:
                        self.all_channels.append(self._logic.i_channel)
                    if not self._logic.q_channel in self.all_channels:
                        self.all_channels.append(self._logic.q_channel)
            
            # Group steps by 'Wait for Flag'
            self.steps_by_wait_flag = {}
            for step in self.all_steps:
                wait_flag = step.get('Receive Trig', 0)
                if wait_flag not in self.steps_by_wait_flag:
                    self.steps_by_wait_flag[wait_flag] = []
                self.steps_by_wait_flag[wait_flag].append(step)
    
            # Tracks how many times a step has been run
            self._step_run_tracker = {}
            self.compiled_pulses = {}
            # Flags currently being expanded on the call stack - guards against Send/Receive Trig cycles
            self._active_flags = set()

    def compile(self):
        """Starts compilation and resets local run trackers."""
        # Reset tracker for this compilation run
        self._step_run_tracker = {id(step): 0 for step in self.all_steps}
        self._active_flags = set()
        # Segments are collected in one shared structure so that steps sharing a Receive Trig
        # (i.e. running concurrently) write to the same starting offset instead of queuing up
        self._channel_segments = {ch: [] for ch in self.all_channels if ch != "IQ"}
        self._max_len = 0

        self._compile_flag(0, 0)

        # Final single-allocation pass per channel: zero-fill then write only the real segments
        flag_waveforms = {}
        for ch, segments in self._channel_segments.items():
            master_arr = np.zeros(self._max_len, dtype=np.float64)
            for seg_offset, seg in segments:
                master_arr[seg_offset:seg_offset + seg.size] = seg
            flag_waveforms[ch] = master_arr

        print("Compiling Sequence Finished")
        return flag_waveforms

    def _compile_flag(self, flag_id, start_offset):
        if flag_id not in self.steps_by_wait_flag:
            return

        if flag_id in self._active_flags:
            # A step's Send Trig loops back to a flag already being expanded on this call stack -
            # break the cycle instead of recursing forever.
            self._logic.log.warning(
                f'Sequence has a Send/Receive Trig cycle involving flag {flag_id}; skipping repeated expansion.'
            )
            return

        self._active_flags.add(flag_id)
        try:
            self._expand_flag(flag_id, start_offset)
        finally:
            self._active_flags.discard(flag_id)

    def _expand_flag(self, flag_id, start_offset):
        # Every step waiting on this flag starts at the same offset (they run concurrently);
        # each step's own Send Trig chain is anchored independently to that step's own end offset
        for step in self.steps_by_wait_flag[flag_id]:
            step_id = id(step)
            repetitions = step.get('repetitions', 1)
            chnl = list(step.get('channels', []))
            used_iq = "IQ" in chnl
            offset = start_offset

            if isinstance(step['block'], str):
                pulse_type = self.pulse_blocks[step['block']]
            else:
                pulse_type = step['block']

            # A Pulses/Variable Pulses block with no increment is identical on every repetition,
            # so the whole run can be tiled in one numpy call instead of looping in Python per rep
            is_static = pulse_type[0] in ("Pulses", "Variable Pulses") and pulse_type[3] == 0 and pulse_type[4] == 0

            if is_static:
                current_run_count = self._step_run_tracker[step_id]

                if used_iq:
                    if len(chnl) > 1:
                        pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                        standard_pulse = self.compile_pulse(pulse_type, current_run_count)
                    else:
                        pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                else:
                    pulse_shape = self._get_cached_pulse(step['block'], pulse_type, current_run_count)

                self._step_run_tracker[step_id] += repetitions

                if used_iq:
                    i_pulse, q_pulse = pulse_shape[0], pulse_shape[1]
                    pulse_len = len(i_pulse)
                    if repetitions > 1:
                        i_pulse = np.tile(i_pulse, repetitions)
                        q_pulse = np.tile(q_pulse, repetitions)
                    if self._logic.i_channel in self._channel_segments:
                        self._channel_segments[self._logic.i_channel].append((offset, i_pulse))
                    if self._logic.q_channel in self._channel_segments:
                        self._channel_segments[self._logic.q_channel].append((offset, q_pulse))
                    if len(chnl) > 1:
                        standard_tiled = np.tile(standard_pulse, repetitions) if repetitions > 1 else standard_pulse
                        for ch in chnl:
                            if ch != "IQ" and ch in self._channel_segments:
                                self._channel_segments[ch].append((offset, standard_tiled))
                else:
                    pulse_len = len(pulse_shape)
                    tiled = np.tile(pulse_shape, repetitions) if repetitions > 1 else pulse_shape
                    for ch in chnl:
                        if ch in self._channel_segments:
                            self._channel_segments[ch].append((offset, tiled))

                offset += pulse_len * repetitions
            else:
                for _ in range(repetitions):
                    current_run_count = self._step_run_tracker[step_id]

                    if used_iq:
                        if len(chnl) > 1:
                            pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                            standard_pulse = self.compile_pulse(pulse_type, current_run_count)
                        else:
                            pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                    else:
                        pulse_shape = self._get_cached_pulse(step['block'], pulse_type, current_run_count)

                    self._step_run_tracker[step_id] += 1

                    # Determine exact length
                    pulse_len = len(pulse_shape[0]) if used_iq else len(pulse_shape)

                    # Only record segments for channels actually carrying data this iteration; idle
                    # channels are left as zeros in the final array instead of being allocated here
                    if used_iq:
                        i_pulse, q_pulse = pulse_shape[0], pulse_shape[1]
                        if self._logic.i_channel in self._channel_segments:
                            self._channel_segments[self._logic.i_channel].append((offset, i_pulse))
                        if self._logic.q_channel in self._channel_segments:
                            self._channel_segments[self._logic.q_channel].append((offset, q_pulse))
                        for ch in chnl:
                            if ch != "IQ" and ch in self._channel_segments:
                                self._channel_segments[ch].append((offset, standard_pulse))
                    else:
                        for ch in chnl:
                            if ch in self._channel_segments:
                                self._channel_segments[ch].append((offset, pulse_shape))

                    offset += pulse_len

            step_end = offset
            self._max_len = max(self._max_len, step_end)

            # Continue this step's own chain independently - other steps sharing this flag start
            # at the same offset but may finish (and trigger their own next step) at a different time
            send_flag = step.get('Send Trig', 0)
            if send_flag != 0 and send_flag in self.steps_by_wait_flag:
                self._compile_flag(send_flag, step_end)

    def _get_cached_pulse(self, block_key, pulse_type, current_run_count):
        """ Compiles a non-IQ pulse, reusing a cached result for blocks with no length increment """
        cache_key = ','.join(map(str, block_key)) if isinstance(block_key, list) else block_key

        if cache_key in self.compiled_pulses:
            return self.compiled_pulses[cache_key]

        pulse_shape = self.compile_pulse(pulse_type, current_run_count)
        if pulse_type[3] == 0 and pulse_type[4] == 0:
            self.compiled_pulses[cache_key] = pulse_shape
        return pulse_shape

    def compile_pulse(self, pulse_parameters, iters=0, iq_phase=0, iq_out=False):

        pulse_type = pulse_parameters[0]
        if pulse_type == "Pulses" or pulse_type =="Variable Pulses":
            if isinstance(pulse_parameters[1], str) or isinstance(pulse_parameters[2], str):
                if iq_out:
                    return [np.zeros(10), np.zeros(10)]
                return np.zeros(10)

            pulse_length = pulse_parameters[1] * self.fs #self.pulse_length.value()
            pause_length = pulse_parameters[2] * self.fs #self.pause_length.value()
            pulse_step_size = pulse_parameters[3] * self.fs #self.increment_size.value()
            pause_step_size = pulse_parameters[4] * self.fs #self.pause_increment_size.value()

            if len( pulse_parameters) > 5:
                pulse_amplitude = pulse_parameters[5]
            else:
                pulse_amplitude = 1

            num_pulse_samples = int(pulse_length + pulse_step_size*(iters // self.steps_per_iter))
            num_pause_samples = int(pause_length + pause_step_size*(iters // self.steps_per_iter))
            waveform = np.concatenate((np.ones(num_pulse_samples), np.zeros(num_pause_samples)))
            
            if iq_out:
                # Scale to accomodate the phase from IQ
                return [pulse_amplitude * np.cos(np.radians(iq_phase))*waveform, pulse_amplitude * np.sin(np.radians(iq_phase))*waveform] 
            else:
                return pulse_amplitude * waveform
        elif pulse_type == "Frequency Sweep": # Trigometric identity: cos(2 pi df t)cos(2 pi f_c t) - sin(2 pi df t)sin( 2 pi f_c t) = cos(2 pi (f_c + df) t)
            duration = pulse_parameters[1] #duration scaled to ns
            steps = pulse_parameters[4] #self.sweep_steps.value()
            freq = pulse_parameters[2] + ((pulse_parameters[3] - pulse_parameters[2]) / steps) * ((iters // self.steps_per_iter) % steps)

            pts_per_step = int(self.fs * duration)

            dt = 1.0 / self.fs
            
            start_idx = 0
            end_idx = pts_per_step

            phase_step = 2 * np.pi * freq * dt

            current_phase = pulse_parameters[5]
            block_phases = current_phase + np.arange(pts_per_step) * phase_step # Use phases to construct the sin and cos signals used in this sweep

            if iq_out:
                # total_samples = steps * pts_per_step
                cos_signal = np.empty(pts_per_step)
                sin_signal = np.empty(pts_per_step)
                
                cos_signal[start_idx:end_idx] = -np.sin(block_phases + np.radians(iq_phase))
                sin_signal[start_idx:end_idx] = np.cos(block_phases + np.radians(iq_phase))

                current_phase = block_phases[-1] + phase_step
                pulse_parameters[5] = current_phase % 360
                
                return [cos_signal, sin_signal]
            else: # Sweep should be done using IQ can be changed if needed
                self._logic.log.warning('Frequency sweep called on non-IQ channel non supported, returning zeros')
                return np.zeros(pts_per_step)
        else:
            return pulse_parameters[1]