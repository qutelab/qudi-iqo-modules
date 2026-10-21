# -*- coding: utf-8 -*-

"""
This file contains models of Gaussian fitting routines for qudi based on the lmfit package.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-core/>

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

__all__ = ('Rabi')

import numpy as np
from qudi.util.fit_models.model import FitModelBase, estimator
from qudi.util.fit_models.helpers import correct_offset_histogram, smooth_data, sort_check_data
from qudi.util.fit_models.helpers import estimate_double_peaks, estimate_triple_peaks
from qudi.util.fit_models.linear import Linear
from qudi.util.fit_models.gaussian import *

# class Rabi(FitModelBase):
    # """ ToDo: Document
    # """
    # def __init__(self, **kwargs):
        # super().__init__(**kwargs)
        # self.set_param_hint('offset', value=0, min=-np.inf, max=np.inf)
        # self.set_param_hint('amplitude_1', value=0, min=-np.inf, max=np.inf)
        # self.set_param_hint('amplitude_2', value=0, min=-np.inf, max=np.inf)
        # self.set_param_hint('amplitude_3', value=0, min=-np.inf, max=np.inf)
        # self.set_param_hint('center_1', value=0., min=-np.inf, max=np.inf)
        # self.set_param_hint('center_2', value=0., min=-np.inf, max=np.inf)
        # self.set_param_hint('center_3', value=0., min=-np.inf, max=np.inf)
        # self.set_param_hint('sigma_1', value=0., min=0., max=np.inf)
        # self.set_param_hint('sigma_2', value=0., min=0., max=np.inf)
        # self.set_param_hint('sigma_3', value=0., min=0., max=np.inf)

    # @staticmethod
    # def _model_function(x, offset, c0, contrast, center_1, center_2, center_3, sigma_1, sigma_2, sigma_3,
                        # amplitude_1, amplitude_2, amplitude_3, omega, delta, population, Tdecay, toffset):
    # #c0: PL with no MW
    # #contrast: full-flip contrast
    # #omega: on-resonance Rabi frequency, where pi pulse = 1 / (2 * omega)
    # #delta: detuning of the drive from the m_l = +1 linear
    # #population: m_l = +1 population. The other two lines get (1 - P) / 2
    # #Tdecay: exponential damping of each line's oscillations
    # #toffset: time offset for pulse rise or dead time
        # try:
            # Wi = np.sqrt(omega **2 + delta **2)
            # a = c0 * ( 1 - contrast * (np.sum( omega **2 / Wi **2) * (1 - np.exp(-t + toffset)/Tdecay) * np.cos(2 * np.pi * Wi * (t + toffset)))) / 2, 0, np.pi)
            # b = standard single frequency rabi equation
        # return offset + multiple_gaussian(x,
                                          # (center_1, center_2, center_3),
                                          # (sigma_1, sigma_2, sigma_3),
                                          # (amplitude_1, amplitude_2, amplitude_3))