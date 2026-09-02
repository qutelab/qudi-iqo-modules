import numpy as np

from qtpy import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
import spcm
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
        graph_waveform = {}
        try:
            self.log.debug("Loading waveform")

            # Swap behavior depending on variable type of filepath
            if isinstance(filepath, str):
                temp_data = np.loadtxt(filepath, delimiter=',')
            else:
                temp_data = filepath

            # Differentiate behavior between analog and digital
            if 'a_' in channel_key:
                if temp_data.ndim > 1:
                    temp_data = temp_data[:, 0]
                data = []

                if np.max(temp_data) <= 1 and np.min(temp_data) >= -1:
                    temp_data = temp_data * 32767 # Scales to max amplitude
                    temp_data = np.asarray(temp_data, dtype=np.int16)
                else:
                    temp_data = np.asarray(temp_data, dtype=np.int16)
    
                temp_data = np.clip(temp_data, -32767, 32767)
                # if self._awg.reps > 0:
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
                # else:
                    # data = np.zeros(len(temp_data) * 32)
                    # for i in range(32):
                        # data[i * len(temp_data): (i+1)*len(temp_data)] = temp_data

            if 'd_' in channel_key:
                if temp_data.ndim > 1:
                    temp_data = temp_data[:, 0]
                data = []
                temp_data = np.where(temp_data > 0.5, 1, 0) # Set all data to 1 or 0

                # if self._awg.reps > 0:
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
                # else:
                    # data = temp_data
                # else:
                    # data = np.zeros(len(temp_data) * 32)
                    # for i in range(32):
                        # data[i * len(temp_data): (i+1)*len(temp_data)] = temp_data

            self.waveform[channel_key] = data
            graph_waveform[channel_key] = data[:min(1000000, len(data))] # for preformance reasons limit how much is graphed
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

    # -------------------------------------------------
    # Upload waveform
    # -------------------------------------------------

    def upload_waveform(self):
        """ Uploads the loaded waveform into AWG memory """
        if self.waveform is None:
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
            for channel in self.waveform.keys():
                channel_length = len(self.waveform[channel])

                amplitude_factor = 1
                if self.length_mode == 'padding':
                    self.waveform[channel] = np.pad(
                        self.waveform[channel],
                        (0, max_length - channel_length),
                        mode='constant',
                        constant_values=0
                    )

                if 'd_' in channel:
                    digital_samples[channel] = self.waveform[channel]
                if 'a_' in channel:
                    analog_samples[channel] = np.asarray(amplitude_factor * self.waveform[channel], dtype=np.int16)

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
            if isinstance(err, spcm.SpcmTimeout):
                self._awg.pulser_off()
            else:
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
            
            for channel in waveforms.keys():
                self.load_waveform_file(np.array(waveforms[channel]), channel)
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

            current_iteration = None
            current_block_id = 0
            current_trigger_id = 0

            sequence = []
            temp_sequence = []
            temp_indx = 0
            max_length = 0
            num_iters = 1
            for line in lines:
                if "%" in line:
                    continue

                if "iterate" in line:
                    num_iters = int(line.split(" ")[1][:-1])
                    continue
                elif "inline" in line:
                    continue
                    # if current_block_id > 0:
                        # current_trigger_id += 1
                elif "evaluate" in line:
                    # if current_block_id > 0:
                        # current_trigger_id += 1
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
                    current_block_id += 1
                    
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
                    
                    current_block_id += 1
                    
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

    def compile(self):
        """Starts compilation and resets local run trackers."""
        # Reset tracker for this compilation run
        self._step_run_tracker = {id(step): 0 for step in self.all_steps}
        waveform = self._compile_flag(0)
        print("Compiling Sequence Finished")
        return waveform

    def _compile_flag(self, flag_id):
        if flag_id not in self.steps_by_wait_flag:
            return {ch: np.array([], dtype=np.float64) for ch in self.all_channels if ch != "IQ"}
    
        # Use lists as temporary staging buffers for each channel
        channel_buffers = {ch: [] for ch in self.all_channels if ch != "IQ"}
        
        for step in self.steps_by_wait_flag[flag_id]:
            step_id = id(step)
            repetitions = step.get('repetitions', 1)
    
            for _ in range(repetitions):
                current_run_count = self._step_run_tracker[step_id]
                chnl = list(step.get('channels', []))
                used_iq = False
                
                if isinstance(step['block'], str):
                    pulse_type = self.pulse_blocks[step['block']]
                else:
                    pulse_type = step['block']

                if "IQ" in chnl:
                    if len(chnl) > 1:
                        pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                        standard_pulse = self.compile_pulse(pulse_type, current_run_count)
                    else:
                        pulse_shape = self.compile_pulse(pulse_type, current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                    used_iq = True
                else:
                    if isinstance(step['block'], list):
                        if ','.join(map(str, step['block'])) in self.compiled_pulses.keys():
                            pulse_shape = self.compiled_pulses[','.join(map(str, step['block']))]
                        else:
                            pulse_shape = self.compile_pulse(pulse_type, current_run_count)
                            if pulse_type[3] != 0 or pulse_type[4] != 0:
                                if isinstance(step['block'], list):
                                    self.compiled_pulses[','.join(map(str, step['block']))] = pulse_shape
                    else:
                        if step['block'] in self.compiled_pulses.keys():
                            pulse_shape = self.compiled_pulses[step['block']]
                        else:
                            pulse_shape = self.compile_pulse(pulse_type, current_run_count)
                            if pulse_type[3] != 0 or pulse_type[4] != 0:
                                self.compiled_pulses[step['block']] = pulse_shape
    
                self._step_run_tracker[step_id] += 1
                
                # Determine exact length
                pulse_len = len(pulse_shape[0]) if used_iq else len(pulse_shape)

                # Build iteration waveforms as standard dict of arrays
                iter_waveforms = {}
                if used_iq:
                    i_pulse, q_pulse = pulse_shape[0], pulse_shape[1]
                    for ch in self.all_channels:
                        if ch == self._logic.i_channel:
                            iter_waveforms[ch] = i_pulse
                        elif ch == self._logic.q_channel:
                            iter_waveforms[ch] = q_pulse
                        elif ch in chnl:
                            iter_waveforms[ch] = standard_pulse
                        else:
                            iter_waveforms[ch] = np.zeros(pulse_len, dtype=np.float64)
                else:
                    for ch in self.all_channels:
                        if ch in chnl:
                            iter_waveforms[ch] = pulse_shape
                        else:
                            iter_waveforms[ch] = np.zeros(pulse_len, dtype=np.float64)

                # Accumulate current iteration waveforms into channel buffers
                for ch in channel_buffers:
                    if ch in iter_waveforms and iter_waveforms[ch].size > 0:
                        channel_buffers[ch].append(iter_waveforms[ch])

                # Handle recursive nested sequences cleanly by pushing child arrays into buffers too
                send_flag = step.get('Send Trig', 0)
                if send_flag != 0 and send_flag in self.steps_by_wait_flag:
                    child_waveforms = self._compile_flag(send_flag)
                    for ch in channel_buffers:
                        if ch in child_waveforms and child_waveforms[ch].size > 0:
                            channel_buffers[ch].append(child_waveforms[ch])

        # Find the maximum length across all accumulated blocks for uniform padding
        max_len = 0
        channel_arrays = {}
        for ch, buf in channel_buffers.items():
            if buf:
                total_len = sum(seg.size for seg in buf)
                if total_len > max_len:
                    max_len = total_len

        # Final single-allocation pass per channel
        flag_waveforms = {}
        for ch, buf in channel_buffers.items():
            if not buf:
                flag_waveforms[ch] = np.array([], dtype=np.float64)
                continue
            
            total_len = sum(seg.size for seg in buf)
            master_arr = np.zeros(max_len, dtype=np.float64)
            
            current_idx = 0
            for seg in buf:
                end_idx = current_idx + seg.size
                master_arr[current_idx:end_idx] = seg
                current_idx = end_idx
                
            flag_waveforms[ch] = master_arr

        return flag_flag_waveforms if 'flag_flag_waveforms' in locals() else flag_waveforms

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
            waveform = []
    
            waveform.extend(np.ones( int(pulse_length + pulse_step_size*(iters // self.steps_per_iter) )) )
            waveform.extend(np.zeros( int(pause_length + pause_step_size*(iters // self.steps_per_iter) )) )
            
            if iq_out:
                # Scale to accomodate the phase from IQ
                return [pulse_amplitude * np.cos(np.radians(iq_phase))*np.array(waveform), pulse_amplitude * np.sin(np.radians(iq_phase))*np.array(waveform)] 
            else:
                return pulse_amplitude * np.array(waveform)
        elif pulse_type == "Frequency Sweep": # Trigometric identity: cos(2 pi df t)cos(2 pi f_c t) - sin(2 pi df t)sin( 2 pi f_c t) = cos(2 pi (f_c + df) t)
            duration = pulse_parameters[1] #duration scaled to ns
            steps = pulse_parameters[4] #self.sweep_steps.value()
            freq = pulse_parameters[2] + ((pulse_parameters[3] - pulse_parameters[2]) / steps) * ((iters // self.steps_per_iter) % steps)

            pts_per_step = int(self.fs * duration)

            current_phase = 0.0
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
                return np.empty(pts_per_step)
        else:
            return pulse_parameters[1]