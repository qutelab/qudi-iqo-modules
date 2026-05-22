# -*- coding: utf-8 -*-
"""
Plot widget for SimpleScanGui containing:
  - A 1-D interactive average plot (InteractivePlot)
  - A 2-D raw scan image (DataImageItem + ColorBarWidget)

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

__all__ = ('SimpleScanPlotWidget',)

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from qudi.util.widgets.plotting.plot_item import DataImageItem
from qudi.util.widgets.plotting.colorbar import ColorBarWidget
from qudi.util.interactivePlotAM import InteractivePlot


class SimpleScanPlotWidget(QtWidgets.QWidget):
    """
    Combined widget containing:
      - Channel X/Y axis selectors
      - An InteractivePlot showing averaged signal data
      - A 2-D image plot showing raw per-scan data with a colour bar
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)

        # ── Channel selector row ──────────────────────────────────────────────
        selector_layout = QtWidgets.QHBoxLayout()

        x_axis_label = QtWidgets.QLabel('X Axis:')
        x_axis_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        selector_layout.addWidget(x_axis_label)
        self.x_channel_combo = QtWidgets.QComboBox()
        self.x_channel_combo.setMinimumWidth(140)
        self.x_channel_combo.setToolTip('Column to use as the x-axis in the average plot')
        selector_layout.addWidget(self.x_channel_combo)

        selector_layout.addSpacing(16)

        y_axis_label = QtWidgets.QLabel('Y Axis:')
        y_axis_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        selector_layout.addWidget(y_axis_label)
        self.y_channel_combo = QtWidgets.QComboBox()
        self.y_channel_combo.setMinimumWidth(140)
        self.y_channel_combo.setToolTip('Data channel to display on both plots')
        selector_layout.addWidget(self.y_channel_combo)

        selector_layout.addSpacing(16)
        

        selector_layout.addStretch()
        main_layout.addLayout(selector_layout,0,0,1,2)

        # ── 1-D average (signal) plot ─────────────────────────────────────────
        self.average_plot = InteractivePlot()
        self.average_plot.setLabel('bottom', 'X')
        self.average_plot.setLabel('left', 'Signal')
        self.average_plot.showGrid(x=True, y=True, alpha=0.5)
        self.average_plot.setMinimumHeight(200)
        main_layout.addWidget(self.average_plot, 1,0)

        # ── 2-D raw scan image ────────────────────────────────────────────────

        self._image_widget = pg.PlotWidget()
        self._image_widget.getPlotItem().setContentsMargins(0, 1, 5, 2)
        self._image_item = DataImageItem()
        self._image_widget.addItem(self._image_item)
        self._image_widget.setMinimumWidth(100)
        self._image_widget.setMinimumHeight(150)
        self._image_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._image_widget.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._image_widget.setLabel('bottom', 'X')
        self._image_widget.setLabel('left', 'Scan Line')
        main_layout.addWidget(self._image_widget, 2,0)

        right_layout = QtWidgets.QVBoxLayout()

        right_layout.addStretch()
        self._colorbar = ColorBarWidget()
        self._colorbar.set_label(text='Signal', unit='')
        self._colorbar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        if self._colorbar.mode is ColorBarWidget.ColorBarMode.PERCENTILE:
            self._image_item.set_percentiles(self._colorbar.percentiles)
        else:
            self._image_item.set_percentiles(None)
        self._colorbar.sigModeChanged.connect(self._colorbar_mode_changed)
        self._colorbar.sigLimitsChanged.connect(self._colorbar_limits_changed)
        self._colorbar.sigPercentilesChanged.connect(self._colorbar_percentiles_changed)
        right_layout.addWidget(self._colorbar)

        self._normalize_checkbox = QtWidgets.QCheckBox('Line Normalize')
        self._normalize_checkbox.setToolTip(
            'Normalize each scan line of the 2-D image to its row mean.'
        )
        right_layout.addWidget(self._normalize_checkbox)

        main_layout.addLayout(right_layout, 1,1,2,1)

        # ── Align x-axes ──────────────────────────────────────────────────────
        # Fix the left-axis width to the same value on both plots so that the
        # actual data regions start at the same horizontal pixel position.
        _LEFT_AXIS_WIDTH = 60
        self.average_plot.getPlotItem().getAxis('left').setWidth(_LEFT_AXIS_WIDTH)
        self._image_widget.getPlotItem().getAxis('left').setWidth(_LEFT_AXIS_WIDTH)

        # Link x-axes only when the average plot is also showing the independent
        # variable (column 0); update whenever the x-channel selection changes.
        self.x_channel_combo.currentIndexChanged.connect(self._update_x_link)
        self._update_x_link()

        # Internal cache for re-rendering on colorbar setting changes
        self._last_image_data = None
        self._last_x_extent = (0.0, 1.0)
        # Track selected channels to detect when the selection changes
        self._prev_xi = -1
        self._prev_yi = -1

    # ── Channel population ────────────────────────────────────────────────────

    def set_channel_labels(self, labels):
        """
        Populate x/y channel combo boxes.

        Parameters
        ----------
        labels : list[str]
            Human-readable column labels, typically ``logic._data_labels``.
        """
        if not labels:
            return

        x_prev = self.x_channel_combo.currentText()
        y_prev = self.y_channel_combo.currentText()

        self.x_channel_combo.blockSignals(True)
        self.y_channel_combo.blockSignals(True)
        self.x_channel_combo.clear()
        self.y_channel_combo.clear()
        self.x_channel_combo.addItems(labels)
        self.y_channel_combo.addItems(labels)

        x_idx = self.x_channel_combo.findText(x_prev)
        self.x_channel_combo.setCurrentIndex(max(0, x_idx))

        y_idx = self.y_channel_combo.findText(y_prev)
        # Default Y to the last column (usually the primary scanner channel)
        self.y_channel_combo.setCurrentIndex(y_idx if y_idx >= 0 else len(labels) - 1)

        self.x_channel_combo.blockSignals(False)
        self.y_channel_combo.blockSignals(False)

    @property
    def x_channel_index(self):
        return max(0, self.x_channel_combo.currentIndex())

    @property
    def y_channel_index(self):
        return max(0, self.y_channel_combo.currentIndex())

    def _update_x_link(self):
        """Link x-axes iff the average plot is showing the independent variable."""
        if self.x_channel_index == 0:
            self._image_widget.setXLink(self.average_plot)
        else:
            self._image_widget.setXLink(None)


    # ── Data update ───────────────────────────────────────────────────────────

    def set_data(self, signal_data, raw_data, x_extent=None,
                 x_label='X', x_unit='', x0_label='X', x0_unit='',
                 y_label='Signal', y_unit=''):
        """
        Refresh both plots.

        Parameters
        ----------
        signal_data : ndarray or None
            Shape ``(n_points, n_channels)`` — the averaged scan data.
        raw_data : ndarray or None
            Shape ``(n_scans, n_points, n_channels)`` — all individual scan lines.
        x_extent : (float, float) or None
            Fixed (x_min, x_max) for the image x-axis.  When *None* the range
            is inferred from the recorded x values in ``raw_data``.
        x_label, x_unit : str
            Axis label / unit for the selected x-channel (average plot).
        x0_label, x0_unit : str
            Axis label / unit for column 0 (always used as the 2-D image x-axis).
        y_label, y_unit : str
            Axis labels / units for the selected y-channel.
        """
        xi = self.x_channel_index
        yi = self.y_channel_index

        # Update axis labels
        self.average_plot.setLabel('bottom', x_label, units=x_unit)
        self.average_plot.setLabel('left', y_label, units=y_unit)
        self._image_widget.setLabel('bottom', x0_label, units=x0_unit)
        self._colorbar.set_label(text=y_label, unit=y_unit)

        # ── 1-D average plot ──────────────────────────────────────────────────
        channel_changed = (xi != self._prev_xi) or (yi != self._prev_yi)
        self._prev_xi = xi
        self._prev_yi = yi

        if (signal_data is not None
                and signal_data.ndim == 2
                and signal_data.shape[1] > max(xi, yi)):
            x_sig = signal_data[:, xi]
            y_sig = signal_data[:, yi]
            valid = np.isfinite(x_sig) & np.isfinite(y_sig)
            if valid.any():
                self.average_plot.data = (x_sig[valid], y_sig[valid])
                # When the selected channel changes, re-enable y auto-range so
                # the new data always fits in view (a previous user zoom may
                # have disabled it).
                if channel_changed:
                    self.average_plot.getViewBox().enableAutoRange(axis='y')
                # Set x-range explicitly.  x_extent comes from the configured
                # scan range (column 0), so only use it when the average plot
                # is also showing column 0; otherwise derive from the data.
                if xi == 0 and x_extent is not None:
                    self.average_plot.setXRange(
                        float(x_extent[0]), float(x_extent[1]), padding=0.05
                    )
                else:
                    self.average_plot.setXRange(
                        float(x_sig[valid].min()), float(x_sig[valid].max()),
                        padding=0.05
                    )
            else:
                self.average_plot.data = None
        else:
            self.average_plot.data = None

        # ── 2-D image ─────────────────────────────────────────────────────────
        self._update_image(raw_data, x_extent)

    def update_image_data(self, raw_data, x_extent=None, y_label='Signal', y_unit=''):
        """
        Update only the 2-D image — suitable for per-data-point refreshes
        without recomputing the (more expensive) averaged signal plot.

        Parameters
        ----------
        raw_data : ndarray or None
            Shape ``(n_scans, n_points, n_channels)``.
        x_extent : (float, float) or None
            Fixed x-axis range.  Preferred over inferred range during scanning.
        y_label, y_unit : str
            Label / unit for the colour bar.
        """
        self._colorbar.set_label(text=y_label, unit=y_unit)
        self._update_image(raw_data, x_extent)

    def clear_data(self):
        """Clear both plots."""
        self.average_plot.data = None
        self._image_item.clear()
        self._last_image_data = None
        self._last_x_extent = (0.0, 1.0)

    # ── Internal rendering ────────────────────────────────────────────────────

    def _update_image(self, raw_data, x_extent=None):
        """
        Shared image update logic used by both ``set_data`` and
        ``update_image_data``.

        The raw_data array has shape ``(n_scans, n_points, n_channels)``.
        We extract channel *yi*, transpose to ``(n_points, n_scans)`` so that
        pyqtgraph maps the first axis to x (the scan variable) and the second
        axis to y (scan line index), which is the physically meaningful layout.
        """
        # The 2-D image always uses column 0 (the independent / control variable)
        # as its x-axis, regardless of the average-plot x-channel selector.
        xi = 0
        yi = self.y_channel_index

        if (raw_data is not None
                and raw_data.ndim == 3
                and raw_data.shape[2] > max(xi, yi)):
            # Transpose: (n_scans, n_points) → (n_points, n_scans)
            # axis-0 → x (scan variable), axis-1 → y (scan line index)
            img = raw_data[:, :, yi].T.copy()

            # Determine x extent from caller hint or recorded x values
            if x_extent is not None:
                x_min, x_max = float(x_extent[0]), float(x_extent[1])
            else:
                all_x = raw_data[:, :, xi].ravel()
                finite_x = all_x[np.isfinite(all_x)]
                if finite_x.size > 1:
                    x_min, x_max = float(finite_x.min()), float(finite_x.max())
                elif finite_x.size == 1:
                    x_min, x_max = float(finite_x[0]), float(finite_x[0])
                else:
                    x_min, x_max = 0.0, float(img.shape[0])

            # Optional per-line normalisation.
            # After transpose, scan lines are columns (axis 1), so normalise
            # by the mean along axis 0 (across x points within each scan line).
            if self._normalize_checkbox.isChecked():
                try:
                    global_mean = np.nanmean(img)
                    col_means = np.nanmean(img, axis=0, keepdims=True)
                    with np.errstate(invalid='ignore', divide='ignore'):
                        img = img * (global_mean / col_means)
                except Exception:
                    self._normalize_checkbox.setChecked(False)

            self._last_image_data = img
            self._last_x_extent = (x_min, x_max)
            self._render_image(img, x_min, x_max)
        else:
            self._last_image_data = None
            self._last_x_extent = (0.0, 1.0)
            self._image_item.clear()

    def _render_image(self, img, x_min, x_max):
        if self._colorbar.mode is ColorBarWidget.ColorBarMode.PERCENTILE:
            self._image_item.set_image(image=img, autoLevels=False)
            levels = self._image_item.levels
            if levels is not None:
                self._colorbar.set_limits(*levels)
        else:
            self._image_item.set_image(
                image=img,
                autoLevels=False,
                levels=self._colorbar.limits,
            )
        if img is not None and img.shape[0] > 0 and img.shape[1] > 0:
            # After transpose: axis-0 = x (n_points), axis-1 = y (n_scans)
            # extent (1, n_scans) places pixel centres at integers 1..n_scans
            self._image_item.set_image_extent(
                ((x_min, x_max), (1, img.shape[1]))
            )
            # Explicitly update the ViewBox x-range so both linked plots show
            # the correct span (setRect positions the image but does not move
            # the viewport automatically).
            self._image_widget.setXRange(x_min, x_max, padding=0.05)

    # ── Colorbar callbacks ────────────────────────────────────────────────────

    @QtCore.Slot(object)
    def _colorbar_mode_changed(self, mode):
        if self._colorbar.mode is ColorBarWidget.ColorBarMode.PERCENTILE:
            self._image_item.set_percentiles(self._colorbar.percentiles)
        else:
            self._image_item.set_percentiles(None)
        if self._last_image_data is not None:
            self._render_image(self._last_image_data, *self._last_x_extent)

    @QtCore.Slot(tuple)
    def _colorbar_limits_changed(self, limits):
        lower, upper = limits
        if (self._colorbar.mode is not ColorBarWidget.ColorBarMode.PERCENTILE
                and self._last_image_data is not None):
            self._image_item.set_image(
                image=self._last_image_data,
                autoLevels=False,
                levels=(lower, upper),
            )

    @QtCore.Slot(tuple)
    def _colorbar_percentiles_changed(self, percentiles):
        if (self._colorbar.mode is ColorBarWidget.ColorBarMode.PERCENTILE
                and self._last_image_data is not None):
            self._image_item.set_percentiles(percentiles)
            self._render_image(self._last_image_data, *self._last_x_extent)
