from snAPI.Main import *
from qudi.util.datastorage import TextDataStorage
import nidaqmx
from time import sleep
from PySide6 import QtCore
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt

class PicoWorker(QtCore.QObject):

    sigWorkerFinished = QtCore.Signal(object)
    sigAcquireData = QtCore.Signal()
    dummyMode = True

    def __init__(self):
        super().__init__()
        self._running = False
        self.result = None
        self.max_time = 30000 #ms

            
        self._thread = QtCore.QThread()
        self.moveToThread(self._thread)
        self._thread.start()

        if self.dummyMode:
            self.sn = None
            self.sigAcquireData.connect(self.acquire_data_dummy, QtCore.Qt.ConnectionType.QueuedConnection)
        else:
            self.sn = snAPI(systemIni=r"C:\Users\qutel\.conda\envs\qudi\Lib\site-packages\snAPI\system.ini")
            self.sn.getDevice()
            self.sn.setLogLevel(logLevel=LogLevel.DataFile, onOff=True)
            self.sn.initDevice(MeasMode.T3)
            self.sn.loadIniConfig(r"C:\Users\qutel\Projects\QE\measurement-code\PicoharpServer-main\PicoharpConfig\PH330_Edge.ini")
            self.sigAcquireData.connect(self.acquire_data, QtCore.Qt.ConnectionType.QueuedConnection)


    def shutdown(self):
        self.sigAcquireData.disconnect()
        if self._thread is None:
            return
        #self._stop = True      # Implement measurement interruption?
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        

    @QtCore.Slot()
    def acquire_data(self):
        try:
            with nidaqmx.Task() as task:
                task.ao_channels.add_ao_voltage_chan("Dev1/ao3", min_val=0.0, max_val=5.0)
                task.write(0)
            sleep(0.1)
            self.sn.histogram.measure(acqTime=self.max_time, savePTU=False)

            counts, bins = self.sn.histogram.getData()
            counts = counts[1]
            self.data = np.array([bins, counts]).T
            self.sigWorkerFinished.emit(None)
        except Exception as e:
            self.sigWorkerFinished.emit(e)
        

        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan("Dev1/ao3", min_val=0.0, max_val=5.0)
            task.write(3)
        sleep(0.1)

    @QtCore.Slot()
    def acquire_data_dummy(self):
        sleep(5)
        bins = np.arange(100)/10
        counts = np.random.random_integers(1,1000,len(bins))
        self.data = np.array([bins,counts]).T
        self.sigWorkerFinished.emit(None)
    
    def save_count_rate(self,root_dir):
        sleep(0.2)
        count_rate = self.sn.device.getCountRates()[0]
        data_storage = TextDataStorage(root_dir=root_dir,
                                       column_formats='.15e')

        column_headers = ['CountRate']
        timestamp = datetime.now()
        mstag = timestamp.strftime('%f')[:-3]
        nametag = f'{mstag}_PicoCountRate_raw'
        
        
        file_path, _, _ = data_storage.save_data(np.array([count_rate]),
                                                 # metadata=metadata,
                                                 nametag=nametag,
                                                 timestamp=timestamp,
                                                 column_headers=column_headers,
                                                 column_dtypes=float)

    def save_data(self,root_dir):
        data_storage = TextDataStorage(root_dir=root_dir,
                                       column_formats='.15e')

        column_headers = ['Bins','Counts']
        timestamp = datetime.now()
        mstag = timestamp.strftime('%f')[:-3]
        nametag = f'{mstag}_PicoLifetime_raw'
        

        file_path, _, _ = data_storage.save_data(self.data,
                                                 # metadata=metadata,
                                                 nametag=nametag,
                                                 timestamp=timestamp,
                                                 column_headers=column_headers,
                                                 column_dtypes=float)

        figure = plt.figure()
        plt.plot(self.data[:,0],self.data[:,1])
        plt.grid()
        plt.xlabel('ns')

        fig_path = f"{file_path.rsplit('_raw.', 1)[0]}"
        data_storage.save_thumbnail(figure, file_path=fig_path)