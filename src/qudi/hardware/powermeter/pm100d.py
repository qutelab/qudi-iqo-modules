"""
Thorlabs PM100D power meter - single-class SCPI/VISA interface.

Wraps connection, configuration, sampling, and uncertainty budgeting into
one class so it can be dropped into other code. The public entry point is
measure_power(), which returns (mean_power_W, combined_uncertainty_W).

Requirements:
    pip install pyvisa
    NI-VISA runtime (or pyvisa-py, see PM100D.__init__ backend arg)

Example:
    from pm100d import PM100D

    with PM100D() as pm:
        power, uncertainty = pm.measure_power(
            sample_rate_hz=20,
            duration_s=10,
            wavelength_nm=737,
            save_raw=False,
            verbose=True,
        )
        print(f"{power*1e6:.3f} +/- {uncertainty*1e6:.3f} uW")
"""

import time
from typing import Optional, Tuple

import numpy as np
import pyvisa

from qudi.interface.process_control_interface import ProcessValueInterface, ProcessControlConstraints

class PM100D(ProcessValueInterface):
    """
    Thin SCPI wrapper around a Thorlabs PM100D + power sensor.
    Example config:
    
    powermeter:
        module.Class: 'powermeter.pm100d.PM100D'
        
    
    """

    # Sensor calibration accuracy spec, fraction of reading, by wavelength
    # band (low_nm, high_nm, fraction). Defaults are for the S130C.
    # If you switch sensors, either edit these or pass your own via
    # sensor_accuracy_bands in __init__.
    _DEFAULT_ACCURACY_BANDS = (
        (400, 440, 0.05),
        (440, 980, 0.03),
        (980, 1100, 0.07),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    # -- setup / connection -------------------------------------------------
    # """
        # resource_name : VISA resource string, e.g.
            # "USB0::0x1313::0x8070::P0000116::INSTR". Auto-detected if None.
        # backend : "" for default (NI-VISA if available, else pyvisa-py),
            # or "@py" to force pyvisa-py.
        # sensor_accuracy_bands : override the (lo_nm, hi_nm, fraction)
            # calibration-accuracy table, if using a sensor other than S130C.
        # """
    def on_activate(self):
        resource_name = None
        timeout_ms = 3000
        backend = ""
        sensor_accuracy_bands = None
        try:        
            print(backend, type(backend))
            self.rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            if resource_name is None:
                resource_name = self._find_pm100d(self.rm)
            self.resource_name = resource_name
            self.inst = self.rm.open_resource(resource_name)
            self.inst.timeout = timeout_ms
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.idn = self.inst.query("*IDN?").strip()
            self._accuracy_bands = sensor_accuracy_bands or self._DEFAULT_ACCURACY_BANDS
            self.connected=True
        except Exception as e:
            self.connected=False
            self.log.warning(f'Unable to connect to PM100D, please reload module pm100d to retry: {e}')
        
    def on_deactivate(self):
        if self.connected:
            self.inst.close()
        self.connected=False

    @staticmethod
    def _find_pm100d(rm: pyvisa.ResourceManager) -> str:
        """Find a connected PM100D over USB (Thorlabs Vendor ID 0x1313)."""
        resources = rm.list_resources()
        candidates = [r for r in resources if "0x1313" in r]
        if not candidates:
            raise RuntimeError(
                f"No PM100D found. Available VISA resources: {resources}"
            )
        if len(candidates) > 1:
            print(f"Multiple Thorlabs devices found, using first: {candidates}")
        return candidates[0]

    def _sensor_accuracy(self, wavelength_nm: float) -> float:
        """Specified calibration-accuracy fraction at this wavelength."""
        for lo, hi, frac in self._accuracy_bands:
            if lo <= wavelength_nm <= hi:
                return frac
        raise ValueError(
            f"{wavelength_nm} nm is outside the sensor's specified "
            f"wavelength range for the configured accuracy bands."
        )

    def _configure_power(self, wavelength_nm, auto_range=True, average_count=1):
        self.inst.write("CONF:POW")
        self.inst.write(f"SENS:CORR:WAV {wavelength_nm}")
        self.inst.write(f"SENS:POW:RANG:AUTO {'ON' if auto_range else 'OFF'}")
        self.inst.write(f"SENS:AVER:COUN {average_count}")
        self.inst.write("SENS:POW:UNIT W")

    def _read_power(self) -> float:
        """Trigger a new measurement and fetch it, in Watts."""
        return float(self.inst.query("READ?"))

    # -- public API -----------------------------------------------------

    def measure_power(
        self,
        sample_rate_hz: float = 100,
        duration_s: float = 0.1,
        wavelength_nm: float = 531,
        save_raw: bool = False,
        save_path: str = '',
        average_count: int = 1,
        auto_range: bool = True,
        verbose: bool = False,
    ) -> Tuple[float, float]:
        """
        Sample optical power for `duration_s` seconds at up to
        `sample_rate_hz`, at `wavelength_nm`, and return the mean power
        and its combined uncertainty, both in Watts.

        Combined uncertainty is the root-sum-square of:
          - statistical uncertainty (SEM) across the collected samples
          - the sensor's specified calibration accuracy at this wavelength
        (an independent, non-averaging-reducible systematic term).

        Parameters
        ----------
        sample_rate_hz : requested polling rate. Actual achieved rate is
            capped by USB/SCPI round-trip latency and average_count.
        duration_s : total acquisition time.
        wavelength_nm : wavelength for spectral response correction.
        save_raw : if True, saves (timestamps, samples) to an .npz file.
        save_path : path for the saved .npz file if save_raw is True.
        average_count : internal hardware averaging per reading (see
            SENS:AVER:COUN in the PM100D SCPI reference).
        auto_range : enable auto-ranging.
        verbose : print progress and a results summary.

        Returns
        -------
        (mean_power_W, combined_uncertainty_W) **in mW
        """
        self._configure_power(
            wavelength_nm, auto_range=auto_range, average_count=average_count
        )

        dt_target = 1.0 / sample_rate_hz
        n_samples = max(1, int(duration_s * sample_rate_hz))
        samples = np.empty(n_samples)
        timestamps = np.empty(n_samples)
        t_start = time.perf_counter()

        if verbose:
            print(
                f"Measuring at {wavelength_nm} nm, target {sample_rate_hz} Hz "
                f"for {duration_s} s ({n_samples} samples)..."
            )

        for i in range(n_samples):
            t0 = time.perf_counter()
            samples[i] = self._read_power()
            timestamps[i] = time.perf_counter() - t_start
            elapsed = time.perf_counter() - t0
            sleep_time = dt_target - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        mean_power = float(np.mean(samples))
        std_power = float(np.std(samples, ddof=1)) if n_samples > 1 else 0.0
        sem_power = std_power / np.sqrt(n_samples) if n_samples > 1 else 0.0

        accuracy_frac = self._sensor_accuracy(wavelength_nm)
        u_sensor = accuracy_frac * mean_power
        u_combined = float(np.sqrt(sem_power**2 + u_sensor**2))

        if save_raw:
            np.savetxt(save_path, np.vstack((timestamps, samples)).T, delimiter=',')

        if verbose:
            actual_rate = n_samples / timestamps[-1] if timestamps[-1] > 0 else float("inf")
            print(f"  N samples:              {n_samples}")
            print(f"  Achieved rate:           {actual_rate:.2f} Hz")
            print(f"  Mean power:              {mean_power * 1e6:.4f} uW")
            print(f"  Std deviation:           {std_power * 1e6:.4f} uW")
            print(f"  Stat. uncertainty (SEM): {sem_power * 1e6:.4f} uW")
            print(
                f"  Sensor cal. uncertainty: {u_sensor * 1e6:.4f} uW "
                f"({accuracy_frac * 100:.0f}% @ {wavelength_nm} nm)"
            )
            print(f"  Combined uncertainty:    {u_combined * 1e6:.4f} uW")
            if save_raw:
                print(f"  Raw samples saved to:    {save_path}")

        return mean_power, u_combined

    # -- cleanup / context manager ---------------------------------------

    def close(self):
        self.inst.close()
        self.rm.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    with PM100D() as pm:
        print(f"Connected: {pm.idn}")
        power, uncertainty = pm.measure_power(
            sample_rate_hz=10,
            duration_s=0.1,
            wavelength_nm=531,
            save_raw=True,
            save_path=r"C:\Users\qutel\qudi\qudi-core\src\qudi\scripts\test_save.csv",
            verbose=True,
        )
        print(f"\nResult: {power * 1e6:.4f} +/- {uncertainty * 1e6:.4f} uW")
