import pyqtgraph as pg

from qtpy import QtWidgets
from qtpy import QtCore

from qudi.core.module import GuiBase
from qudi.core.connector import Connector

from qudi.logic.pulsed.predefined_generate_methods.basic_predefined_methods import *
from qudi.core.configoption import ConfigOption
import qudi.util.paths as paths
from qtpy.QtWidgets import *
from qtpy.QtCore import *
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox

from qudi.logic.simple_awg_logic import PulseCompiler

import pickle
import json

import os
#import importlib
#import sys
import numpy as np
import time


class SimpleAWGGui(GuiBase):
    """
    GUI module for controlling SimpleAWGLogic.

    Provides:
      - AWG Channel setup and control
      - Pulse train creation
      - AWG control

    example config for copy-paste:

    simple_awg_gui:
        module.Class: 'simple_awg.simple_awg_gui.SimpleAWGGui'
        options:
            save_path: 'C:\\'  #Defaults to default_data_dir\\Pulses, e.g. USERDIR\\qudi\\Data\\Pulses
        connect:
            simple_awg_logic: 'simple_awg_logic'
            microwave: microwave_dummy  #Optional, for direct RF generator control
    """
    simpleawglogic = Connector(interface='SimpleAWGLogic')
    _microwave = Connector(name='microwave', interface='MicrowaveInterface', optional=True)
    save_filepath = ConfigOption('save_path')

    NEW_SEQUENCE_LABEL = 'New Sequence'
    DEFAULT_SAMPLE_RATE = 1e9

    def on_activate(self):

        #These are default in case no sequence or blocks are saved
        self.pulse_blocks = {'idle': np.zeros(10)}
        self.sequences = {'': np.array([]), 'Clear': [{'block': 'idle', 'channels': ['a_ch1', 'a_ch2', 'a_ch3', 'a_ch4', 'd_ch1', 'd_ch2', 'd_ch3', 'd_ch4', 'd_ch5', 'd_ch6'], 'repetitions': 1, 'Send Trig': 1, 'Receive Trig': 0}]}

        #Try to load existing sequences and pulse blocks
        if self.save_filepath is None:
            self.save_filepath = paths.get_default_data_dir() + '\\Pulses'
        if not os.path.exists(self.save_filepath):
            try:
                os.mkdir(self.save_filepath)
                self.log.info(f'Made directory for storing pulses: {self.save_filepath}')
            except:
                self.log.error(f'Unable to create directory for storing pulses, check if parent-dir exists: {self.save_filepath}')
        try:
            with open(f"{self.save_filepath}\\Sequences.pkl", "rb") as f:
                self.sequences = pickle.load(f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error loading dictionary: {e}")

        try:
            with open(f"{self.save_filepath}\\Pulse_Blocks.pkl", "rb") as f:
                self.pulse_blocks = pickle.load(f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error loading dictionary: {e}")

        #Pulse Sequencer sequences are stored separately, as inline pulse/idle time steps
        self.pulse_sequences = {}
        try:
            with open(f"{self.save_filepath}\\PulseSequences.json", "r") as f:
                self.pulse_sequences = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error loading pulse sequences: {e}")

        #These are used for graphs
        self.plot_buffer = []
        self._waveform_dict = {}
           
        self.sequence_table = None
        self.pulse_sequence_table = None

        #enables accessing the logic
        self._logic = self.simpleawglogic()
        self._logic.update_pulses_and_sequences(None, self.pulse_blocks)

        # ------------------------------
        # Initalize main graphics objects
        # ------------------------------
        self._main_window = QtWidgets.QMainWindow()
        self._main_window.setWindowTitle('Simple Spectrum AWG')
        central_widget = QtWidgets.QWidget()
        self._main_window.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        self.tabs = QtWidgets.QTabWidget()
        main_layout.addWidget(self.tabs)

        #Add tabs to gui
        self.waveform_tab = QtWidgets.QWidget()
        self.channels_tab = QtWidgets.QWidget()
        self.creation_tab = QtWidgets.QWidget()
        self.sequence_tab = QWidget()
        self.pulse_sequencer_tab = QWidget()
        self.tabs.addTab(self.waveform_tab, "Waveforms")
        self.tabs.addTab(self.channels_tab, "Channels")
        self.tabs.addTab(self.creation_tab, "Create Pulse")
        self.tabs.addTab(self.sequence_tab, "Sequence Manager")
        self.tabs.addTab(self.pulse_sequencer_tab, "Pulse Sequencer")

        waveform_layout = QtWidgets.QVBoxLayout(self.waveform_tab)
        channels_layout = QtWidgets.QVBoxLayout(self.channels_tab)
        creation_layout = QtWidgets.QVBoxLayout(self.creation_tab)

        # ----------------------------------------
        # Plot widgets
        # ----------------------------------------

        self.plot_widget = pg.PlotWidget()
        self.pulse_plot = pg.PlotWidget()

        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time (s)')

        #self.plot_widget.getPlotItem().setDownsampling(auto=True, method='peak')

        # ----------------------------------------
        # Waveform tab Buttons and Inputs
        # ----------------------------------------

        # mw_freq_sweep_layout = QFormLayout()

        # self.microwave_power_input = QDoubleSpinBox()
        # self.microwave_power_input.setRange(-110, 16.5)
        # self.microwave_power_input.setDecimals(6)

        # self.microwave_start_freq = QDoubleSpinBox()
        # self.microwave_end_freq = QDoubleSpinBox()
        # self.microwave_freq_steps = QSpinBox()
        # self.microwave_freq_steps.setRange(1, 1e7)

        # self.microwave_start_freq.setDecimals(6)
        # self.microwave_end_freq.setDecimals(6)

        # power_layout = QHBoxLayout()
        # power_layout.addWidget( QLabel("Microwave Power") )
        # power_layout.addWidget(self.microwave_power_input)
        # self.microwave_power_input.setSuffix(" dBm")
        # self.microwave_power_input.setValue(-110)
        # # power_layout.addWidget( QLabel("dBm") )
        # power_layout.setSpacing(45)
        # # power_layout.setContentsMargins(0, 100, 0, 100)

        # mw_freq_sweep_layout.addRow(power_layout)

        # mw_freq_layout = QHBoxLayout()
        # mw_freq_layout.addWidget( QLabel("Lower End") )
        # mw_freq_layout.addWidget( self.microwave_start_freq )
        # self.microwave_start_freq.setSuffix(" GHz")
        # mw_freq_layout.addWidget( QLabel(" Higher End") )
        # mw_freq_layout.addWidget( self.microwave_end_freq )
        # self.microwave_end_freq.setSuffix(" GHz")
        # mw_freq_layout.addWidget( QLabel("Number of Steps") )
        # mw_freq_layout.addWidget(self.microwave_freq_steps)
        # mw_freq_layout.setSpacing(45)
        # mw_freq_layout.setContentsMargins(0, 0, 0, 10)

        # mw_freq_sweep_layout.addRow(mw_freq_layout)

        # waveform_layout.addLayout(mw_freq_sweep_layout)
        waveform_layout.addWidget(self.plot_widget)

        button_layout = QtWidgets.QHBoxLayout()

        self.load_button = QtWidgets.QPushButton('Load CSV')
        self.upload_button = QtWidgets.QPushButton('Upload')
        self.start_button = QtWidgets.QPushButton('Start')
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.clear_button = QPushButton('Clear')

        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.upload_button)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.clear_button)

        waveform_layout.addLayout(button_layout)

        hw_button_layout = QtWidgets.QHBoxLayout()
        waveform_layout.addLayout(hw_button_layout)


        self.awg_toggle_button = QtWidgets.QPushButton("Connect to AWG")
        self.awg_toggle_button.setCheckable(True)
        hw_button_layout.addWidget(self.awg_toggle_button)
        self.awg_toggle_button.toggled.connect(self.toggle_awg)

        ### RF Control Window for manual control ###

        self.rfgen_button = QtWidgets.QPushButton('RF Generator Control')
        if self._microwave.is_connected:
            self.rfgen_button.clicked.connect(self._load_rfcontrol)
        else:
            self.rfgen_button.setDisabled(True)
        hw_button_layout.addWidget(self.rfgen_button)

        self._rf_control_window = QtWidgets.QDialog(self._main_window)
        self._rf_control_window.setWindowTitle('RF Signal Generator Control')
        _rf_control_layout = QtWidgets.QGridLayout()
        self._rf_control_window.setLayout(_rf_control_layout)

        _rf_control_layout.addWidget(QtWidgets.QLabel('RF Frequency (Hz)'), 0, 0)
        self._rf_control_frequency = ScienDSpinBox()
        self._rf_control_frequency.setMinimum(100e6)
        self._rf_control_frequency.setMaximum(6e9)
        self._rf_control_frequency.setSuffix('Hz')
        self._rf_control_frequency.setMinimumSize(75, 0)
        _rf_control_layout.addWidget(self._rf_control_frequency, 0, 1)

        _rf_control_layout.addWidget(QtWidgets.QLabel('RF Power (dBm)'), 1, 0)
        self._rf_control_power = QtWidgets.QDoubleSpinBox()
        self._rf_control_power.setMinimum(-110)
        self._rf_control_power.setMaximum(16.5)
        self._rf_control_power.setDecimals(2)
        self._rf_control_power.setSingleStep(0.1)
        _rf_control_layout.addWidget(self._rf_control_power, 1, 1)

        _rf_control_layout.addWidget(QtWidgets.QLabel('Enable Modulation'), 2, 0)
        self._rf_control_modEnable = QtWidgets.QCheckBox()
        _rf_control_layout.addWidget(self._rf_control_modEnable, 2, 1)

        self._rf_control_rfEnable = QtWidgets.QPushButton('Enable Output')
        self._rf_control_rfEnable.setCheckable(True)
        self._rf_control_rfEnable.setStyleSheet("""
            QPushButton:checked { background-color: red; }
            QPushButton:hover { background-color: grey; }
            """)
        _rf_control_layout.addWidget(self._rf_control_rfEnable, 3, 0, 1, 2)

        self._rf_control_update_btn = QtWidgets.QPushButton('Update values')
        _rf_control_layout.addWidget(self._rf_control_update_btn, 4, 0, 1, 2)

        self._rf_control_frequency.valueChanged.connect(lambda x: self._rf_control_send(frequency=x))
        self._rf_control_power.valueChanged.connect(lambda x: self._rf_control_send(power=x))
        self._rf_control_modEnable.stateChanged.connect(lambda x: self._rf_control_send(modulation=x))    
        self._rf_control_rfEnable.toggled.connect(lambda x: self._rf_control_send(rfEnable=x))
        self._rf_control_update_btn.toggled.connect(self._rf_control_update)

        self._rf_control_lock_timer = QTimer()
        self._rf_control_lock_timer.setInterval(1000)
        self._rf_control_lock_timer.timeout.connect(self._rf_control_check_for_lock)
        self._rf_control_lock_timer.start()

        self._rf_control_update()



        # ----------------------------------------
        # Status label (not used too much tbh)
        # ----------------------------------------

        self.status_label = QtWidgets.QLabel('Idle')

        waveform_layout.addWidget(self.status_label)

        self.status_bar = self._main_window.statusBar()

        self.status_bar.showMessage("Idle")
        

        # ----------------------------------------
        # Connect Waveform tab actions
        # ----------------------------------------

        self.load_button.clicked.connect(
            self.load_waveform
        )

        self.upload_button.clicked.connect(
            self._logic.upload_waveform
        )

        self.start_button.clicked.connect(
            self.start_output
        )

        self.stop_button.clicked.connect(
            self._logic.stop_output
        )

        self.clear_button.clicked.connect(
            self._logic.clear_waveforms
        )

        # ----------------------------------------
        # Connect logic signals - Plotting
        # ----------------------------------------

        self._logic.sigWaveformUpdated.connect(
            self.update_plot
        )

        self._logic.sigStatusUpdated.connect(
            self.update_status
        )

        # ----------------------------------------
        # Channel selection - For plotting and loading
        # ----------------------------------------
        
        channel_layout = QtWidgets.QHBoxLayout()
        
        channel_label = QtWidgets.QLabel("Channel:")
        
        self.channel_combo = QtWidgets.QComboBox()
        self.pulse_channel_combo = QtWidgets.QComboBox() #Used in "Create Pulse" tab
        
        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_combo)
        waveform_layout.addLayout(channel_layout)

        self.channel_combo.currentTextChanged.connect(
            self.refresh_plot
        )

        # -------------------------
        # Channel Setup - Analog and Digital
        # -------------------------
        analog_group = QtWidgets.QGroupBox("Analog Channels")
        analog_layout = QtWidgets.QFormLayout()
        
        self.analog_checkboxes = {}
        self.voltages = {}
        self.impedances = {}
        
        for ch in self._logic.awg().analog_channels.keys():
        
            checkbox = QCheckBox(ch)
        
            checkbox.setChecked(
                self._logic.get_channel_state(ch)
            )

            volt_impedance_group = QHBoxLayout()

            volt_group = QHBoxLayout()
            volt_label = QLabel("Voltage:")

            #Enable control over voltage and impedance for each channel
            volt_input = QDoubleSpinBox(decimals=2)
            volt_input.setRange(0, 4)
            volt_input.setSuffix(" V")

            volt_group.addWidget(volt_label)
            volt_group.addWidget(volt_input)

            volt_group.setSpacing(20)

            impedance_group = QHBoxLayout()
            impedance_label = QLabel("Impedance:")

            low_imp = QRadioButton("50 ohms")
            high_imp = QRadioButton("High")

            impedance_buttons = QButtonGroup()

            impedance_buttons.addButton(low_imp, 1)
            impedance_buttons.addButton(high_imp, 2)

            impedance_button_layout = QHBoxLayout()
            impedance_button_layout.addWidget(low_imp)
            impedance_button_layout.addWidget(high_imp)

            impedance_group.addWidget(impedance_label)
            impedance_group.addLayout(impedance_button_layout)

            impedance_group.setSpacing(20)

            volt_impedance_group.addLayout(volt_group)
            volt_impedance_group.addLayout(impedance_group)

            volt_impedance_group.setContentsMargins(100, 0, 75, 0)
            volt_impedance_group.setSpacing(50)
            
            checkbox.toggled.connect( self.make_channel_toggle_handler(ch) )
                    
            # analog_layout.addWidget(checkbox)
            analog_layout.addRow(checkbox, volt_impedance_group)
        
            self.analog_checkboxes[ch] = checkbox
            self.voltages[ch] = volt_input
            self.impedances[ch] = impedance_buttons

        #Simplifies actions by using button to initiate changes to channels
        self.apply_button = QPushButton("Apply Changes")

        self.apply_button.clicked.connect(
            self.apply_channel_changes
        )
        analog_layout.addRow(self.apply_button)
        analog_group.setLayout(analog_layout)
        channels_layout.addWidget(analog_group)

        digital_group = QGroupBox("Digital Channels")
        digital_layout = QVBoxLayout()
        self.digital_checkboxes = {}
        for ch in self._logic.awg().digital_channels.keys():
            checkbox = QtWidgets.QCheckBox(ch)
            checkbox.setChecked(
                self._logic.get_channel_state(ch)
            )
            checkbox.toggled.connect( self.make_channel_toggle_handler(ch) )
            digital_layout.addWidget(checkbox)
            self.digital_checkboxes[ch] = checkbox

        digital_group.setLayout(digital_layout)
        channels_layout.addWidget(digital_group)

        # ------------------------
        # Enables IQ signals - Used by logic
        # ------------------------
        iq_group = QtWidgets.QGroupBox("I/Q Signals")
        iq_layout = QtWidgets.QVBoxLayout()

        self.iq_add_button = QtWidgets.QPushButton("Add I/Q Signal")
        self.iq_add_button.setCheckable(True)
        
        self.iq_add_button.clicked.connect(
            self.add_iq
        )
        
        iq_layout.addWidget(self.iq_add_button)
        i_label = QtWidgets.QLabel("I Channel:")
        
        self.i_channel = QtWidgets.QComboBox()
        
        iq_layout.addWidget(i_label)
        iq_layout.addWidget(self.i_channel)

        q_label = QtWidgets.QLabel("Q Channel:")
        
        self.q_channel = QtWidgets.QComboBox()
        
        iq_layout.addWidget(q_label)
        iq_layout.addWidget(self.q_channel)
        
        self.iq_channel_refresh()

        self.i_channel.setCurrentIndex(0)
        self.q_channel.setCurrentIndex(1)

        self.add_iq()
        
        iq_group.setLayout(iq_layout)

        self.iq_channel_refresh()
        
        channels_layout.addWidget(iq_group)

        channels_layout.addStretch()

        # --------------------
        # Pulse Creation
        # --------------------
        self.creation_tabs = QTabWidget()

        pulse_group = QtWidgets.QGroupBox("Pulse Parameters")
        pulse_layout = QtWidgets.QHBoxLayout()

        # --------------------
        # Pulse Parameters
        # --------------------
        pulse_group = QtWidgets.QGroupBox("Pulse Parameters")
        parameter_layout = QtWidgets.QFormLayout()
         
        length_label = QtWidgets.QLabel("Pulse Length: ")
        self.pulse_length = QtWidgets.QSpinBox()
        self.pulse_length.setMinimum(0)
        self.pulse_length.setValue(10)
        self.pulse_length.setMaximum(2.5E8)
        self.pulse_length.setSuffix(" ns")

        pulse_layout.addWidget(length_label)
        pulse_layout.addWidget(self.pulse_length)
        
        pause_label = QtWidgets.QLabel("Pause Length: ")
        self.pause_length = QtWidgets.QSpinBox()
        self.pause_length.setMinimum(0)
        self.pause_length.setMaximum(2.5E8)
        self.pause_length.setValue(10)
        self.pause_length.setSuffix(" ns")
        pulse_layout.addWidget(pause_label)
        pulse_layout.addWidget(self.pause_length)

        pulse_layout.setSpacing(70)

        rep_layout = QHBoxLayout()
        rep_layout.setContentsMargins(150, 10, 150, 0)

        increment_label = QtWidgets.QLabel("Pulse Size Increment: ")
        self.increment_size = QtWidgets.QSpinBox()
        self.increment_size.setMinimum(-2.5E8)
        self.increment_size.setMaximum(2.5E8)
        self.increment_size.setValue(0)
        self.increment_size.setSuffix(" ns")

        incr_layout = QHBoxLayout()
        incr_layout.addWidget(increment_label)
        incr_layout.addWidget(self.increment_size)

        pause_increment_label = QtWidgets.QLabel("Pause Size Increment: ")
        self.pause_increment_size = QtWidgets.QSpinBox()
        self.pause_increment_size.setMinimum(-2.5E8)
        self.pause_increment_size.setMaximum(2.5E8)
        self.pause_increment_size.setValue(0)
        self.pause_increment_size.setSuffix(" ns")

        self.pulse_amplitude = QDoubleSpinBox()
        self.pulse_amplitude.setRange(-1, 1)
        self.pulse_amplitude.setValue(1)

        incr_layout.addWidget(pause_increment_label)
        incr_layout.addWidget(self.pause_increment_size)

        amp_layout = QHBoxLayout()
        amp_layout.addWidget(QLabel("Pulse Amplitude: "))
        amp_layout.addWidget(self.pulse_amplitude)

        incr_layout.setSpacing(70)
        parameter_layout.addRow(pulse_layout)
        parameter_layout.addRow(incr_layout)
        parameter_layout.addRow(rep_layout)
        parameter_layout.addRow(amp_layout)
        pulse_group.setLayout(parameter_layout)
        pulse_group.setContentsMargins(100, 0, 75, 0)


        # --------------------
        # Pulse Parameters
        # --------------------
        var_pulse_group = QtWidgets.QGroupBox("Variable Pulse Parameters")
        var_parameter_layout = QtWidgets.QFormLayout()
        var_pulse_layout = QtWidgets.QHBoxLayout()
         
        var_length_label = QtWidgets.QLabel("Pulse Length: ")
        self.var_pulse_length = QtWidgets.QLineEdit()
        # self.var_pulse_length.setMinimum(0)
        # self.var_pulse_length.setValue(10)
        # self.var_pulse_length.setMaximum(2.5E8)
        # self.var_pulse_length.setSuffix(" ns")

        var_pulse_layout.addWidget(var_length_label)
        var_pulse_layout.addWidget(self.var_pulse_length)
        
        var_pause_label = QtWidgets.QLabel("Pause Length: ")
        self.var_pause_length = QtWidgets.QLineEdit()
        # self.var_pause_length.setMinimum(0)
        # self.var_pause_length.setMaximum(2.5E8)
        # self.var_pause_length.setValue(10)
        # self.var_pause_length.setSuffix(" ns")
        var_pulse_layout.addWidget(var_pause_label)
        var_pulse_layout.addWidget(self.var_pause_length)

        var_pulse_layout.setSpacing(70)
        
        self.var_pulse_amplitude = QDoubleSpinBox()
        self.var_pulse_amplitude.setRange(-1, 1)
        self.var_pulse_amplitude.setValue(1)

        var_amp_layout = QHBoxLayout()
        var_amp_layout.addWidget(QLabel("Pulse Amplitude: "))
        var_amp_layout.addWidget(self.var_pulse_amplitude)

        var_parameter_layout.addRow(var_pulse_layout)
        var_parameter_layout.addRow(var_amp_layout)
        var_pulse_group.setLayout(var_parameter_layout)
        var_pulse_group.setContentsMargins(100, 0, 75, 0)

        pulse_button_layout = QtWidgets.QHBoxLayout()
                
        pulse_button_layout.addWidget(channel_label)
        pulse_button_layout.addWidget(self.pulse_channel_combo)

        self.pulse_button = QtWidgets.QPushButton('Send Pulse Block')

        pulse_button_layout.addWidget(self.pulse_button)

        self.pulse_button.clicked.connect(
            self.send_pulse_block
        )

        sine_group = QGroupBox()

        sweep_group = QGroupBox()
        sweep_layout = QFormLayout()

        range_layout = QHBoxLayout()

        range_layout.addWidget(QLabel("Lower Range: "))
        self.sweep_low = QDoubleSpinBox()
        self.sweep_low.setMinimum(-2e6)
        self.sweep_low.setMaximum(2e6)
        self.sweep_low.setSuffix(" MHz")
        range_layout.addWidget(self.sweep_low)
        range_layout.addWidget(QLabel("Upper Range: "))
        self.sweep_high = QDoubleSpinBox()
        self.sweep_high.setMinimum(-2e6)
        self.sweep_high.setMaximum(2e6)
        self.sweep_high.setSuffix(" MHz")
        range_layout.addWidget(self.sweep_high)
        range_layout.setSpacing(70)

        sweep_time_layout = QHBoxLayout()
        sweep_time_layout.addWidget(QLabel("Pulse Time: "))
        self.sweep_time = QSpinBox()
        self.sweep_time.setMaximum(2.5e8)
        self.sweep_time.setSuffix(" ns")
        sweep_time_layout.addWidget(self.sweep_time)
        sweep_time_layout.addWidget(QLabel("Number of Steps"))
        self.sweep_steps = QSpinBox()
        self.sweep_steps.setMaximum(2.5e8)
        sweep_time_layout.addWidget(self.sweep_steps)
        sweep_time_layout.setSpacing(70)
        
        sweep_layout.addRow(range_layout)
        sweep_layout.addRow(sweep_time_layout)
        sweep_group.setLayout(sweep_layout)

        self.creation_tabs.addTab(pulse_group, "Pulses")
        self.creation_tabs.addTab(var_pulse_group, "Variable Pulses")
        # self.creation_tabs.addTab(sine_group, "Sine/Cosine")
        self.creation_tabs.addTab(sweep_group, "Frequency Sweep")

        block_button_group = QGroupBox("Create Pulse Block")
        block_button_layout = QFormLayout()
        text_layout = QHBoxLayout()
        buttons_layout = QHBoxLayout()
        
        self.block_name_edit = QLineEdit()
        visualize_block = QPushButton("Plot Pulse Block")
        create_pulse_block = QPushButton("Create Pulse Block")
        save_pulse_block = QPushButton("Save Pulse Block")

        visualize_block.clicked.connect(
            self.plot_pulse
        )

        create_pulse_block.clicked.connect(
            self.create_pulse_block
        )

        save_pulse_block.clicked.connect(
            self.save_pulse_block
        )
        
        text_layout.addWidget(QLabel("Block Name:"))
        text_layout.addWidget(self.block_name_edit)
        text_layout.setSpacing(70)
        text_layout.setContentsMargins(100, 0, 100, 0)
        
        buttons_layout.addWidget(visualize_block)
        buttons_layout.addWidget(create_pulse_block)
        buttons_layout.addWidget(save_pulse_block)

        block_button_layout.addRow(text_layout)
        block_button_layout.addRow(buttons_layout)

        block_button_group.setLayout(block_button_layout)
        
        
        pulse_plot_group = QGroupBox()
        pulse_plot_layout = QHBoxLayout()

        self.pulse_plot.setLabel('left', 'Amplitude')
        self.pulse_plot.setLabel('bottom', 'Time (ns)')

        pulse_plot_layout.addWidget(self.pulse_plot)
        pulse_plot_group.setLayout(pulse_plot_layout)

        # creation_layout.addWidget(pulse_group)
        creation_layout.addWidget(self.creation_tabs)
        creation_layout.addWidget(block_button_group)
        creation_layout.addWidget(pulse_plot_group)
        creation_layout.addLayout(pulse_button_layout)
        # self.refresh_channel_selector()

        # ------------ SEQUENCE ------------------- #
        
        sequence_layout = QVBoxLayout(self.sequence_tab)

        iteration_manage_layout = QHBoxLayout()
        iter_label = QLabel("1 Iteration Step:")
        self.steps_input = QSpinBox()
        self.steps_input.setRange(1, 1000000)
        self.steps_input.setValue(100)
        
        iteration_manage_layout.addWidget(iter_label)
        iteration_manage_layout.addWidget(self.steps_input)
        iteration_manage_layout.addWidget(QLabel(" Reps"))
        sequence_layout.addLayout(iteration_manage_layout)

        iteration_manage_layout.setSpacing(40)
        iteration_manage_layout.setContentsMargins(100, 0, 100, 0)
        
        self.sequence_table = QTableWidget()
        self.sequence_table.setColumnCount(5)
        
        self.sequence_table.setHorizontalHeaderLabels([
            "Pulse Block",
            "Channels",
            "Repetitions",
            "Start After Step",
            "IQ Phase"
        ])
        
        self.sequence_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.sequence_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )

        add_btn = QPushButton("Add Step")
        remove_btn = QPushButton("Remove Step")
        write_sequence_btn = QPushButton("Write Sequence")
        save_sequence_btn = QPushButton("Save Sequence")
        load_sequence_btn = QPushButton("Load Sequence")
        
        load_file_btn = QPushButton("Load Sequence from File")

        current_indicator = QHBoxLayout()

        self.sequence_select = QComboBox()
        #self.sequence_select.setMinimumWidth()
        self.sequence_select.addItems(self.sequences.keys())

        current_indicator.addWidget(self.sequence_select)
        current_indicator.addWidget(load_sequence_btn)

        add_btn.clicked.connect(self.add_sequence_step)
        remove_btn.clicked.connect(self.remove_sequence_step)
        write_sequence_btn.clicked.connect(self.write_sequence)
        save_sequence_btn.clicked.connect(self.save_sequence)
        load_sequence_btn.clicked.connect(self.load_sequence)
        load_file_btn.clicked.connect(self.load_sequence_file)

        self.new_sequence_name = QLineEdit() 
        self.new_sequence_name.textChanged.connect(self.mark_sequence_dirty)

        self.sequence_modified_label = QLabel("")

        sequence_button_layout = QFormLayout()

        standard_btns = QHBoxLayout()
        standard_btns.addWidget(add_btn)
        standard_btns.addWidget(remove_btn)
        standard_btns.addWidget(write_sequence_btn)
        standard_btns.addWidget(save_sequence_btn)
        standard_btns.addWidget(self.new_sequence_name)
        standard_btns.addWidget(self.sequence_modified_label)
        
        sequence_button_layout.addRow(standard_btns)
        sequence_button_layout.addRow(current_indicator)
        sequence_button_layout.addRow(load_file_btn)

        sequence_layout.addWidget(self.sequence_table)
        sequence_layout.addLayout(sequence_button_layout)

        self._sequence_dirty = False

        # ------------ PULSE SEQUENCER ------------------- #

        pulse_sequence_layout = QVBoxLayout(self.pulse_sequencer_tab)

        self.pulse_sequence_table = QTableWidget()
        self.rebuild_pulse_sequence_table([])

        if False:
            self.pulse_sequence_table.setColumnCount(8)

            self.pulse_sequence_table.setHorizontalHeaderLabels([
                "Pulse Time",
                "Pulse Var",
                "Idle Time",
                "Idle Var",
                "Channels",
                "Repetitions",
                "Start After Step",
                "IQ Phase"
            ])

            self.pulse_sequence_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.Stretch
            )

        pulse_seq_add_btn = QPushButton("Add Step")
        pulse_seq_remove_btn = QPushButton("Remove Step")
        pulse_seq_write_btn = QPushButton("Write Sequence")
        pulse_seq_save_btn = QPushButton("Save Sequence")
        pulse_seq_delete_btn = QPushButton("Delete Sequence")
        pulse_seq_load_btn = QPushButton("Load Sequence")

        pulse_seq_current_indicator = QHBoxLayout()

        self.pulse_sequence_select = QComboBox()
        self._refresh_pulse_sequence_combo()

        pulse_seq_current_indicator.addWidget(self.pulse_sequence_select)
        pulse_seq_current_indicator.addWidget(pulse_seq_load_btn)
        pulse_seq_current_indicator.addWidget(pulse_seq_delete_btn)

        pulse_seq_add_btn.clicked.connect(self.add_pulse_sequence_step)
        pulse_seq_remove_btn.clicked.connect(self.remove_pulse_sequence_step)
        pulse_seq_write_btn.clicked.connect(self.write_pulse_sequence)
        pulse_seq_save_btn.clicked.connect(self.save_pulse_sequence)
        pulse_seq_delete_btn.clicked.connect(self.delete_pulse_sequence)
        pulse_seq_load_btn.clicked.connect(self.load_pulse_sequence)

        self.new_pulse_sequence_name = QLineEdit()
        self.new_pulse_sequence_name.textChanged.connect(self.mark_pulse_sequence_dirty)

        self.pulse_sequence_modified_label = QLabel("")

        sample_rate_layout = QHBoxLayout()
        sample_rate_constraints = self._logic.awg().constraints.sample_rate
        self.pulse_sequence_sample_rate = ScienDSpinBox()
        self.pulse_sequence_sample_rate.setMinimum(sample_rate_constraints.min)
        self.pulse_sequence_sample_rate.setMaximum(sample_rate_constraints.max)
        self.pulse_sequence_sample_rate.setSuffix('Hz')
        self.pulse_sequence_sample_rate.setValue(self._logic.awg().get_sample_rate())
        self.pulse_sequence_sample_rate.valueChanged.connect(self.mark_pulse_sequence_dirty)
        sample_rate_layout.addWidget(QLabel("Sample Rate:"))
        sample_rate_layout.addWidget(self.pulse_sequence_sample_rate)

        pulse_seq_button_layout = QFormLayout()

        pulse_seq_standard_btns = QHBoxLayout()
        pulse_seq_standard_btns.addWidget(pulse_seq_add_btn)
        pulse_seq_standard_btns.addWidget(pulse_seq_remove_btn)
        pulse_seq_standard_btns.addWidget(pulse_seq_write_btn)
        pulse_seq_standard_btns.addWidget(pulse_seq_save_btn)
        pulse_seq_standard_btns.addWidget(self.new_pulse_sequence_name)
        pulse_seq_standard_btns.addWidget(self.pulse_sequence_modified_label)

        pulse_seq_button_layout.addRow(sample_rate_layout)
        pulse_seq_button_layout.addRow(pulse_seq_standard_btns)
        pulse_seq_button_layout.addRow(pulse_seq_current_indicator)

        pulse_sequence_layout.addWidget(self.pulse_sequence_table)
        pulse_sequence_layout.addLayout(pulse_seq_button_layout)

        # Defaults to the permanent empty entry rather than whatever was last saved
        self.pulse_sequence_select.setCurrentText(self.NEW_SEQUENCE_LABEL)
        self.load_pulse_sequence()

        self.show()
        if not self._logic._awg.connected:
            self.toggle_awg()
        else:
            # toggle_awg() (which populates self.available_channels) only runs above when
            # connecting; if the AWG was already connected from a prior GUI reload, do it here
            self.refresh_channel_selector()

    def on_deactivate(self):
        self._rf_control_frequency.valueChanged.disconnect()
        self._rf_control_power.valueChanged.disconnect()
        self._rf_control_modEnable.stateChanged.disconnect() 
        self._rf_control_rfEnable.toggled.disconnect()
        self._rf_control_update_btn.toggled.disconnect()
        self._rf_control_lock_timer.timeout.disconnect()
        self._rf_control_lock_timer.stop()
        self._rf_control_window.close()
        self._main_window.close()

    # -------------------------------------------------
    # Load waveform dialog
    # -------------------------------------------------

    def load_waveform(self):
        """Used to load pulse train waveform from csv files"""
   
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._main_window,
            'Load Waveform',
            '',
            'CSV Files (*.csv)'
        )

        if filepath:
            channel = self.channel_combo.currentText()

            self._logic.load_waveform_file(filepath, channel)
            

    # -------------------------------------------------
    # Update plot
    # -------------------------------------------------

    @QtCore.Slot(object)
    def update_plot(self):
        """Loads waveform from logic and then refresh plot """
        self._waveform_dict = self._logic.waveform
        self.refresh_plot()

    def refresh_plot(self):
        """ Clears plots updates plots according to the currently selected channel """
        self.plot_widget.clear()
        self.pulse_plot.clear()
    
        channel = self.channel_combo.currentData()

        selected_block = None
        if hasattr(self, 'block_name_edit'):
            selected_block = self.block_name_edit.text()
        
    
        if channel is None:
            channel = self.channel_combo.currentText()

        if hasattr(self, '_waveform_dict'): # Some times waveforms had not been initialized
            if channel not in self._waveform_dict:
                self.plot_widget.clear()
            else:
                waveform = self._waveform_dict[channel]
                
                ds = max(1,2*(int(np.log2(len(waveform)))-13))  #Downsample when > 10000 data points.
                waveformds = waveform[::ds]
                xax = np.arange(len(waveformds))/self._logic.fs*ds
                #waveform=waveform[:min(len(waveform), max_length)]        
                self.plot_widget.plot(xax,waveformds)

        max_length=100000
        if selected_block not in self.pulse_blocks:
            if len(self.plot_buffer) > 0:
                self.plot_buffer = self.plot_buffer[:min(len(self.plot_buffer), max_length)]
                self.pulse_plot.plot(self.plot_buffer)
            else:
                self.pulse_plot.clear()
        # else:
            # compiler = PulseCompiler(None, self.pulse_blocks, self._logic, self._logic.awg().get_sample_rate() )
            # temp_plot = compiler.compile_pulse(self.create_pulse())
            # self.pulse_plot.plot(temp_plot)

        #Set range to reasonable bounds
        self.plot_widget.getViewBox().autoRange()
        self.pulse_plot.getViewBox().autoRange()

    
    def toggle_awg(self):
        """ If AWG already connected toggle text and button action """
        checked = self._logic._awg.connected
        
        if not checked:
            self._logic.start_awg()  
            self.awg_toggle_button.setText("Disconnect from AWG")
            self.status_bar.showMessage("AWG running")
        else:
            self._logic.stop_awg()
            self.awg_toggle_button.setText("Connect to AWG")
            self.status_bar.showMessage("AWG stopped")

        self.channel_combo.clear()
        self.pulse_channel_combo.clear()
        self.refresh_channel_selector()
        
        if self._logic._awg.connected:
            for channel in self.available_channels:
                self._logic.set_channel_state(channel, self._logic.get_channel_state(channel))

    @QtCore.Slot(str)
    def update_status(self, text):
        self.status_bar.showMessage(text)

    def show(self): 
        """ Shows the main window """
        self._main_window.show()
        self._main_window.raise_()


    def refresh_channel_selector(self):
        """ Attempts to ensure that channels states are correctly linked between logic and gui layers """
        self.load_channel_states()

        current_channel = self.channel_combo.currentText()
        pulse_current_channel = self.pulse_channel_combo.currentText()
    
        self.channel_combo.blockSignals(True)
        self.pulse_channel_combo.blockSignals(True)
    
        self.available_channels = self._logic.get_active_channels()
    
        for ch in self._logic.awg().analog_channels.keys():
            checkbox = self.analog_checkboxes[ch]
        
            checkbox.setChecked(
                self._logic.get_channel_state(ch)
            )

        for ch in self._logic.awg().digital_channels.keys():
            checkbox = self.digital_checkboxes[ch]
        
            checkbox.setChecked(
                self._logic.get_channel_state(ch)
            )

        self.channel_combo.clear()
        self.pulse_channel_combo.clear()
        self.channel_combo.addItems(self.available_channels)
        self.pulse_channel_combo.addItems(self.available_channels)
    
        # Restore previous selection if possible
        if current_channel in self.available_channels:
            self.channel_combo.setCurrentText(current_channel)
            self.pulse_channel_combo.setCurrentText(pulse_current_channel)
    
        self.channel_combo.blockSignals(False)
        self.pulse_channel_combo.blockSignals(False)
    
        self.refresh_plot()

        if not self.sequence_table is None:
            self.rebuild_entire_table()

        if not self.pulse_sequence_table is None:
            self.rebuild_pulse_sequence_table(self.get_pulse_sequence())

    def make_channel_toggle_handler(self, channel):
        """ GUI layer toggles AWG channel states"""

        def handler(state):
            self._logic.set_channel_state(channel, state)
            self.refresh_channel_selector()
    
        return handler

    def iq_channel_refresh(self):
        """ Refreshes the I/Q selection GUI """
        current_i_channel = self.i_channel.currentText()
        current_q_channel = self.q_channel.currentText()
    
        self.i_channel.blockSignals(True)
        self.q_channel.blockSignals(True)
    
        self.i_channel.clear()
        self.q_channel.clear()

        self.i_channel.addItems(self._logic.awg().analog_channels.keys())
        self.q_channel.addItems(self._logic.awg().analog_channels.keys())

        self.i_channel.setCurrentText(current_i_channel)
        self.q_channel.setCurrentText(current_q_channel)
    
        self.i_channel.blockSignals(False)
        self.q_channel.blockSignals(False)

    def add_iq(self):
        """ Select the two channels being used for I/Q """
        i_channel = self.i_channel.currentText()
        q_channel = self.q_channel.currentText()

        if not i_channel == q_channel:
            self._logic.set_iq_channels(i_channel, q_channel)

    def create_pulse(self):
        """ Defines the criteria used to construct each pulse block"""
        new_pulse = {}
        tab_name = self.creation_tabs.tabText(self.creation_tabs.currentIndex())
        
        pulse_parameters =  []
        pulse_parameters.append(tab_name)
        if tab_name == "Pulses":
            pulse_parameters.append(self.pulse_length.value() * 1e-9)
            pulse_parameters.append(self.pause_length.value() * 1e-9)
            pulse_parameters.append(self.increment_size.value() * 1e-9)
            pulse_parameters.append(self.pause_increment_size.value() * 1e-9)
            pulse_parameters.append(self.pulse_amplitude.value())
        elif tab_name == "Frequency Sweep":
            pulse_parameters.append(self.sweep_time.value() * 1e-9)
            pulse_parameters.append(self.sweep_low.value()  * 1e6)
            pulse_parameters.append(self.sweep_high.value() * 1e6)
            pulse_parameters.append(self.sweep_steps.value() )
            # pulse_parameters.append( self.sweep_phase_btns.checkedButton().text() == "Sine" )
            pulse_parameters.append(0)
        elif tab_name == "Variable Pulses":
            pulse_time = self.var_pulse_length.text()
            try: pulse_time=float(pulse_time)
            except: pass
            pulse_parameters.append(pulse_time)
            idle_time = self.var_pause_length.text()
            try: idle_time=float(idle_time)
            except: pass
            pulse_parameters.append(idle_time)
            pulse_parameters.append(0)
            pulse_parameters.append(0)
            pulse_parameters.append(self.var_pulse_amplitude.value())

        return pulse_parameters

    def apply_channel_changes(self):
        """ GUI applies impedance and voltage changes """
        volts = []
        imps = []

        for ch in self.voltages.keys():
            voltage = self.voltages[ch].value()
            volts.append(voltage)

        for ch in self.impedances.keys():
            checked_button = self.impedances[ch].checkedButton()

            if checked_button.text() == "High":
                imps.append("High")
            else:
                imps.append("Low")

        self._logic.awg().voltage = volts
        self._logic.awg().resistance = imps

    def load_channel_states(self):
        """ Get current channel states impedance and voltage """
        volts = self._logic.awg().voltage
        imps = self._logic.awg().resistance

        for i, volt in enumerate(volts):
            self.voltages[f"a_ch{i+1}"].setValue(volt)

        for i, imp in enumerate(imps):
            if imp == "High":
                self.impedances[f"a_ch{i+1}"].button(2).setChecked(True)
            else:
                self.impedances[f"a_ch{i+1}"].button(1).setChecked(True)

    def plot_pulse(self):
        """ Plots the chosen pulse block """
        compiler = PulseCompiler(None, self.pulse_blocks, self._logic, sample_rate=self._logic.awg().get_sample_rate())
        self.plot_buffer = compiler.compile_pulse(self.create_pulse()) #self.create_waveform()
        self.refresh_plot()

    def create_pulse_block(self):
        """ Creates the current pulse block """
        block_name = self.block_name_edit.text()
        self.pulse_blocks[block_name] = self.create_pulse()
        
        self._logic.update_pulses_and_sequences(None, self.pulse_blocks)
        self.rebuild_entire_table()

    def save_pulse_block(self):
        """ Save the pulse block to the target location """
        block_name = self.block_name_edit.text()
        new_block = self.create_pulse()

        self.rebuild_entire_table()

        saved_blocks = {}

        #Load currently saved pulse blocks
        try:
            with open(f"{self.save_filepath}\\Pulse_Blocks.pkl", "rb") as f:
                saved_blocks = pickle.load(f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error saving dictionary: {e}")

        saved_blocks[block_name] = new_block

        #Save all previous pulse blocks and chosen
        try:
            with open(f"{self.save_filepath}\\Pulse_Blocks.pkl", "wb") as f:
                pickle.dump(saved_blocks, f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error saving dictionary: {e}")
            
        self._logic.update_pulses_and_sequences(None, self.pulse_blocks)

    def start_output(self):
        """ Interface between GUI level and logic level to start the sequence """

        # freq_steps = self.microwave_freq_steps.value()
        # lower_bound = self.microwave_start_freq.value()
        # upper_bound = self.microwave_end_freq.value()
        # power = self.microwave_power_input.value()

        # if freq_steps > 1:
        #     self._logic.scan_frequencies(power, lower_bound*1e9, upper_bound*1e9, freq_steps)
        # else:
        self._logic.start_output()

    def send_pulse_block(self):
        """ Pulse block upload onto specific channel """
        
        channel = self.pulse_channel_combo.currentText()
        block_name = self.block_name_edit.text()

        if block_name is None:
            return

        compiler = PulseCompiler(None, self.pulse_blocks, self._logic, sample_rate=self._logic.awg().get_sample_rate())

        self._logic.load_waveform_file(compiler.compile_pulse(self.pulse_blocks[block_name], 0), channel)
        
    def add_sequence_step(self):
        """ Adds a step to the GUI """
    
        row = self.sequence_table.rowCount()
        self.sequence_table.insertRow(row)
    
        #
        # Pulse block
        #
        block = QComboBox()
        block.addItems(sorted(self.pulse_blocks.keys()))
        self.sequence_table.setCellWidget(row, 0, block)
    
        #
        # Channels
        #
        channel_widget = ChannelWidget(["IQ"] + self.available_channels)
        self.sequence_table.setCellWidget(row, 1, channel_widget)
    
        #
        # Repetitions
        #
        reps = QSpinBox()
        reps.setRange(1, 10000)
        reps.setValue(1)
        self.sequence_table.setCellWidget(row, 2, reps)
    
        #
        # Start After Step - which step number this step should begin after (0 = start immediately)
        #
        start_after_step = QSpinBox()
        start_after_step.setRange(0, 9999)
        start_after_step.setValue(0)
        self.sequence_table.setCellWidget(row, 3, start_after_step)

        iq_phase = QDoubleSpinBox()
        iq_phase.setRange(-360, 360)
        iq_phase.setValue(0)
        self.sequence_table.setCellWidget(row, 4, iq_phase)
    
        self.sequence_table.resizeRowToContents(row)

        self._connect_row_dirty_signals(block, channel_widget, reps, start_after_step, iq_phase)
        self.mark_sequence_dirty()

    def remove_sequence_step(self):
        """ Remove a step from the sequence GUI """
        row = self.sequence_table.currentRow()
    
        if row >= 0:
            self.sequence_table.removeRow(row)
            self.mark_sequence_dirty()

    def get_sequence(self):
        """ Returns the sequence as a dictionary """
    
        sequence = []
    
        for row in range(self.sequence_table.rowCount()):
    
            block = self.sequence_table.cellWidget(row, 0).currentText()
            channels = self.sequence_table.cellWidget(row, 1).selected_channels()
            reps = self.sequence_table.cellWidget(row, 2).value()
            start_after_step = self.sequence_table.cellWidget(row, 3).value()
            iq_phase = self.sequence_table.cellWidget(row, 4).value()
            
            sequence.append({
                "block": block,
                "channels": channels,
                "repetitions": reps,
                "Send Trig": row + 1, # each step's own step number, used as the trigger target for later steps
                "Receive Trig": start_after_step,
                "IQ Phase": iq_phase
            })
    
        return sequence

    def write_sequence(self):
        """ Compiles the sequence as currently displayed in the table """
        sequence_name = self.new_sequence_name.text()
        sequence = self.get_sequence()

        self.sequences[sequence_name] = sequence

        self.sequence_select.clear()
        self.sequence_select.addItems(self.sequences.keys())
        self.sequence_select.setCurrentText(sequence_name)
        
        waveforms = {}

        steps_per_iter = self.steps_input.value()

        self._logic.set_sample_rate(self.DEFAULT_SAMPLE_RATE)
        
        compiler = PulseCompiler(sequence, self.pulse_blocks, self._logic, sample_rate=self.DEFAULT_SAMPLE_RATE, steps_per_iter=steps_per_iter)
        waveforms = compiler.compile()

        self._logic.load_waveform_set(waveforms)
            
        self._logic.update_pulses_and_sequences(sequence, self.pulse_blocks)

        #self.clear_sequence_dirty()

        # for i in range(1000):
        #     avail_pulses = self.pulse_blocks.copy()
        #     self._logic.increment_time_pulse(sequence, avail_pulses, iters=i)

        #     self.start_output()
        #     time.sleep(1)

    def load_sequence_file(self):
        """Used to load and compile pulse sequence from file"""
   
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._main_window,
            'Load Sequence',
            '',
            'SEQ Files (*.seq)'
        )

        if filepath:
            sequence_name = self.new_sequence_name.text()
            sequence = self._logic.read_sequence_file(filepath)
            self.sequences[sequence_name] = sequence
            
            waveforms = {}

            steps_per_iter = self.steps_input.value()
            compiler = PulseCompiler(sequence, self.pulse_blocks, self._logic, steps_per_iter=steps_per_iter)
            waveforms = compiler.compile()

            self._logic.load_waveform_set(waveforms)
                
            self._logic.update_pulses_and_sequences(sequence, self.pulse_blocks)

    def save_sequence(self):
        """ Saves whatever sequence is currently displayed in the table to disk """
        new_name = self.new_sequence_name.text()
        new_sequence = self.get_sequence()

        self.sequences[new_name] = new_sequence

        self.sequence_select.clear()
        self.sequence_select.addItems(self.sequences.keys())
        self.sequence_select.setCurrentText(new_name)

        try:
            with open(f"{self.save_filepath}\\Sequences.pkl", "wb") as f:
                pickle.dump(self.sequences, f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error saving dictionary: {e}")

        new_blocks = {}
        try:
            with open(f"{self.save_filepath}\\Pulse_Blocks.pkl", "rb") as f:
                new_blocks = pickle.load(f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error saving dictionary: {e}")

        for step in new_sequence:
            block = step["block"]
            new_blocks[block] = self.pulse_blocks[block]

        try:
            with open(f"{self.save_filepath}\\Pulse_Blocks.pkl", "wb") as f:
                pickle.dump(new_blocks, f)
        except (OSError, pickle.PickleError) as e:
            print(f"Error saving dictionary: {e}")

        self.clear_sequence_dirty()

    def load_sequence(self):
        """ Loads the sequence into the GUI """
        selected_sequence = self.sequence_select.currentText()

        sequence = self.sequences[selected_sequence]
        self.new_sequence_name.setText(selected_sequence)
        
        self.rebuild_entire_table(sequence=sequence)

        # rebuilding the table triggers dirty signals; the freshly loaded sequence is clean
        self.clear_sequence_dirty()

    def mark_sequence_dirty(self, *_args):
        """ Flags the displayed sequence as having unsaved changes """
        self._sequence_dirty = True
        self.sequence_modified_label.setText('*')

    def clear_sequence_dirty(self):
        """ Flags the displayed sequence as matching the last written/saved/loaded state """
        self._sequence_dirty = False
        self.sequence_modified_label.setText('')

    def _connect_row_dirty_signals(self, block, channel_widget, reps, start_after_step, iq_phase):
        """ Marks the sequence dirty whenever any widget in a sequence table row changes """
        block.currentIndexChanged.connect(self.mark_sequence_dirty)
        reps.valueChanged.connect(self.mark_sequence_dirty)
        start_after_step.valueChanged.connect(self.mark_sequence_dirty)
        iq_phase.valueChanged.connect(self.mark_sequence_dirty)
        for checkbox in channel_widget.checkboxes.values():
            checkbox.toggled.connect(self.mark_sequence_dirty)


    def rebuild_entire_table(self, sequence=None):
        """ Updates the entire table to match current conditions (IE channels, and pulse blocks) """
        # store current state
        if sequence is None:
            old_sequence = self.get_sequence()
        else:
            old_sequence = sequence
    
        self.sequence_table.clear()
        self.sequence_table.setRowCount(0)
    
        self.sequence_table.setColumnCount(5)
        self.sequence_table.setHorizontalHeaderLabels([
            "Block", "Channels", "Reps", "Start After Step", "IQ Phase"
        ])
    
        # rebuild rows
        for step in old_sequence:
    
            row = self.sequence_table.rowCount()
            self.sequence_table.insertRow(row)
    
            block = QComboBox()
            block.addItems(sorted(self.pulse_blocks.keys()))
            block.setCurrentText(step["block"])

            sequence_channels = ["IQ"] + self.available_channels
    
            self.sequence_table.setCellWidget(row, 0, block)
    
            ch_widget = ChannelWidget(sequence_channels)
            ch_widget.set_channels(step["channels"])
    
            self.sequence_table.setCellWidget(row, 1, ch_widget)
    
            reps = QSpinBox()
            reps.setMinimum(1)
            reps.setMaximum(10000)
            reps.setValue(step["repetitions"])

    
            start_after_step = QSpinBox()
            start_after_step.setRange(0, 9999)
            start_after_step.setValue(step["Receive Trig"])
    
            self.sequence_table.setCellWidget(row, 2, reps)
            self.sequence_table.setCellWidget(row, 3, start_after_step)

            iq_phase = QDoubleSpinBox()
            iq_phase.setRange(-360, 360)
            iq_phase.setValue(0)
            self.sequence_table.setCellWidget(row, 4, iq_phase)

            self.sequence_table.resizeRowToContents(row)

            self._connect_row_dirty_signals(block, ch_widget, reps, start_after_step, iq_phase)

    # -------------------------------------------------
    # Pulse Sequencer tab
    # -------------------------------------------------

    def add_pulse_sequence_step(self):
        """ Adds a step to the Pulse Sequencer table """
        row = self.pulse_sequence_table.rowCount()
        self.pulse_sequence_table.insertRow(row)

        pulse_time = ScienDSpinBox()
        pulse_time.setMinimum(0)
        pulse_time.setSuffix('s')
        pulse_time.setValue(0)
        self.pulse_sequence_table.setCellWidget(row, 0, pulse_time)

        pulse_var = QCheckBox()
        self.pulse_sequence_table.setCellWidget(row, 1, pulse_var)

        idle_time = ScienDSpinBox()
        idle_time.setMinimum(0)
        idle_time.setSuffix('s')
        idle_time.setValue(0)
        self.pulse_sequence_table.setCellWidget(row, 2, idle_time)

        idle_var = QCheckBox()
        self.pulse_sequence_table.setCellWidget(row, 3, idle_var)

        channel_widget = ChannelWidget(["IQ"] + self.available_channels)
        self.pulse_sequence_table.setCellWidget(row, 4, channel_widget)

        reps = QSpinBox()
        reps.setRange(1, 10000)
        reps.setValue(1)
        self.pulse_sequence_table.setCellWidget(row, 5, reps)

        start_after_step = QSpinBox()
        start_after_step.setRange(0, 9999)
        start_after_step.setValue(0)
        self.pulse_sequence_table.setCellWidget(row, 6, start_after_step)

        iq_phase = QDoubleSpinBox()
        iq_phase.setRange(-360, 360)
        iq_phase.setValue(0)
        self.pulse_sequence_table.setCellWidget(row, 7, iq_phase)

        self.pulse_sequence_table.resizeRowToContents(row)

        self._connect_pulse_sequence_row_dirty_signals(
            pulse_time, idle_time, channel_widget, reps, start_after_step, iq_phase
        )
        self.mark_pulse_sequence_dirty()

    def remove_pulse_sequence_step(self):
        """ Removes the selected step from the Pulse Sequencer table """
        row = self.pulse_sequence_table.currentRow()

        if row >= 0:
            self.pulse_sequence_table.removeRow(row)
            self.mark_pulse_sequence_dirty()

    def get_pulse_sequence(self):
        """ Returns the Pulse Sequencer table contents as a sequence of inline pulse/idle blocks """
        sequence = []

        for row in range(self.pulse_sequence_table.rowCount()):
            pulse_time = self.pulse_sequence_table.cellWidget(row, 0).value()
            pulse_var = self.pulse_sequence_table.cellWidget(row, 1).isChecked()
            idle_time = self.pulse_sequence_table.cellWidget(row, 2).value()
            idle_var = self.pulse_sequence_table.cellWidget(row, 3).isChecked()
            channels = self.pulse_sequence_table.cellWidget(row, 4).selected_channels()
            reps = self.pulse_sequence_table.cellWidget(row, 5).value()
            start_after_step = self.pulse_sequence_table.cellWidget(row, 6).value()
            iq_phase = self.pulse_sequence_table.cellWidget(row, 7).value()

            if pulse_var or idle_var:
                sequence.append({
                    # inline block - no named pulse block or increments, matches PulseCompiler's "Pulses" format
                    "block": ["Variable Pulses", [pulse_time,'tau'][pulse_var], [idle_time,'tau'][idle_var], 0, 0],
                    "channels": channels,
                    "repetitions": reps,
                    "Send Trig": row + 1, # each step's own step number, used as the trigger target for later steps
                    "Receive Trig": start_after_step,
                    "IQ Phase": iq_phase
                })
            else:
                sequence.append({
                    # inline block - no named pulse block or increments, matches PulseCompiler's "Pulses" format
                    "block": ["Pulses", pulse_time, idle_time, 0, 0],
                    "channels": channels,
                    "repetitions": reps,
                    "Send Trig": row + 1, # each step's own step number, used as the trigger target for later steps
                    "Receive Trig": start_after_step,
                    "IQ Phase": iq_phase
                })

        return sequence
    
    def write_pulse_sequence(self):
        """ Compiles and uploads the sequence currently displayed in the Pulse Sequencer table """
        sequence = self.get_pulse_sequence()
        sample_rate = self.pulse_sequence_sample_rate.value()

        # Match the AWG's sample clock to the requested rate so the compiled bin size lines up with the hardware
        self._logic.set_sample_rate(sample_rate)

        compiler = PulseCompiler(sequence, {}, self._logic, sample_rate=sample_rate)
        waveforms = compiler.compile()

        self._logic.load_waveform_set(waveforms)

        self._logic.update_pulses_and_sequences(sequence, {})

        #self.clear_pulse_sequence_dirty()

    def save_pulse_sequence(self):
        """ Saves the sequence currently displayed in the Pulse Sequencer table to disk """
        sequence_name = self.new_pulse_sequence_name.text()

        if sequence_name == self.NEW_SEQUENCE_LABEL:
            self.update_status(f'"{self.NEW_SEQUENCE_LABEL}" is reserved and cannot be overwritten - choose another name')
            return

        sequence = self.get_pulse_sequence()

        self.pulse_sequences[sequence_name] = {
            "steps": sequence,
            "sample_rate": self.pulse_sequence_sample_rate.value()
        }

        self._refresh_pulse_sequence_combo(select_name=sequence_name)

        try:
            with open(f"{self.save_filepath}\\PulseSequences.json", "w") as f:
                json.dump(self.pulse_sequences, f)
        except OSError as e:
            print(f"Error saving pulse sequences: {e}")

        self.clear_pulse_sequence_dirty()

    def delete_pulse_sequence(self):
        """ Removes the currently selected saved sequence from disk and the dropdown """
        sequence_name = self.pulse_sequence_select.currentText()

        if sequence_name == self.NEW_SEQUENCE_LABEL:
            self.update_status(f'"{self.NEW_SEQUENCE_LABEL}" is reserved and cannot be deleted')
            return

        if sequence_name not in self.pulse_sequences:
            return

        del self.pulse_sequences[sequence_name]

        self._refresh_pulse_sequence_combo()

        try:
            with open(f"{self.save_filepath}\\PulseSequences.json", "w") as f:
                json.dump(self.pulse_sequences, f)
        except OSError as e:
            print(f"Error saving pulse sequences: {e}")

    def load_pulse_sequence(self):
        """ Loads the selected saved sequence into the Pulse Sequencer table """
        selected_sequence = self.pulse_sequence_select.currentText()

        if selected_sequence == self.NEW_SEQUENCE_LABEL:
            sequence = []
            sample_rate = self._logic.awg().get_sample_rate()
            self.new_pulse_sequence_name.setText('')
        elif selected_sequence in self.pulse_sequences:
            saved_entry = self.pulse_sequences[selected_sequence]
            # older saved files stored a bare list of steps with no sample rate attached
            if isinstance(saved_entry, dict):
                sequence = saved_entry["steps"]
                sample_rate = saved_entry.get("sample_rate", self.pulse_sequence_sample_rate.value())
            else:
                sequence = saved_entry
                sample_rate = self.pulse_sequence_sample_rate.value()
            self.new_pulse_sequence_name.setText(selected_sequence)
        else:
            return

        self.pulse_sequence_sample_rate.setValue(sample_rate)

        self.rebuild_pulse_sequence_table(sequence)

        # rebuilding the table triggers dirty signals; the freshly loaded sequence is clean
        self.clear_pulse_sequence_dirty()

    def _refresh_pulse_sequence_combo(self, select_name=None):
        """ Repopulates the sequence dropdown, keeping the permanent 'New Sequence' entry first """
        self.pulse_sequence_select.clear()
        self.pulse_sequence_select.addItems([self.NEW_SEQUENCE_LABEL] + list(self.pulse_sequences.keys()))
        if select_name is not None:
            self.pulse_sequence_select.setCurrentText(select_name)

    def mark_pulse_sequence_dirty(self, *_args):
        """ Flags the displayed pulse sequence as having unsaved changes """
        self._pulse_sequence_dirty = True
        self.pulse_sequence_modified_label.setText('*')

    def clear_pulse_sequence_dirty(self):
        """ Flags the displayed pulse sequence as matching the last written/saved/loaded state """
        self._pulse_sequence_dirty = False
        self.pulse_sequence_modified_label.setText('')

    def _connect_pulse_sequence_row_dirty_signals(self, pulse_time, idle_time, channel_widget, reps, start_after_step, iq_phase):
        """ Marks the pulse sequence dirty whenever any widget in a table row changes """
        pulse_time.valueChanged.connect(self.mark_pulse_sequence_dirty)
        idle_time.valueChanged.connect(self.mark_pulse_sequence_dirty)
        reps.valueChanged.connect(self.mark_pulse_sequence_dirty)
        start_after_step.valueChanged.connect(self.mark_pulse_sequence_dirty)
        iq_phase.valueChanged.connect(self.mark_pulse_sequence_dirty)
        for checkbox in channel_widget.checkboxes.values():
            checkbox.toggled.connect(self.mark_pulse_sequence_dirty)

    def rebuild_pulse_sequence_table(self, sequence):
        """ Rebuilds the Pulse Sequencer table to match the given sequence """
        self.pulse_sequence_table.clear()
        self.pulse_sequence_table.setRowCount(0)

        self.pulse_sequence_table.setColumnCount(8)
        self.pulse_sequence_table.setHorizontalHeaderLabels([
            "Pulse\nTime", 
            "Pulse\nVar", 
            "Idle\nTime", 
            "Idle\nVar", 
            "Channels", 
            "Repetitions", 
            "Start\nAfter Step", 
            "IQ Phase"
        ])

        self.pulse_sequence_table.setColumnWidth(1,40)
        self.pulse_sequence_table.setColumnWidth(3,40)
        self.pulse_sequence_table.setColumnWidth(4,175)

        for step in sequence:
            block = step["block"]
            self.add_pulse_sequence_step()
            row = self.pulse_sequence_table.rowCount()-1

            if block[0]=='Pulses':
                self.pulse_sequence_table.cellWidget(row,0).setValue(block[1])
                self.pulse_sequence_table.cellWidget(row,1).setChecked(0)
                self.pulse_sequence_table.cellWidget(row,2).setValue(block[2])
                self.pulse_sequence_table.cellWidget(row,3).setChecked(0)
            elif block[0]=='Variable Pulses':
                if type(block[1]) is str:
                    self.pulse_sequence_table.cellWidget(row,0).setValue(0)
                    self.pulse_sequence_table.cellWidget(row,1).setChecked(True)
                else:
                    self.pulse_sequence_table.cellWidget(row,0).setValue(block[1])
                    self.pulse_sequence_table.cellWidget(row,1).setChecked(False)
                if type(block[2]) is str:
                    self.pulse_sequence_table.cellWidget(row,2).setValue(0)
                    self.pulse_sequence_table.cellWidget(row,3).setChecked(True)
                else:
                    self.pulse_sequence_table.cellWidget(row,2).setValue(block[2])
                    self.pulse_sequence_table.cellWidget(row,3).setChecked(False)
            self.pulse_sequence_table.cellWidget(row,4).set_channels(step["channels"])
            self.pulse_sequence_table.cellWidget(row,5).setValue(step["repetitions"])
            self.pulse_sequence_table.cellWidget(row,6).setValue(step["Receive Trig"])
            self.pulse_sequence_table.cellWidget(row,7).setValue(step["IQ Phase"])


            if False:
                row = self.pulse_sequence_table.rowCount()
                self.pulse_sequence_table.insertRow(row)

                

                pulse_time = ScienDSpinBox()
                pulse_time.setMinimum(0)
                pulse_time.setSuffix('s')
                pulse_time.setValue(block[1])
                self.pulse_sequence_table.setCellWidget(row, 0, pulse_time)

                idle_time = ScienDSpinBox()
                idle_time.setMinimum(0)
                idle_time.setSuffix('s')
                idle_time.setValue(block[2])
                self.pulse_sequence_table.setCellWidget(row, 2, idle_time)

                channel_widget = ChannelWidget(["IQ"] + self.available_channels)
                channel_widget.set_channels(step["channels"])
                self.pulse_sequence_table.setCellWidget(row, 4, channel_widget)

                reps = QSpinBox()
                reps.setRange(1, 10000)
                reps.setValue(step["repetitions"])
                self.pulse_sequence_table.setCellWidget(row, 5, reps)

                start_after_step = QSpinBox()
                start_after_step.setRange(0, 9999)
                start_after_step.setValue(step["Receive Trig"])
                self.pulse_sequence_table.setCellWidget(row, 6, start_after_step)

                iq_phase = QDoubleSpinBox()
                iq_phase.setRange(-360, 360)
                iq_phase.setValue(step["IQ Phase"])
                self.pulse_sequence_table.setCellWidget(row, 7, iq_phase)

                self.pulse_sequence_table.resizeRowToContents(row)

                self._connect_pulse_sequence_row_dirty_signals(
                    pulse_time, idle_time, channel_widget, reps, start_after_step, iq_phase
                )

    def _load_rfcontrol(self, checked=False):
        if self._microwave.is_connected:
            self._rf_control_window.show()

    def _rf_control_send(self,frequency=None,power=None,modulation=None,rfEnable=None):
        if not self._microwave.is_connected:
            self.log.warning("RF Control called but microwave module not connected, ignoring")
            return
        if frequency is not None:
            try:
                self._microwave().cw_frequency = frequency
            except RuntimeError as e:
                self.log.warning(e)
        if power is not None:
            try:
                self._microwave().cw_power = power
            except RuntimeError as e:
                self.log.warning(e)
        if modulation is not None:
            try:
                if modulation:
                    self._microwave().set_pulsed()
                else:
                    self._microwave().set_cw()
            except RuntimeError as e:
                self.log.warning(e)
        if rfEnable is not None:
            try:
                if rfEnable:
                    self._microwave().cw_on()
                else:
                    self._microwave().cw_off()
            except RuntimeError as e:
                self.log.warning(e)

    def _rf_control_update(self):
        if not self._microwave.is_connected:
            self.log.warning("RF Control called but microwave module not connected, ignoring")
            return
        self._rf_control_frequency.blockSignals(True)
        self._rf_control_power.blockSignals(True)
        self._rf_control_modEnable.blockSignals(True)
        self._rf_control_rfEnable.blockSignals(True)

        self._rf_control_frequency.setValue(self._microwave().cw_frequency)
        self._rf_control_power.setValue(self._microwave().cw_power)
        self._rf_control_modEnable.setChecked(self._microwave().modulation_active)
        self._rf_control_rfEnable.setChecked(self._microwave().output_active)

        self._rf_control_frequency.blockSignals(False)
        self._rf_control_power.blockSignals(False)
        self._rf_control_modEnable.blockSignals(False)
        self._rf_control_rfEnable.blockSignals(False)

    def _rf_control_check_for_lock(self):
        if not self._microwave.is_connected:
            return
        if self._microwave().module_state() != 'idle':
            self._rf_control_frequency.setDisabled(True)
            self._rf_control_power.setDisabled(True)
            self._rf_control_modEnable.setDisabled(True)
        else:
            self._rf_control_frequency.setDisabled(False)
            self._rf_control_power.setDisabled(False)
            self._rf_control_modEnable.setDisabled(False)


            

class ChannelWidget(QWidget):
    """ Channel Widget records the channels splitting the GUI into digital and analog """

    def __init__(self, channels, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(3)

        analog_layout = QHBoxLayout()
        digital_layout = QHBoxLayout()

        analog_layout.addWidget(QLabel("Analog:"))
        digital_layout.addWidget(QLabel("Digital:"))

        self.checkboxes = {}

        for channel in channels:

            cb = QCheckBox(channel.split("_")[-1])  # displays ch0, ch1...

            self.checkboxes[channel] = cb

            if channel.startswith("a_") or channel=="IQ":
                analog_layout.addWidget(cb)

            elif channel.startswith("d_"):
                digital_layout.addWidget(cb)

        analog_layout.addStretch()
        digital_layout.addStretch()

        main_layout.addLayout(analog_layout)
        main_layout.addLayout(digital_layout)

        self.setStyleSheet("""
            QCheckBox {
                spacing: 3px;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 12px;
                height: 12px;
            }
            QLabel {
                font-size: 12px;
                font-weight: bold;
            }
        """)

    def selected_channels(self):
        return [
            name
            for name, cb in self.checkboxes.items()
            if cb.isChecked()
        ]

    def set_channels(self, channels):

        for name, cb in self.checkboxes.items():
            cb.setChecked(name in channels)



