# -*- coding: utf-8 -*-
"""
GUI module for controlling TimeHistLogic.

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

__all__ = ['TimeHistogramGui']

from PySide6 import QtCore

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.logic.time_hist_logic import TimeHistLogic
from qudi.gui.time_histogram.time_histogram_main_window import TimeHistogramMainWindow


class TimeHistogramGui(GuiBase):
    """
    GUI module for controlling TimeHistLogic, plotting live pulse-timing histograms.

    example config for copy-paste:

    time_histogram_gui:
        module.Class: 'time_histogram.time_histogram_gui.TimeHistogramGui'
        connect:
            time_hist_logic: 'time_hist_logic'
    """

    # Connector
    _time_hist_logic = Connector(name='time_hist_logic', interface=TimeHistLogic)

    # GUI-internal signals (connected to logic with QueuedConnection for thread safety)
    _sigStartAcquisition = QtCore.Signal()
    _sigStopAcquisition = QtCore.Signal()
    _sigClearData = QtCore.Signal()
    _sigSaveData = QtCore.Signal(str)
    _sigActiveChannelsChanged = QtCore.Signal(list)
    _sigSampleRateChanged = QtCore.Signal(str)
    _sigSamplingTimeChanged = QtCore.Signal(int)
    _sigDownsampleChanged = QtCore.Signal(int)
    _sigBufferSizeChanged = QtCore.Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_activate(self):
        """Build and show the main window; connect all signals."""
        self._mw = TimeHistogramMainWindow()

        logic = self._time_hist_logic()

        available_channels = logic.available_channels
        active_channels = logic.active_channels
        self._mw.control_dockwidget.set_available_channels(available_channels, active_channels)
        self._mw.set_channels(active_channels)

        self._mw.control_dockwidget.set_settings({
            'sample_rate': logic.sample_rate,
            'sampling_time_ns': logic.sampling_time_ns,
            'downsample': logic.downsample,
            'buffer_size': logic.buffer_size,
        })

        self.__connect_gui_signals()
        self.__connect_control_signals()
        self.__connect_logic_signals()

        self._update_acquisition_state(logic.acquisition_running)

        self._mw.restore_default_view()
        self.show()

    def on_deactivate(self):
        """Disconnect all signals and close the window."""
        self.__disconnect_gui_signals()
        self.__disconnect_control_signals()
        self.__disconnect_logic_signals()
        self._save_window_geometry(self._mw)
        self._mw.close()

    def show(self):
        """Raise and show the main window."""
        self._restore_window_geometry(self._mw)
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def restore_default_view(self):
        self._mw.restore_default_view()

    # ── Signal wiring helpers ─────────────────────────────────────────────────

    def __connect_gui_signals(self):
        logic = self._time_hist_logic()
        self._sigStartAcquisition.connect(
            logic.start_acquisition, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigStopAcquisition.connect(
            logic.stop_acquisition, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigClearData.connect(
            logic.clear_data, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigSaveData.connect(
            logic.save_data, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigActiveChannelsChanged.connect(
            logic.set_active_channels, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigSampleRateChanged.connect(
            logic.set_sample_rate, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigSamplingTimeChanged.connect(
            logic.set_sampling_time_ns, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigDownsampleChanged.connect(
            logic.set_downsample, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigBufferSizeChanged.connect(
            logic.set_buffer_size, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def __disconnect_gui_signals(self):
        logic = self._time_hist_logic()
        self._sigStartAcquisition.disconnect(logic.start_acquisition)
        self._sigStopAcquisition.disconnect(logic.stop_acquisition)
        self._sigClearData.disconnect(logic.clear_data)
        self._sigSaveData.disconnect(logic.save_data)
        self._sigActiveChannelsChanged.disconnect(logic.set_active_channels)
        self._sigSampleRateChanged.disconnect(logic.set_sample_rate)
        self._sigSamplingTimeChanged.disconnect(logic.set_sampling_time_ns)
        self._sigDownsampleChanged.disconnect(logic.set_downsample)
        self._sigBufferSizeChanged.disconnect(logic.set_buffer_size)

    def __connect_control_signals(self):
        self._mw.action_toggle_acquisition.triggered[bool].connect(self._toggle_acquisition_clicked)
        self._mw.action_save.triggered.connect(self._save_clicked)
        self._mw.action_restore_view.triggered.connect(self.restore_default_view)

        dw = self._mw.control_dockwidget
        dw.sigActiveChannelsChanged.connect(
            self._active_channels_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigSampleRateChanged.connect(
            self._sample_rate_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigSamplingTimeChanged.connect(
            self._sampling_time_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigDownsampleChanged.connect(
            self._downsample_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigBufferSizeChanged.connect(
            self._buffer_size_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigClearData.connect(
            self._clear_data_clicked, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def __disconnect_control_signals(self):
        self._mw.action_toggle_acquisition.triggered[bool].disconnect(self._toggle_acquisition_clicked)
        self._mw.action_save.triggered.disconnect(self._save_clicked)
        self._mw.action_restore_view.triggered.disconnect(self.restore_default_view)

        dw = self._mw.control_dockwidget
        dw.sigActiveChannelsChanged.disconnect(self._active_channels_changed)
        dw.sigSampleRateChanged.disconnect(self._sample_rate_changed)
        dw.sigSamplingTimeChanged.disconnect(self._sampling_time_changed)
        dw.sigDownsampleChanged.disconnect(self._downsample_changed)
        dw.sigBufferSizeChanged.disconnect(self._buffer_size_changed)
        dw.sigClearData.disconnect(self._clear_data_clicked)

    def __connect_logic_signals(self):
        logic = self._time_hist_logic()
        logic.sigAcquisitionStateChanged.connect(
            self._update_acquisition_state, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigDataAvailable.connect(
            self._update_data, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigSettingsUpdated.connect(
            self._update_settings, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def __disconnect_logic_signals(self):
        logic = self._time_hist_logic()
        logic.sigAcquisitionStateChanged.disconnect(self._update_acquisition_state)
        logic.sigDataAvailable.disconnect(self._update_data)
        logic.sigSettingsUpdated.disconnect(self._update_settings)

    # ── Toolbar / control slots ──────────────────────────────────────────────

    @QtCore.Slot(bool)
    def _toggle_acquisition_clicked(self, is_checked):
        """Start or stop acquisition depending on the toggle state."""
        if is_checked:
            self._mw.action_toggle_acquisition.setEnabled(False)
            self._mw.control_dockwidget.set_enabled(False)
            self._sigStartAcquisition.emit()
        else:
            self._sigStopAcquisition.emit()

    @QtCore.Slot()
    def _save_clicked(self):
        tag = self._mw.save_nametag_lineedit.text().strip() or None
        self._sigSaveData.emit(tag if tag is not None else '')

    @QtCore.Slot()
    def _clear_data_clicked(self):
        self._sigClearData.emit()

    @QtCore.Slot(list)
    def _active_channels_changed(self, channels):
        self._sigActiveChannelsChanged.emit(channels)
        self._mw.set_channels(channels)

    @QtCore.Slot(str)
    def _sample_rate_changed(self, value):
        self._sigSampleRateChanged.emit(value)

    @QtCore.Slot(int)
    def _sampling_time_changed(self, value):
        self._sigSamplingTimeChanged.emit(value)

    @QtCore.Slot(int)
    def _downsample_changed(self, value):
        self._sigDownsampleChanged.emit(value)

    @QtCore.Slot(int)
    def _buffer_size_changed(self, value):
        self._sigBufferSizeChanged.emit(value)

    # ── Logic → GUI update slots ──────────────────────────────────────────────

    @QtCore.Slot(bool)
    def _update_acquisition_state(self, is_running):
        """Reflect the current running/stopped state in the GUI."""
        self._mw.action_toggle_acquisition.blockSignals(True)
        self._mw.action_toggle_acquisition.setChecked(is_running)
        self._mw.action_toggle_acquisition.setText(
            'Stop Acquisition' if is_running else 'Start Acquisition'
        )
        self._mw.action_toggle_acquisition.setEnabled(True)
        self._mw.action_toggle_acquisition.blockSignals(False)

        self._mw.control_dockwidget.set_enabled(not is_running)

    @QtCore.Slot(object)
    def _update_data(self, data):
        """Refresh the live histogram plot from the current logic data."""
        self._mw.update_data(data)

    @QtCore.Slot(dict)
    def _update_settings(self, settings):
        """Reflect setting changes emitted by the logic."""
        self._mw.control_dockwidget.set_settings(settings)
        if 'active_channels' in settings:
            logic = self._time_hist_logic()
            self._mw.control_dockwidget.set_available_channels(
                logic.available_channels, settings['active_channels']
            )
            self._mw.set_channels(settings['active_channels'])
