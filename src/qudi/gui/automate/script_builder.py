import sys
import os
import json
import time
from turtle import position
#import pandas as pd

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QListWidget,
    QHBoxLayout, QDialog, QLabel, QFileDialog, QMessageBox,
    QCheckBox, QFormLayout, QSpinBox, QDoubleSpinBox, QProgressBar, QMainWindow
)
from PySide6 import QtWidgets as qw
from PySide6 import QtCore
from PySide6.QtCore import Qt

#Logic imports for automation functions
from qudi.logic.scanning_probe_logic import ScanningProbeLogic
from qudi.logic.scanning_optimize_logic import ScanningOptimizeLogic
from qudi.logic.scanning_data_logic import ScanningDataLogic
from qudi.logic.spectrometer_logic import SpectrometerLogic
from qudi.logic.simple_scan_logic import SimpleScanLogic

from qudi.gui.automate.grid_maker import GridApp


# ###
# Example config, make sure to extend as new connectors are added:
# 	script_builder:
# 			module.Class: automate.script_builder.ScriptBuilderGUI
# 		connect:
# 		    optimize_logic : scanning_optimize_logic
# 			scanning_logic : scanning_probe_logic
# 			scanning_data_logic : scanning_data_logic
# 			spectrometer_logic : spectrometer_logic
# 			simple_scan_logic : simple_scan_logic

## To add new functions: Populate the entry in FunctionCatalog, including the register decorator and finish functions


# ---------------------- FUNCTION CATALOG ----------------------
class FunctionCatalog(QtCore.QObject):
    sigFuncComplete = QtCore.Signal(str)  #Emits log string when function completes, can be connected to log_result in ScriptBuilderGUI
    sigInterrupt = QtCore.Signal()

    def __init__(self, parent):  #Parent required to access logic modules
        super().__init__(parent)
        self.parent = parent
        for name, connector in self.parent._connectors.items():
            setattr(self, name, connector)

        self._functions = self._discover_functions()
        self.folder_path = None
        self._func_running=False
        self.sigFuncComplete.connect(lambda _: setattr(self,'_func_running',False))

    def _discover_functions(self):
        funcs = {}
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, "_meta"):
                if not attr._meta.get("hidden", False):
                    funcs[attr_name] = attr
        return funcs

    def list_functions(self):
        return list(self._functions.keys())

    def get_meta(self, func_name):
        return self._functions[func_name]._meta

    def call(self, func_entry, coord_label=None):
        if self._func_running:  #This shouldn't happen, but just in case prevent to functions running simultaneously
            return
        self._func_running=True
        func_name = func_entry["name"]
        func = self._functions[func_name]
        meta = func._meta

        start_position = [self.scanning_logic().scanner_position[coord] for coord in ['x','y','z']]
        self._metadata = {"start_position": start_position}  #Reset each call, will be passed to save functions
        if coord_label is not None: self._metadata["coord_label"] = coord_label  #For logging grid coordinate, can be used in functions by accessing self._metadata

        if "params" in func_entry:
            kwargs = func_entry["params"]
            typed_kwargs = {}
            for k, spec in meta["params"].items():
                default = spec.get("default")
                if callable(default):
                    default = default(self)
                val = kwargs.get(k, default)  #Use provided value if available, otherwise default
                if type(spec["type"]) is list: #
                    typed_kwargs[k] = spec["type"][0](val)
                else:
                    typed_kwargs[k] = spec["type"](val)  #Cast to correct type
            res = func(**typed_kwargs)
        else:
            res = func()
        return res


    @staticmethod
    def register(params: dict = {}, returns="log", hidden=False):
        def decorator(func):
            func._meta = {
                "params": params,
                "returns": returns,
                "hidden": hidden
            }
            return func
        return decorator
    

    
    ##############################################################################################################
    ### Function definitions below. Use @register({param dict} , returns=Optional)  then def function():       ###
    ### If no input parameters, still use @register()
    ### Emits string will save that string to log.
    ### Using lambda ctx in default will pull currently set values when the dialog opens, ctx is the context.
    ### Implemented types: float (DoubleSpinBox), int (SpinBox), bool (Checkbox), list(ComboBox)
    ### For lists, "type" is defined as [type], i.e. a list containing the type that will be populated in the list.
    ###  then "entries" is required for the possible choices.
    ##############################################################################################################


    @register()
    def optimize(self):
        self._start_position = [self.scanning_logic().scanner_position[coord] for coord in ['x','y','z']]
        self.optimize_logic().start_optimize()
        self.optimize_logic().sigOptimizeStateChanged.connect(self.finish_optimize, Qt.QueuedConnection)
        self.sigInterrupt.connect(self.optimize_logic().stop_optimize)
        
        
    def finish_optimize(self):
        if (not self._func_running) or (self.optimize_logic().module_state() != 'idle'):  #state_change emits happen during intermediate steps, need to check if we're actually done
            return
        try:
            self.optimize_logic().sigOptimizeStateChanged.disconnect(self.finish_optimize)
            self.sigInterrupt.disconnect(self.optimize_logic().stop_optimize)
        except:
            pass  #Ignore if signal was already be disconnected, this seems to happen because the statechange emits two signals quickly before disconnect copmletes
        final_position = [self.scanning_logic().scanner_position[coord] for coord in ['x','y','z']]
        self.sigFuncComplete.emit(f"Optimized from {self._start_position} to {final_position}")
        

    @register(params={
        "center_wavelength": {"type": float, "default": lambda ctx: ctx.spectrometer_logic().wavelength},
        "exposure_time": {"type": float, "default": lambda ctx: ctx.spectrometer_logic().exposure_time},
        "number_spectra": {"type": int, "default": lambda ctx: ctx.spectrometer_logic().number_spectra},
        "data_type": {"type":[str], "entries": ['spectrum','background'], "default": 'spectrum'},
    })
    def record_spectrum(self, center_wavelength, exposure_time, number_spectra, data_type):
        # Implementation for recording spectrum
        self.spectrometer_logic().wavelength = center_wavelength
        self.spectrometer_logic().exposure_time = exposure_time
        self.spectrometer_logic().background_correction = False #For consistency
        if data_type=='spectrum':
            self.spectrometer_logic().number_spectra = number_spectra
            self.spectrometer_logic().run_get_spectrum()
        elif data_type=='background':
            self.spectrometer_logic().number_background = number_spectra
            self.spectrometer_logic().run_get_background()
        self.spectrometer_logic().sig_acquisition_complete.connect(self.finish_record_spectrum, Qt.QueuedConnection)
        self.sigInterrupt.connect(self.spectrometer_logic().stop)  #Tell interrupt signal how to stop function
  
    def finish_record_spectrum(self,data_type):
        if (self.spectrometer_logic().acquisition_running) or (not self._func_running):
            return  # State update signals will be emitted before finished.
        try:
            self.spectrometer_logic().sig_acquisition_complete.disconnect(self.finish_record_spectrum)
            self.sigInterrupt.disconnect(self.spectrometer_logic().stop)
        except: 
            pass
        if data_type=='spectrum':
            self.spectrometer_logic().save_all_data(root_dir=self.folder_path,metadata=self._metadata)
        elif data_type=='background':
            self.spectrometer_logic().save_spectrum_data(background=True,root_dir=self.folder_path,metadata=self._metadata)
        self.sigFuncComplete.emit(f"Recorded {self.spectrometer_logic().number_spectra} {data_type} "
                                  f"at {self.spectrometer_logic().wavelength} nm "
                                  f"with {self.spectrometer_logic().exposure_time} s exposure time")
        
    
    @register(params={
        "scan_device": {"type": [str], "entries": lambda ctx: ctx.simple_scan_logic().device_dict, 
                        "default": lambda ctx: list(ctx.simple_scan_logic().device_dict.keys())[0]},  #For listable, set values as source list.
        "x_start": {"type": float, "default": lambda ctx: ctx.simple_scan_logic().x_range[0]}, 
        "x_end": {"type": float, "default": lambda ctx: ctx.simple_scan_logic().x_range[1]},
        "number_steps": {"type": int, "default": lambda ctx: ctx.simple_scan_logic().x_range[2]},
        "time_per": {"type": float, "default": lambda ctx: ctx.simple_scan_logic().time_per},
        "time_wait": {"type": float, "default": lambda ctx: ctx.simple_scan_logic().time_wait},
        "number_scans": {"type": int, "default": lambda ctx: ctx.simple_scan_logic().number_scans},
        "shuffle_x": {"type":bool, "default": lambda ctx: ctx.simple_scan_logic()._shuffle_x},
    })
    def record_scan(self, scan_device, x_start, x_end, number_steps, time_per, time_wait, number_scans, shuffle_x):
        # Implementation for recording generic v_scan. Logic will contain list of addressable devices.
        self.simple_scan_logic().scan_device = scan_device
        self.simple_scan_logic().x_range = (x_start,x_end,number_steps)
        self.simple_scan_logic().time_per = time_per
        self.simple_scan_logic().time_wait = time_wait
        self.simple_scan_logic().number_scans = number_scans
        self.simple_scan_logic().shuffle_x = shuffle_x
        
        self.simple_scan_logic().start_scan()
        self.simple_scan_logic().sigScanComplete.connect(self.finish_record_scan, Qt.QueuedConnection)
        self.sigInterrupt.connect(self.simple_scan_logic().stop_scan)  #Tell interrupt signal how to stop function

    def finish_record_scan(self, scan_success):
        if scan_success:
            try:
                self.sigInterrupt.disconnect(self.simple_scan_logic().stop_scan)
                self.simple_scan_logic().sigScanComplete.disconnect(self.finish_record_scan)
            except: 
                pass
            self.simple_scan_logic().save_data(root_dir=self.folder_path, metadata=self._metadata)
            self.sigFuncComplete.emit(f"Done scan: {self.simple_scan_logic().x_range}")
        else:
            self.sigFuncComplete.emit(f"Scan failed")

    _loop_list = []  #Allow for nested loops
    @register(params={"loop_count": {"type": int, "default": 1}})
    def LOOP_START(self, loop_count):
        self._loop_list.append( (loop_count, 0, self.parent._mw._current_script_idx) )
        self.sigFuncComplete.emit(f"Starting loop of {loop_count} iterations")

    @register()
    def LOOP_END(self):
        loop = self._loop_list[-1]
        if loop[1] < loop[0]-1:  #If we haven't reached the end of the loop, jump back to start
            self.parent._mw._current_script_idx = loop[2]  #Jump back to the function after loop_start
            self._loop_list[-1] = (loop[0], loop[1]+1, loop[2])  #Update loop count
            self.sigFuncComplete.emit(f"Loop iteration {loop[1]+2} of {loop[0]}")
        else:  #Otherwise, we're done with the loop, pop it from the list and continue
            self._loop_list.pop()
            self.sigFuncComplete.emit(f"Finished loop of {loop[0]} iterations")
        

# ---------------------- PARAMETER DIALOG ----------------------
class ParamDialog(QDialog):
    def __init__(self, ctx, func_name, meta, values={}):
        super().__init__()
        self.setWindowTitle(func_name)
        self.inputs = {}

        layout = QFormLayout()

        for name, spec in meta["params"].items():
            if type(spec['type']) == list:
                entries = spec.get("entries")
                if callable(entries):
                    entries = entries(ctx)
                widget = qw.QComboBox()
                widget.addItems(entries)

                default = spec.get("default")
                if callable(default):
                    default = default(ctx)
                val = values.get(name, default)
                widget.setCurrentText(val)

            elif spec['type'] == bool:
                default = spec.get("default")
                if callable(default):
                    default = default(ctx)
                val = values.get(name, default)
                widget = qw.QCheckBox()
                widget.setChecked(val)

            else:
                default = spec.get("default")
                if callable(default):
                    default = default(ctx)
                val = values.get(name, default)  #Use provided value if available, otherwise default
                if spec['type'] == int:
                    widget = QSpinBox()
                    widget.setMaximum(99999999)  #SpinBoxes typically max at 99
                else:
                    widget = QDoubleSpinBox()
                    widget.setRange(-1e12,1e12)  #Arbitrarily large hopefully
                widget.setValue(val)
            widget.setMinimumWidth(200)

            layout.addRow(QLabel(name), widget)
            self.inputs[name] = widget

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        layout.addRow(ok_btn)
        self.setLayout(layout)

    def get_values(self):
        res = {}
        for name,widget in self.inputs.items():
            if type(widget)==qw.QComboBox:
                res[name] = widget.currentText()
            elif type(widget)==qw.QCheckBox:
                res[name] = widget.isChecked()
            else:
                res[name] = widget.value()
        return res

# ---------------------- MAIN GUI ----------------------
class ScriptBuilderGUI(GuiBase):
    optimize_logic = Connector(interface=ScanningOptimizeLogic)
    scanning_logic = Connector(interface=ScanningProbeLogic)
    scanning_data_logic = Connector(interface=ScanningDataLogic)
    spectrometer_logic = Connector(interface=SpectrometerLogic)
    simple_scan_logic = Connector(interface=SimpleScanLogic)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connectors = {
            'optimize_logic': self.optimize_logic,
            'scanning_logic': self.scanning_logic,
            'scanning_data_logic': self.scanning_data_logic,
            'spectrometer_logic': self.spectrometer_logic,
            'simple_scan_logic': self.simple_scan_logic
            }
        self._functionCatalog = FunctionCatalog(self)
        self._grid_maker = GridApp(self)
        self._mw = ScriptBuilder(self)

    def on_activate(self):
        self.show()
    def on_deactivate(self):
        pass
    def show(self):
        self._mw.resize(1000, 600)
        self._mw.show()



class ScriptBuilder(QMainWindow):
    def __init__(self, parent):
        super().__init__()
        self.parent=parent
        self.setWindowTitle("Script Builder")
        self.catalog = self.parent._functionCatalog
        self.grid_maker = self.parent._grid_maker
        self.script = []
        self.coordinate_list = None
        self.logfile_path = None
        self._log_open = False
        self.folder_path = None
        self.printLogToConsole = True

        cw = QWidget()
        self.setCentralWidget(cw)

        main_layout = QHBoxLayout()
        cw.setLayout(main_layout)

        self.func_list = QListWidget()
        self.func_list.addItems(self.catalog.list_functions())

        self.add_btn = QPushButton("Add Function")
        self.add_btn.clicked.connect(self.add_function)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.func_list)
        left_layout.addWidget(self.add_btn)

        self.script_list = QListWidget()
        self.script_list.setDragDropMode(QListWidget.InternalMove)

        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        self.grid_btn = QPushButton("Create Grid")
        self.grid_checkbox = QCheckBox('Enable')
        self.grid_checkbox.setCheckable(False)  #Disabled until grid is populated
        self.folder_btn = QPushButton("Select Folder")
        self.run_btn = QPushButton("Run Script")
        self.stop_btn = QPushButton("Stop Script")
        self.save_btn = QPushButton("Save Script")
        self.load_btn = QPushButton("Load Script")

        self.edit_btn.clicked.connect(self.edit_function)
        self.delete_btn.clicked.connect(self.delete_function)
        self.grid_btn.clicked.connect(self.create_grid)
        self.folder_btn.clicked.connect(self.select_folder)
        self.run_btn.clicked.connect(self.start_script, Qt.QueuedConnection)
        self.stop_btn.clicked.connect(lambda: self.finish_script(True), Qt.QueuedConnection)
        self.save_btn.clicked.connect(self.save_script)
        self.load_btn.clicked.connect(self.load_script)

        self.progress = QProgressBar()

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.script_list)
        right_layout.addWidget(self.edit_btn)
        right_layout.addWidget(self.delete_btn)
        grid_layout = QHBoxLayout()
        right_layout.addLayout(grid_layout)
        grid_layout.addWidget(self.grid_btn)
        grid_layout.addWidget(self.grid_checkbox)
        right_layout.addWidget(self.folder_btn)
        right_layout.addWidget(self.progress)
        right_layout.addWidget(self.run_btn)
        right_layout.addWidget(self.stop_btn)
        right_layout.addWidget(self.save_btn)
        right_layout.addWidget(self.load_btn)

        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)

    def _set_running(self, state):
        self._running = state
        self.func_list.setEnabled(not state)
        self.script_list.setEnabled(not state)
        self.add_btn.setEnabled(not state)
        self.edit_btn.setEnabled(not state)
        self.delete_btn.setEnabled(not state)
        self.grid_btn.setEnabled(not state)
        self.grid_checkbox.setEnabled(not state)
        self.folder_btn.setEnabled(not state)
        self.run_btn.setEnabled(not state)
        self.stop_btn.setEnabled(state)
        self.save_btn.setEnabled(not state)
        self.load_btn.setEnabled(not state)
        


    def _refresh_script_order(self):
        self.script = [self.script_list.item(i).data(Qt.UserRole) for i in range(self.script_list.count())]

    def _format_entry(self, entry):
        if 'params' in entry:
            params = ", ".join(f"{k}={v}" for k, v in entry["params"].items())
            return f"{entry['name']}({params})"
        else:
            return entry["name"]

    def add_function(self):
        func_name = self.func_list.currentItem().text()
        meta = self.catalog.get_meta(func_name)

        if len(meta["params"]) != 0:
            dialog = ParamDialog(self.catalog, func_name, meta)
            if dialog.exec():
                entry = {"name": func_name, "params": dialog.get_values()}
                self.script.append(entry)
            else:
                return  #Dialog was closed.
        else:
            entry = {"name": func_name}
            self.script.append(entry)

        self.script_list.addItem(self._format_entry(entry))
        self.script_list.item(self.script_list.count()-1).setData(Qt.UserRole, entry)
        self._refresh_script_order()

    def edit_function(self):
        idx = self.script_list.currentRow()
        if idx < 0: return

        item = self.script_list.item(idx)
        entry = item.data(Qt.UserRole)
        meta = self.catalog.get_meta(entry["name"])

        if len(entry['params']) == 0:  #nothing to edit
            return

        dialog = ParamDialog(self.catalog, entry["name"], meta, entry["params"])
        if dialog.exec():
            entry["params"] = dialog.get_values()
            item.setText(self._format_entry(entry))
            self.script_list.item(idx).setData(Qt.UserRole, entry)
            self._refresh_script_order()
        else:
            return  #Dialog was closed.

    def delete_function(self):
        idx = self.script_list.currentRow()
        if idx >= 0:
            self.script_list.takeItem(idx)
            self._refresh_script_order()

    def _set_coordinate_list(self, coord_list, coord_list_CR=None):
        self.coordinate_list = coord_list
        self.coordinate_list_CR = coord_list_CR
        if coord_list is not None:
            self.grid_checkbox.setCheckable(True)
            self.grid_checkbox.setChecked(True)

    def create_grid(self):
        self.grid_maker.exec()
        self._initial_z = self.parent.scanning_logic().scanner_position['z']  #Allow to start each next point at initial z.
        self.grid_maker.sig_grid_updated.connect(self._set_coordinate_list)

    def select_folder(self):
        self.folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if self.folder_path == "":
            self.folder_path = None
        self.catalog.folder_path = self.folder_path

    def save_script(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Script", filter="JSON (*.json)")
        if path:
            self._refresh_script_order()
            with open(path, "w") as f:
                json.dump(self.script, f, indent=2)

    def load_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Script", filter="JSON (*.json)")
        if path:
            with open(path) as f:
                self.script = json.load(f)

            self.script_list.clear()
            for entry in self.script:
                self.script_list.addItem(self._format_entry(entry))
                self.script_list.item(self.script_list.count()-1).setData(Qt.UserRole, entry)

    def log_result(self, result):  #Shouldn't be open more than once at a time, but just in case
        while self._log_open:  #Wait until log is free
            pass
        if self.printLogToConsole:
            print(result)
        self._log_open = True
        if self.logfile_path is not None:
            t=time.strftime('%Y%m%d_%H%M%S', time.localtime())
            with open(self.logfile_path, "a") as f:
                f.write(f'{t}: {result}'+"\n")
        self._log_open=False

    
    def start_script(self):
        if (self.folder_path is None) or (not os.path.isdir(self.folder_path)):
            self.select_folder()
            if self.folder_path is None:  #User cancelled folder selection
                return

        self.logfile_path = f"{self.folder_path}/log_{time.strftime('%Y%m%d_%H%M%S', time.localtime())}.txt"

        if (self.coordinate_list is None) or (not self.grid_checkbox.isChecked()):
            self._coordinate_list = [[self.parent.scanning_logic().scanner_position[coord] for coord in ['x','y','z']]]
            self._coord_labels = [None]
        else:
            self._coordinate_list = [coordI+[self._initial_z] for coordI in self.coordinate_list]
            self._coord_labels = self.coordinate_list_CR

        self._refresh_script_order()
        self._set_running(True)

        total = len(self._coordinate_list)*len(self.script)
        self.progress.setMaximum(total)
        
        self._current_coord_idx = 0
        self._current_script_idx = 0

        self.log_result(f'Starting scan of {len(self._coordinate_list)} coordinates:')
        #for ii,coords in enumerate(self._coordinate_list):
            #self.log_result(f'{ii+1} : {coords}')

        try: 
            self.catalog.sigFuncComplete.disconnect(self.next_script_step)  #In case this was left connected.
        except:
            pass
        self.catalog.sigFuncComplete.connect(self.next_script_step, Qt.QueuedConnection)  #Connect function completion signal to next step
        

        self.next_script_step()  #Start first step


    @QtCore.Slot()
    def next_script_step(self, result=None):
        self.progress.setValue(self._current_coord_idx*len(self.script)+self._current_script_idx)
        if result is not None:
            self.log_result(result)

        if not self._running: return  # Something called this after script was stopped, ignore.

        if self._current_script_idx == 0: # Goto location and update lists
            if self.grid_checkbox.isChecked():
                if self._current_coord_idx==0:
                    self.grid_maker.update_done(None, self.coordinate_list[self._current_coord_idx])
                elif self._current_coord_idx < len(self.coordinate_list):
                    self.grid_maker.update_done(self.coordinate_list[:self._current_coord_idx], self.coordinate_list[self._current_coord_idx])
                else:
                    self.grid_maker.update_done(self.coordinate_list[:self._current_coord_idx], None)

            if self._current_coord_idx >= len(self._coordinate_list):
                self.finish_script()
                return
        
            coords = {}
            coords['x']=self._coordinate_list[self._current_coord_idx][0]
            coords['y']=self._coordinate_list[self._current_coord_idx][1]
            coords['z']=self._coordinate_list[self._current_coord_idx][2]
            self.parent.scanning_logic().set_target_position(coords, move_blocking=True)
            self.log_result(f'{self._current_coord_idx+1}/{len(self._coordinate_list)} Moved to : {coords}')
        
        self.script_list.setCurrentRow(self._current_script_idx)
        QApplication.processEvents()
        entry = self.script[self._current_script_idx]
        self.log_result(f'Starting script step: {entry}')
        self.catalog.call(entry, coord_label=self._coord_labels[self._current_coord_idx])
        self._current_script_idx += 1
        if self._current_script_idx >= len(self.script):
            self._current_script_idx = 0
            self._current_coord_idx += 1

        


    def finish_script(self,interrupted=False):
        if not self._running:
            return
        
        try: 
            self.catalog.sigFuncComplete.disconnect(self.next_script_step)
        except:
            pass  #In case it was disconnected somehow already.
        
        self._set_running(False)
        if interrupted:
            self.catalog.sigInterrupt.emit()
            self.log_result("Script execution interrupted by user")
            QMessageBox.information(self, "Done", "Execution interrupted by user")
        else:
            self.log_result("Script execution complete")
            QMessageBox.information(self, "Done", "Execution complete")

        self.logfile_path = None
        
        



# ---------------------- MAIN ----------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScriptBuilder()
    window.resize(1000, 600)
    window.show()
    sys.exit(app.exec())
