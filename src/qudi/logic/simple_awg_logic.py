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
                if self._awg.reps > 0:
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
                else:

                    for _ in range(32):
                        data.extend(temp_data)

            if 'd_' in channel_key:
                if temp_data.ndim > 1:
                    temp_data = temp_data[:, 0]
                data = []
                temp_data = np.where(temp_data > 0.5, 1, 0) # Set all data to 1 or 0

                if self._awg.reps > 0:
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
                else:

                    for _ in range(32):
                        data.extend(temp_data)

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
            current_params = self.pulse_blocks[current_block]
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
                wait_flag = step.get('Recieve Trig', 0)
                if wait_flag not in self.steps_by_wait_flag:
                    self.steps_by_wait_flag[wait_flag] = []
                self.steps_by_wait_flag[wait_flag].append(step)
    
            # Tracks how many times a step has been run
            self._step_run_tracker = {}

    def compile(self):
        """Starts compilation and resets local run trackers."""
        # Reset tracker for this compilation run
        self._step_run_tracker = {id(step): 0 for step in self.all_steps}
        return self._compile_flag(0)

    def _compile_flag(self, flag_id):
        """ This is used to recursively compile the sequence it starts at flag_id and recurses until no further steps are left """
        if flag_id not in self.steps_by_wait_flag: # Shouldn't happen but just in case
            return {ch: np.array([], dtype=np.float64) for ch in self.all_channels if ch != "IQ"}
    
        parallel_waveforms_list = [] # This is used to ensure that the step can have multiple pulses on differing channels
        
        for step in self.steps_by_wait_flag[flag_id]:
            # Initialize step waveforms as empty arrays for this step block
            step_waveforms = {ch: np.array([], dtype=np.float64) for ch in self.all_channels if ch != "IQ"}
            
            step_id = id(step)
            repetitions = step.get('repetitions', 1)
    
            for _ in range(repetitions):
                current_run_count = self._step_run_tracker[step_id]
                chnl = list(step.get('channels', [])) # Channels designated by this step
                used_iq = False

                if "IQ" in chnl: # Differentiates IQ dependant pulses
                    if len(chnl) > 1:
                        pulse_shape = self.compile_pulse(self.pulse_blocks[step['block']], current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                        standard_pulse = self.compile_pulse(self.pulse_blocks[step['block']], current_run_count)
                    else:
                        pulse_shape = self.compile_pulse(self.pulse_blocks[step['block']], current_run_count, iq_out=True, iq_phase=step["IQ Phase"])
                    used_iq = True
                else:
                    pulse_shape = self.compile_pulse(self.pulse_blocks[step['block']], current_run_count)
    
                # Increment run counter per step iteration
                self._step_run_tracker[step_id] += 1
    
                # Determine the exact length of the generated pulse for alignment
                if used_iq:
                    pulse_len = len(pulse_shape[0])
                else:
                    pulse_len = len(pulse_shape)

                # Build iteration waveforms, ensuring ALL channels are accounted for with proper length (padding with zeros)
                iter_waveforms = {}
                if used_iq:
                    i_pulse, q_pulse = pulse_shape[0], pulse_shape[1]
                    for ch in self.all_channels:
                        if ch == self._logic.i_channel:
                            iter_waveforms[ch] = i_pulse.copy()
                        elif ch == self._logic.q_channel:
                            iter_waveforms[ch] = q_pulse.copy()
                        elif ch in chnl:
                            iter_waveforms[ch] = standard_pulse
                        else:
                            iter_waveforms[ch] = np.zeros(pulse_len, dtype=np.float64)
                else:
                    for ch in self.all_channels:
                        if ch in chnl:
                            iter_waveforms[ch] = pulse_shape.copy()
                        else:
                            iter_waveforms[ch] = np.zeros(pulse_len, dtype=np.float64)
    
                # Handle recursive nested sequences
                send_flag = step.get('Send Trig', 0)
                if send_flag != 0 and send_flag in self.steps_by_wait_flag:
                    child_waveforms = self._compile_flag(send_flag)
                    
                    # Find max length between iter and child to pad them evenly before concatenating
                    child_len = len(next(iter(child_waveforms.values()))) if child_waveforms else 0
                    
                    for ch in iter_waveforms:
                        child_wf = child_waveforms.get(ch, np.zeros(child_len, dtype=np.float64))
                        # Concatenate the current step iteration with its recursive child sequence
                        iter_waveforms[ch] = np.concatenate([iter_waveforms[ch], child_wf])

                # Append iteration to step accumulator
                for ch in iter_waveforms:
                    step_waveforms[ch] = np.concatenate([step_waveforms[ch], iter_waveforms[ch]])
    
            parallel_waveforms_list.append(step_waveforms)
        
        # Determine maximum length across ALL real channels in this parallel group
        max_len = 0
        for step_wf in parallel_waveforms_list:
            for ch, wf in step_wf.items():
                if len(wf) > max_len:
                    max_len = len(wf)
    
        # Overlay (sum) parallel waveforms safely with uniform padding
        flag_waveforms = {ch: np.zeros(max_len, dtype=np.float64) for ch in self.all_channels if ch != "IQ"}

        for step_waveforms in parallel_waveforms_list:
            for ch in flag_waveforms:
                curr_wave = step_waveforms[ch]
                pad_width = max_len - len(curr_wave)
                
                if pad_width > 0:
                    padded_wave = np.pad(curr_wave, (0, pad_width), mode='constant')
                else:
                    padded_wave = curr_wave
    
                flag_waveforms[ch] += padded_wave

        return flag_waveforms

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
            return np.empty(0)