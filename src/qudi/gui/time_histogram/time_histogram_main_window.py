# -*- coding: utf-8 -*-
"""
Main window and control dock widget for TimeHistogramGui.

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

__all__ = ('TimeHistogramMainWindow', 'TimeHistogramControlDockWidget')

import os
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets, QtGui

from qudi.util.paths import get_artwork_dir
from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
from qudi.util.colordefs import QudiPalettePale as palette

_NS_PER_S = 1e9  # GUI displays timing values in seconds (SI-prefixed); logic/hardware use ns ints


class TimeHistogramControlDockWidget(AdvancedDockWidget):
    """
    Dock widget exposing hardware/acquisition settings for TimeHistLogic.

    Signals
    -------
    sigActiveChannelsChanged(list)
    sigSampleRateChanged(str)
    sigSamplingTimeChanged(int)
    sigDownsampleChanged(int)
    sigBufferSizeChanged(int)
    sigClearData()
    """

    sigActiveChannelsChanged = QtCore.Signal(list)
    sigSampleRateChanged = QtCore.Signal(str)
    sigSamplingTimeChanged = QtCore.Signal(int)
    sigDownsampleChanged = QtCore.Signal(int)
    sigBufferSizeChanged = QtCore.Signal(int)
    sigClearData = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__('Histogram Control', *args, **kwargs)
        self.setObjectName('TimeHistogram_ControlDock')

        main_widget = QtWidgets.QWidget()
        main_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        main_widget.setLayout(layout)
        self.setWidget(main_widget)

        # ── Channel selection ─────────────────────────────────────────────────
        layout.addWidget(QtWidgets.QLabel('Active Channels:'))
        self.channel_list_widget = QtWidgets.QListWidget()
        self.channel_list_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self.channel_list_widget.setMaximumHeight(120)
        layout.addWidget(self.channel_list_widget)
        self._channel_checkboxes = {}

        # ── Settings form ─────────────────────────────────────────────────────
        form = QtWidgets.QFormLayout()
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(8)
        layout.addLayout(form)

        self.sample_rate_combo = QtWidgets.QComboBox()
        self.sample_rate_combo.addItems(['100MHz', '20MHz', '100kHz'])
        self.sample_rate_combo.setToolTip('Internal clock timebase used for histogram binning')
        form.addRow('Sample Rate:', self.sample_rate_combo)

        self.sampling_time_spinbox = ScienDSpinBox()
        self.sampling_time_spinbox.setDecimals(3)
        self.sampling_time_spinbox.setSuffix('s')
        self.sampling_time_spinbox.setMinimum(1 / _NS_PER_S)
        self.sampling_time_spinbox.setValue(10_000 / _NS_PER_S)
        self.sampling_time_spinbox.setToolTip(
            'Duration after the trigger over which the histogram is recorded'
        )
        form.addRow('Sampling Time:', self.sampling_time_spinbox)

        self.downsample_spinbox = QtWidgets.QSpinBox()
        self.downsample_spinbox.setMinimum(1)
        self.downsample_spinbox.setMaximum(1_000_000)
        self.downsample_spinbox.setValue(1)
        self.downsample_spinbox.setToolTip('Number of clock ticks combined into a single histogram bin')
        form.addRow('Downsample:', self.downsample_spinbox)

        self.buffer_size_spinbox = QtWidgets.QSpinBox()
        self.buffer_size_spinbox.setMinimum(1)
        self.buffer_size_spinbox.setMaximum(2_000_000_000)
        self.buffer_size_spinbox.setValue(1_000_000)
        self.buffer_size_spinbox.setToolTip(
            'Local read buffer size, needs to be much greater than event_rate * sampling_time'
        )
        form.addRow('Buffer Size:', self.buffer_size_spinbox)

        self.clear_data_button = QtWidgets.QPushButton('Clear Data')
        self.clear_data_button.setToolTip('Zero the accumulated histogram counts')
        layout.addWidget(self.clear_data_button)

        layout.addStretch()

        # ── Internal signal wiring ────────────────────────────────────────────
        self.sample_rate_combo.currentTextChanged.connect(self.sigSampleRateChanged)
        self.sampling_time_spinbox.editingFinished.connect(
            lambda: self.sigSamplingTimeChanged.emit(
                round(self.sampling_time_spinbox.value() * _NS_PER_S)
            )
        )
        self.downsample_spinbox.editingFinished.connect(
            lambda: self.sigDownsampleChanged.emit(self.downsample_spinbox.value())
        )
        self.buffer_size_spinbox.editingFinished.connect(
            lambda: self.sigBufferSizeChanged.emit(self.buffer_size_spinbox.value())
        )
        self.clear_data_button.clicked.connect(self.sigClearData)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_available_channels(self, available_channels, active_channels):
        """ (Re-)populate the channel checkbox list. """
        self.channel_list_widget.clear()
        self._channel_checkboxes.clear()
        for channel in available_channels:
            item = QtWidgets.QListWidgetItem(self.channel_list_widget)
            checkbox = QtWidgets.QCheckBox(channel)
            checkbox.setChecked(channel in active_channels)
            checkbox.toggled.connect(self._emit_active_channels)
            self.channel_list_widget.setItemWidget(item, checkbox)
            self._channel_checkboxes[channel] = checkbox

    def _emit_active_channels(self):
        channels = [ch for ch, cb in self._channel_checkboxes.items() if cb.isChecked()]
        self.sigActiveChannelsChanged.emit(channels)

    def set_settings(self, settings):
        """ Update displayed settings without emitting change signals. """
        if 'sample_rate' in settings:
            self.sample_rate_combo.blockSignals(True)
            self.sample_rate_combo.setCurrentText(str(settings['sample_rate']))
            self.sample_rate_combo.blockSignals(False)
        if 'sampling_time_ns' in settings:
            self.sampling_time_spinbox.blockSignals(True)
            self.sampling_time_spinbox.setValue(settings['sampling_time_ns'] / _NS_PER_S)
            self.sampling_time_spinbox.blockSignals(False)
        if 'downsample' in settings:
            self.downsample_spinbox.blockSignals(True)
            self.downsample_spinbox.setValue(settings['downsample'])
            self.downsample_spinbox.blockSignals(False)
        if 'buffer_size' in settings:
            self.buffer_size_spinbox.blockSignals(True)
            self.buffer_size_spinbox.setValue(settings['buffer_size'])
            self.buffer_size_spinbox.blockSignals(False)

    def set_enabled(self, enabled):
        self.channel_list_widget.setEnabled(enabled)
        self.sample_rate_combo.setEnabled(enabled)
        self.sampling_time_spinbox.setEnabled(enabled)
        self.downsample_spinbox.setEnabled(enabled)
        self.buffer_size_spinbox.setEnabled(enabled)


class TimeHistogramMainWindow(QtWidgets.QMainWindow):
    """
    Main window for the Time Histogram GUI.

    Layout
    ------
    - Central widget : live multi-channel histogram plot (pyqtgraph)
    - Left dock      : TimeHistogramControlDockWidget (acquisition settings)
    - Top toolbar    : Start/Stop toggle, Save + nametag field
    """

    _CHANNEL_COLORS = (palette.c1, palette.c2, palette.c3, palette.c4, palette.c5, palette.c6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('qudi: Time Histogram')
        self.setDockNestingEnabled(True)

        icon_path = os.path.join(get_artwork_dir(), 'icons')

        # ── Central plot widget ───────────────────────────────────────────────
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setLabel('left', 'Counts')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        self.plot_widget.addLegend()
        self.setCentralWidget(self.plot_widget)

        self._curves = {}

        # ── Control dock widget ───────────────────────────────────────────────
        self.control_dockwidget = TimeHistogramControlDockWidget(parent=self)

        # ── Actions ───────────────────────────────────────────────────────────
        icon = QtGui.QIcon(os.path.join(icon_path, 'start-counter'))
        icon.addFile(
            os.path.join(icon_path, 'stop-counter'),
            state=QtGui.QIcon.State.On,
        )
        self.action_toggle_acquisition = QtGui.QAction('Start Acquisition', parent=self)
        self.action_toggle_acquisition.setCheckable(True)
        self.action_toggle_acquisition.setIcon(icon)
        self.action_toggle_acquisition.setToolTip('Start / Stop histogram acquisition')

        icon = QtGui.QIcon(os.path.join(icon_path, 'document-save'))
        self.action_save = QtGui.QAction('Save Data', parent=self)
        self.action_save.setIcon(icon)
        self.action_save.setToolTip(
            'Save the current histogram data.\n'
            'Use the text field to specify an optional nametag.'
        )

        icon = QtGui.QIcon(os.path.join(icon_path, 'application-exit'))
        self.action_close = QtGui.QAction('Close', parent=self)
        self.action_close.setIcon(icon)

        self.action_show_controls = QtGui.QAction('Show Histogram Controls', parent=self)
        self.action_show_controls.setCheckable(True)
        self.action_show_controls.setChecked(True)
        self.action_show_controls.setToolTip('Show / hide the control panel')

        self.action_restore_view = QtGui.QAction('Restore Default View', parent=self)
        self.action_restore_view.setToolTip('Reset dock layout to default positions')

        # ── Save nametag field ────────────────────────────────────────────────
        self.save_nametag_lineedit = QtWidgets.QLineEdit()
        self.save_nametag_lineedit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.save_nametag_lineedit.setPlaceholderText('nametag (optional)…')
        self.save_nametag_lineedit.setToolTip('Optional nametag appended to the saved file name')

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QtWidgets.QToolBar('Time Histogram Toolbar')
        toolbar.setObjectName('TimeHistogram_Toolbar')
        toolbar.addAction(self.action_toggle_acquisition)
        toolbar.addSeparator()
        toolbar.addAction(self.action_save)
        toolbar.addWidget(self.save_nametag_lineedit)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)

        # ── Menu bar ──────────────────────────────────────────────────────────
        menu_bar = QtWidgets.QMenuBar()
        menu = menu_bar.addMenu('File')
        menu.addAction(self.action_save)
        menu.addSeparator()
        menu.addAction(self.action_close)
        menu = menu_bar.addMenu('View')
        menu.addAction(self.action_show_controls)
        menu.addSeparator()
        menu.addAction(self.action_restore_view)
        self.setMenuBar(menu_bar)

        # ── Internal wiring ───────────────────────────────────────────────────
        self.action_close.triggered.connect(self.close)
        self.action_show_controls.triggered[bool].connect(self.control_dockwidget.setVisible)
        self.control_dockwidget.sigClosed.connect(
            lambda: self.action_show_controls.setChecked(False)
        )
        self.action_restore_view.triggered.connect(self.restore_default_view)

        self.restore_default_view()

    def restore_default_view(self):
        """Reset dock widget to its default position."""
        self.control_dockwidget.setFloating(False)
        self.control_dockwidget.setVisible(True)
        self.action_show_controls.setChecked(True)
        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea,
            self.control_dockwidget,
        )

    def set_channels(self, channels):
        """ Create/replace one plot curve per active histogram channel. """
        for curve in self._curves.values():
            self.plot_widget.removeItem(curve)
        self._curves.clear()
        for i, channel in enumerate(channels):
            pen = pg.mkPen(self._CHANNEL_COLORS[i % len(self._CHANNEL_COLORS)], width=2)
            self._curves[channel] = self.plot_widget.plot(
                name=channel, pen=pen, stepMode='center'
            )

    def update_data(self, data):
        """ Update the histogram curves from a ``{channel: (edges, counts)}`` mapping (edges in ns). """
        for channel, (edges, counts) in data.items():
            curve = self._curves.get(channel)
            if curve is None:
                continue
            # stepMode='right' requires len(edges) == len(counts) + 1
            n = min(len(counts), max(0, len(edges) - 1))
            curve.setData(edges[:n + 1] / _NS_PER_S, counts[:n])
