# -*- coding: utf-8 -*-
"""
Main window for SimpleScanGui.

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

__all__ = ('SimpleScanMainWindow',)

import os
import importlib
from PySide6 import QtCore, QtWidgets, QtGui

from qudi.util.paths import get_artwork_dir
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox

if True:
    try:
        importlib.reload(simple_scan_plot_widget)
    except NameError:
        import qudi.gui.simple_scan_gui.simple_scan_plot_widget as simple_scan_plot_widget

    try:
        importlib.reload(simple_scan_control_dockwidget)
    except NameError:
        import qudi.gui.simple_scan_gui.simple_scan_control_dockwidget as simple_scan_control_dockwidget


class SimpleScanMainWindow(QtWidgets.QMainWindow):
    """
    Main window for the Simple Scan GUI.

    Layout
    ------
    - Central widget : SimpleScanPlotWidget (1-D average + 2-D image)
    - Left dock      : SimpleScanControlDockWidget (scan parameters)
    - Top toolbar    : Start/Stop toggle, Continue, Save + nametag field
    - Status bar     : Completed scan lines counter
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('qudi: Simple Scan')
        self.setDockNestingEnabled(True)

        icon_path = os.path.join(get_artwork_dir(), 'icons')

        # ── Central plot widget ───────────────────────────────────────────────
        self.plot_widget = simple_scan_plot_widget.SimpleScanPlotWidget()
        self.setCentralWidget(self.plot_widget)

        # ── Control dock widget ───────────────────────────────────────────────
        self.control_dockwidget = (
            simple_scan_control_dockwidget.SimpleScanControlDockWidget(parent=self)
        )

        # ── Status bar ────────────────────────────────────────────────────────
        self.setStatusBar(_SimpleScanStatusBar())

        # ── Actions ───────────────────────────────────────────────────────────
        icon = QtGui.QIcon(os.path.join(icon_path, 'start-counter'))
        icon.addFile(
            os.path.join(icon_path, 'stop-counter'),
            state=QtGui.QIcon.State.On,
        )
        self.action_toggle_scan = QtGui.QAction('Start Scan', parent=self)
        self.action_toggle_scan.setCheckable(True)
        self.action_toggle_scan.setIcon(icon)
        self.action_toggle_scan.setToolTip('Start / Stop scan')

        icon = QtGui.QIcon(os.path.join(icon_path, 'restart-counter'))
        self.action_continue_scan = QtGui.QAction('Continue Scan', parent=self)
        self.action_continue_scan.setIcon(icon)
        self.action_continue_scan.setToolTip(
            'Resume a scan that was stopped before completion'
        )
        self.action_continue_scan.setEnabled(False)

        icon = QtGui.QIcon(os.path.join(icon_path, 'document-save'))
        self.action_save = QtGui.QAction('Save Data', parent=self)
        self.action_save.setIcon(icon)
        self.action_save.setToolTip(
            'Save current scan data.\n'
            'Use the text field to specify an optional nametag.'
        )

        icon = QtGui.QIcon(os.path.join(icon_path, 'application-exit'))
        self.action_close = QtGui.QAction('Close', parent=self)
        self.action_close.setIcon(icon)

        self.action_show_controls = QtGui.QAction('Show Scan Controls', parent=self)
        self.action_show_controls.setCheckable(True)
        self.action_show_controls.setChecked(True)
        self.action_show_controls.setToolTip('Show / hide scan control panel')

        self.action_restore_view = QtGui.QAction('Restore Default View', parent=self)
        self.action_restore_view.setToolTip('Reset dock layout to default positions')

        # ── Save nametag field ────────────────────────────────────────────────
        self.save_nametag_lineedit = QtWidgets.QLineEdit()
        self.save_nametag_lineedit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.save_nametag_lineedit.setMinimumWidth(
            QtGui.QFontMetrics(ScienDSpinBox().font()).width(40 * ' ')
        )
        self.save_nametag_lineedit.setPlaceholderText('nametag (optional)…')
        self.save_nametag_lineedit.setToolTip('Optional nametag appended to the saved file name')

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QtWidgets.QToolBar('Simple Scan Toolbar')
        toolbar.setObjectName('SimpleScan_Toolbar')
        toolbar.addAction(self.action_toggle_scan)
        toolbar.addAction(self.action_continue_scan)
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


class _SimpleScanStatusBar(QtWidgets.QStatusBar):
    """Status bar showing the number of completed scan lines."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet('QStatusBar::item { border: 0px }')

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)
        layout.addStretch(1)

        layout.addWidget(QtWidgets.QLabel('Completed Lines:'))
        self.lines_spinbox = QtWidgets.QSpinBox()
        self.lines_spinbox.setMinimum(-1)
        self.lines_spinbox.setSpecialValueText('N/A')
        self.lines_spinbox.setValue(-1)
        self.lines_spinbox.setReadOnly(True)
        self.lines_spinbox.setButtonSymbols(
            QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.lines_spinbox.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.lines_spinbox)

        self.addPermanentWidget(widget, 1)

    def set_completed_lines(self, value):
        self.lines_spinbox.setValue(int(value))
