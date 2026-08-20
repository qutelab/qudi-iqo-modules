# -*- coding: utf-8 -*-
"""
GUI module for controlling SimpleScanLogic.

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

__all__ = ['SimpleScanGui']

import importlib
import numpy as np
from PySide6 import QtCore

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.logic.simple_scan_logic import SimpleScanLogic

try:
    importlib.reload(simple_scan_main_window)
except NameError:
    import qudi.gui.simple_scan_gui.simple_scan_main_window as simple_scan_main_window


class SimpleScanGui(GuiBase):
    """
    GUI module for controlling SimpleScanLogic.

    Provides:
      - Device selection from ``logic.device_dict``
      - Scan parameter controls mirroring ``record_scan`` in script_builder.py
      - An interactive 1-D average plot and a 2-D raw scan image

    example config for copy-paste:

    simple_scan_gui:
        module.Class: 'simple_scan_gui.simple_scan_gui.SimpleScanGui'
        connect:
            simple_scan_logic: 'simple_scan_logic'
    """

    # Connector
    _simple_scan_logic = Connector(name='simple_scan_logic', interface=SimpleScanLogic)

    # GUI-internal signals (connected to logic with QueuedConnection for thread safety)
    _sigStartScan = QtCore.Signal()
    _sigStopScan = QtCore.Signal()
    _sigContinueScan = QtCore.Signal()
    _sigSaveData = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_activate(self):
        """Build and show the main window; connect all signals."""
        # Reload submodules so that hot-module-reload works in qudi
        try:
            importlib.reload(simple_scan_main_window)
            importlib.reload(SimpleScanLogic)
        except Exception:
            pass

        self._mw = simple_scan_main_window.SimpleScanMainWindow()

        logic = self._simple_scan_logic()

        # Populate device list
        self._mw.control_dockwidget.set_device_list(list(logic.device_dict.keys()))

        # Set device combo to current logic selection (block signals to avoid feedback)
        idx = self._mw.control_dockwidget.device_combo.findText(logic.scan_device)
        if idx >= 0:
            self._mw.control_dockwidget.device_combo.blockSignals(True)
            self._mw.control_dockwidget.device_combo.setCurrentIndex(idx)
            self._mw.control_dockwidget.device_combo.blockSignals(False)

        # Load current scan parameters from logic StatusVars
        self._mw.control_dockwidget.set_scan_parameters({
            'x_range':      logic.x_range,
            'time_per':     logic.time_per,
            'time_wait':    logic.time_wait,
            'number_scans': logic.number_scans,
            'shuffle_x':    logic.shuffle_x,
        })

        # Populate device-dependent widgets (static params + x-range label)
        self._update_device_dependent_widgets()

        self.__connect_gui_signals()
        self.__connect_control_signals()
        self.__connect_logic_signals()

        # Reflect current state (may already be running if re-activated mid-scan)
        self._update_scan_state(logic.module_state() == 'locked')

        self.restore_default_view()
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
        """Restore default dock layout."""
        self._mw.restore_default_view()

    # ── Signal wiring helpers ─────────────────────────────────────────────────

    def __connect_gui_signals(self):
        """Connect internal GUI signals to logic with QueuedConnection."""
        logic = self._simple_scan_logic()
        self._sigStartScan.connect(
            logic.start_scan, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigStopScan.connect(
            logic.stop_scan, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigContinueScan.connect(
            logic.continue_scan, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._sigSaveData.connect(
            logic.save_data, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def __disconnect_gui_signals(self):
        logic = self._simple_scan_logic()
        self._sigStartScan.disconnect(logic.start_scan)
        self._sigStopScan.disconnect(logic.stop_scan)
        self._sigContinueScan.disconnect(logic.continue_scan)
        self._sigSaveData.disconnect(logic.save_data)

    def __connect_control_signals(self):
        """Connect main window toolbar actions and dock widget parameter signals."""
        self._mw.action_toggle_scan.triggered[bool].connect(self._toggle_scan_clicked)
        self._mw.action_continue_scan.triggered.connect(self._continue_scan_clicked)
        self._mw.action_save.triggered.connect(self._save_clicked)
        self._mw.action_restore_view.triggered.connect(self.restore_default_view)

        dw = self._mw.control_dockwidget
        dw.sigDeviceChanged.connect(
            self._device_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigXRangeChanged.connect(
            self._x_range_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigTimePerChanged.connect(
            self._time_per_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigTimeWaitChanged.connect(
            self._time_wait_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigNumberScansChanged.connect(
            self._number_scans_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigShuffleXChanged.connect(
            self._shuffle_x_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        dw.sigStaticSetParamChanged.connect(
            self._static_set_param_changed, QtCore.Qt.ConnectionType.QueuedConnection
        )

        # Re-render plots when the user changes the channel or normalise selectors
        self._mw.plot_widget.x_channel_combo.currentIndexChanged.connect(
            lambda _: self._update_scan_data()
        )
        self._mw.plot_widget.y_channel_combo.currentIndexChanged.connect(
            lambda _: self._update_scan_data()
        )
        self._mw.plot_widget._normalize_checkbox.stateChanged.connect(
            lambda _: self._update_scan_data()
        )

    def __disconnect_control_signals(self):
        self._mw.action_toggle_scan.triggered[bool].disconnect(self._toggle_scan_clicked)
        self._mw.action_continue_scan.triggered.disconnect(self._continue_scan_clicked)
        self._mw.action_save.triggered.disconnect(self._save_clicked)
        self._mw.action_restore_view.triggered.disconnect(self.restore_default_view)

        dw = self._mw.control_dockwidget
        dw.sigDeviceChanged.disconnect(self._device_changed)
        dw.sigXRangeChanged.disconnect(self._x_range_changed)
        dw.sigTimePerChanged.disconnect(self._time_per_changed)
        dw.sigTimeWaitChanged.disconnect(self._time_wait_changed)
        dw.sigNumberScansChanged.disconnect(self._number_scans_changed)
        dw.sigShuffleXChanged.disconnect(self._shuffle_x_changed)
        dw.sigStaticSetParamChanged.disconnect(self._static_set_param_changed)

        self._mw.plot_widget.x_channel_combo.currentIndexChanged.disconnect()
        self._mw.plot_widget.y_channel_combo.currentIndexChanged.disconnect()
        self._mw.plot_widget._normalize_checkbox.stateChanged.disconnect()

    def __connect_logic_signals(self):
        logic = self._simple_scan_logic()
        logic.sigScanStateUpdated.connect(
            self._update_scan_state, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigScanParametersUpdated.connect(
            self._update_scan_parameters, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigScanDataUpdated.connect(
            self._update_scan_data, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigLineReady.connect(
            self._on_line_ready, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigDataPointReady.connect(
            self._on_data_point_ready, QtCore.Qt.ConnectionType.QueuedConnection
        )
        logic.sigScanComplete.connect(
            self._on_scan_complete, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def __disconnect_logic_signals(self):
        logic = self._simple_scan_logic()
        logic.sigScanStateUpdated.disconnect(self._update_scan_state)
        logic.sigScanParametersUpdated.disconnect(self._update_scan_parameters)
        logic.sigScanDataUpdated.disconnect(self._update_scan_data)
        logic.sigLineReady.disconnect(self._on_line_ready)
        logic.sigDataPointReady.disconnect(self._on_data_point_ready)
        logic.sigScanComplete.disconnect(self._on_scan_complete)

    # ── Toolbar slots ─────────────────────────────────────────────────────────

    @QtCore.Slot(bool)
    def _toggle_scan_clicked(self, is_checked):
        """Start or stop the scan depending on the toggle state."""
        if is_checked:
            # Disable controls immediately; logic will re-enable via sigScanStateUpdated
            self._mw.action_toggle_scan.setEnabled(False)
            self._mw.action_continue_scan.setEnabled(False)
            self._mw.control_dockwidget.set_enabled(False)
            self._sigStartScan.emit()
        else:
            self._sigStopScan.emit()

    @QtCore.Slot()
    def _continue_scan_clicked(self):
        """Continue a previously stopped scan."""
        self._mw.action_toggle_scan.setEnabled(False)
        self._mw.action_continue_scan.setEnabled(False)
        self._mw.control_dockwidget.set_enabled(False)
        self._sigContinueScan.emit()

    @QtCore.Slot()
    def _save_clicked(self):
        tag = self._mw.save_nametag_lineedit.text().strip() or None
        self._sigSaveData.emit(tag if tag is not None else '')

    # ── Logic → GUI update slots ──────────────────────────────────────────────

    @QtCore.Slot(bool)
    def _update_scan_state(self, is_running):
        """Reflect the current running/stopped state in the GUI."""
        self._mw.action_toggle_scan.blockSignals(True)
        self._mw.action_toggle_scan.setChecked(is_running)
        self._mw.action_toggle_scan.setText('Stop Scan' if is_running else 'Start Scan')
        self._mw.action_toggle_scan.setEnabled(True)
        self._mw.action_toggle_scan.blockSignals(False)

        self._mw.action_continue_scan.setEnabled(not is_running)
        self._mw.control_dockwidget.set_enabled(not is_running)

    @QtCore.Slot(dict)
    def _update_scan_parameters(self, params):
        """Reflect parameter changes emitted by the logic."""
        self._mw.control_dockwidget.set_scan_parameters(params)

    @QtCore.Slot()
    def _update_scan_data(self):
        """Refresh both plots from the current logic data arrays."""
        logic = self._simple_scan_logic()

        try:
            signal_data = logic.signal_data
        except (AttributeError, TypeError):
            signal_data = None

        try:
            raw_data = logic.raw_data
        except (AttributeError, TypeError):
            raw_data = None

        # Populate channel selectors once data labels are available
        try:
            labels = logic._data_labels
            units = logic._data_units
            self._mw.plot_widget.set_channel_labels(labels)
        except AttributeError:
            labels = None
            units = None

        # Determine axis label strings for the currently selected columns
        xi = self._mw.plot_widget.x_channel_index
        yi = self._mw.plot_widget.y_channel_index
        if labels and units and len(labels) > max(xi, yi):
            x_label, x_unit = labels[xi], units[xi]
            y_label, y_unit = labels[yi], units[yi]
        else:
            x_label, x_unit, y_label, y_unit = 'X', '', 'Signal', ''

        # Column 0 is always the independent variable shown on the 2-D image x-axis
        if labels and units and len(labels) > 0:
            x0_label, x0_unit = labels[0], units[0]
        else:
            x0_label, x0_unit = 'X', ''

        self._mw.plot_widget.set_data(
            signal_data, raw_data,
            x_extent=self._get_x_extent(),
            x_label=x_label, x_unit=x_unit,
            x0_label=x0_label, x0_unit=x0_unit,
            y_label=y_label, y_unit=y_unit,
        )

    def _get_x_extent(self):
        """Return (x_min, x_max) from the configured scan range, or None."""
        try:
            xr = self._simple_scan_logic().x_range
            return (float(xr[0]), float(xr[1]))
        except Exception:
            return None

    def _update_image_data(self):
        """Refresh only the 2-D image — called on every data-point ready."""
        logic = self._simple_scan_logic()
        try:
            raw_data = logic.raw_data
        except (AttributeError, TypeError):
            raw_data = None

        try:
            labels = logic._data_labels
            units = logic._data_units
        except AttributeError:
            labels = None
            units = None

        yi = self._mw.plot_widget.y_channel_index
        if labels and units and len(labels) > yi:
            y_label, y_unit = labels[yi], units[yi]
        else:
            y_label, y_unit = 'Signal', ''

        self._mw.plot_widget.update_image_data(
            raw_data,
            x_extent=self._get_x_extent(),
            y_label=y_label,
            y_unit=y_unit,
        )

    @QtCore.Slot(bool)
    def _on_line_ready(self, success):
        """Called after each completed scan line; update both plots and status bar."""
        if success:
            self._update_scan_data()
            try:
                self._mw.statusBar().set_completed_lines(
                    self._simple_scan_logic()._line_counter
                )
            except Exception:
                pass

    @QtCore.Slot(bool)
    def _on_data_point_ready(self, success):
        """Called after each individual data point; update the 2-D image only."""
        if success:
            self._update_image_data()

    @QtCore.Slot(bool)
    def _on_scan_complete(self, success):
        """Called when the full scan finishes; re-enable GUI controls."""
        self._update_scan_data()
        if success:
            self.log.info('Simple scan completed successfully.')
        else:
            self.log.info('Simple scan did not complete successfully.')

    # ── Parameter change slots (GUI → logic) ──────────────────────────────────

    def _update_device_dependent_widgets(self):
        """Refresh the static-set-parameter rows and x-range label for *device_name*."""
        logic = self._simple_scan_logic()
        device = logic.device_dict.get(logic.scan_device)
        if device is None:
            return

        self._mw.control_dockwidget.set_static_set_parameters(device._static_set_parameters)

        # Update x-range label from the device's first data label/unit
        if device._data_labels:
            label = device._data_labels[0]
        else:
            label = 'X'
        if device._data_units:
            unit = device._data_units[0]
        else:
            unit = ''
        self._mw.control_dockwidget.set_x_range_control(label, unit, logic.x_range)


    @QtCore.Slot(str)
    def _device_changed(self, device_name):
        if device_name:
            self._simple_scan_logic().scan_device = device_name
            self._update_device_dependent_widgets()

    @QtCore.Slot(str, object)
    def _static_set_param_changed(self, label, value):
        """Write the new value back into the logic's static_set_parameters dict."""
        logic = self._simple_scan_logic()
        device = logic.device_dict.get(logic.scan_device)
        if device is None or not device._static_set_parameters:
            return
        device.update_static_set_parameter_value(label,value)

    @QtCore.Slot(float, float, int)
    def _x_range_changed(self, start, end, steps):
        self._simple_scan_logic().x_range = (start, end, steps)

    @QtCore.Slot(float)
    def _time_per_changed(self, value):
        try:
            self._simple_scan_logic().time_per = value
        except AssertionError as exc:
            self.log.warning(f'Invalid time_per value: {exc}')

    @QtCore.Slot(float)
    def _time_wait_changed(self, value):
        try:
            self._simple_scan_logic().time_wait = value
        except AssertionError as exc:
            self.log.warning(f'Invalid time_wait value: {exc}')

    @QtCore.Slot(int)
    def _number_scans_changed(self, value):
        try:
            self._simple_scan_logic().number_scans = value
        except AssertionError as exc:
            self.log.warning(f'Invalid number_scans value: {exc}')

    @QtCore.Slot(bool)
    def _shuffle_x_changed(self, value):
        self._simple_scan_logic().shuffle_x = bool(value)
