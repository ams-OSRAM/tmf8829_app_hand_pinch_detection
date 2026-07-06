# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
"""
ZeroMQ client.
Start client and check for evm and shieldboard:
  - python .\tmf8829_zeromq_client.py
Start client and check for evm:
  - python .\tmf8829_zeromq_client.py evm
Start client and check for shieldboard:
  - python .\tmf8829_zeromq_client.py shieldboard
EXE file creation:
Shield board zeromq server instantiation for server EXE file creation.
Run deploy_shield_board_zmq_server.py do deploy a server executable.
"""
import __init__

import zmq
import ctypes
import time


from zeromq.tmf8829_zeromq_common import *
from tmf8829_application_defines import *

from tmf8829_application_registers import Tmf8829_application_registers as Tmf8829AppRegs
from tmf8829_config_page import Tmf8829_config_page as Tmf8829ConfigRegs
from aos_com.register_io import ctypes2Dict


from tmf8829_application_common import Tmf8829AppCommon
from utilities.tmf8829_logger_service import TMF8829Logger as Tmf8829Logger
from register_page_converter import RegisterPageConverter as RegConv
import sys
import os

class ZeroMqClient:
    """ZeroMQ client"""
   
    VERSION = 0x0004
    """Version 
    - 1 First zeromq client release version
    - 2 Second logger versions
        changes in logging format
    - 3 localhost and linuxhost check
        dual mode support
        point cloud correction
        version moved from client to logger
    - 4 option to save previous data also uncompressed (configuration changed at measurement)
        fix, check if filename exists also for gz files
        for storage use os pathname
        store 3d point cloud values and distance
    """

    def __init__(self) -> None:
        self._client_id = TMF8829_ZEROMQ_CLIENT_NOT_IDENTIFIED
        self._context = zmq.Context()
        self._cmd_socket = self._context.socket(zmq.REQ)
        self._result_socket = self._context.socket(zmq.SUB)
        self._is_measuring = False
        self._is_cfg_client = False
        self._cmd_socket.setsockopt(zmq.LINGER, 100) # after zmq close the Buffer should be cleared
        self._result_socket.setsockopt(zmq.CONFLATE, 1)  # discard old results

    def connect_local(self):
        """Connect to local host server."""
        self._cmd_socket.connect(TMF8829_ZEROMQ_CMD_SERVER_ADDR)
        self._result_socket.connect(TMF8829_ZEROMQ_RESULT_SERVER_ADDR)
        self._result_socket.setsockopt(zmq.SUBSCRIBE, b'')
        logger.info("Connect to local host server")

    def disconnect_local(self):
        """Disconnect from local host server."""
        self._cmd_socket.disconnect(TMF8829_ZEROMQ_CMD_SERVER_ADDR)
        self._result_socket.disconnect(TMF8829_ZEROMQ_RESULT_SERVER_ADDR)
        logger.info("Disconnect from local host server")

    def connect_linux(self):
        """Connect to linux server."""
        self._cmd_socket.connect(TMF8829_ZEROMQ_CMD_LINUX_SERVER_ADDR)
        self._result_socket.connect(TMF8829_ZEROMQ_RESULT_LINUX_SERVER_ADDR)
        self._result_socket.setsockopt(zmq.SUBSCRIBE, b'')
        logger.info("Connect to linux server")

    def disconnect_linux(self):
        """Disconnect from linux server."""
        self._cmd_socket.disconnect(TMF8829_ZEROMQ_CMD_LINUX_SERVER_ADDR)
        self._result_socket.disconnect(TMF8829_ZEROMQ_RESULT_LINUX_SERVER_ADDR)
        logger.info("Disconnect from linux server")

    def send_request(
            self,
            request: Tmf8829zeroMQRequestMessage,
            request_timeout: float = 1.0,
            response_timeout: float = 1.0) -> Tmf8829zeroMQResponseMessage:
        """
        Send a request to the server and wait for response.
        Args:
            request: Request message to send.
            request_timeout: Timeout for sending the request message in seconds.
            response_timeout: Timeout for receiving the response message in seconds.
        Returns:
            Response message.
        Raises:
            CommandError: Request failed.
            TimeoutError: When a timeout elapsed before the request message was sent or before the response message was
                received.
        """
        request_timeout_ms = int(request_timeout * 1000.0)
        if not self._cmd_socket.poll(request_timeout_ms, zmq.POLLOUT):
            raise TimeoutError("Could not send request message")
        logger.info(request.__str__()) 
        self._cmd_socket.send(request.to_buffer())
        #Get the reply.
        response_timeout_ms = int(response_timeout * 1000.0)
        if not self._cmd_socket.poll(response_timeout_ms, zmq.POLLIN):
             raise TimeoutError("No response message received")
        response = Tmf8829zeroMQResponseMessage(client_id=self._client_id,buffer=self._cmd_socket.recv(copy=True))
        logger.info(response.__str__())
        if response.error_code == Tmf8829zeroMQErrorCodes.NO_ERROR :
            return response
        elif response.error_code == Tmf8829zeroMQErrorCodes.NOT_CFG_CLIENT :
            logger.debug("WARNING: not the 1st client of zeroMQ server, can only log")
            return response
        else:
            raise Tmf8829zeroMQRequestError("Host send request failed with {}".format(response.error_code))

    def identify(self) -> tmf8829ZmqDeviceInfo:
        """
        Identify the EVM controller and the target sensor. Get a new client_id if don't have one yet.
        Returns:
            Device information
        Raises:
            CommandError: Identify request failed.
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.IDENTIFY))
        if self._client_id == TMF8829_ZEROMQ_CLIENT_NOT_IDENTIFIED:
            self._client_id = resp.client_id                                # store the newly given ID
        else:
            if self._client_id != resp.client_id:
                raise Tmf8829zeroMQRequestError("Identify, client-id={} differs from response itself={}".format(self._client_id,resp.client_id) )
        _device_info = tmf8829ZmqDeviceInfo.from_buffer_copy( resp.payload )
        if resp.error_code == Tmf8829zeroMQErrorCodes.NOT_CFG_CLIENT:
            self._is_cfg_client = False
            logger.info("ClientId={} Identify, LOGGER-ONLY client".format(self._client_id))
        else:
            self._is_cfg_client = True
            logger.info("ClientId={} Identify, CONFIG & LOGGER client".format(self._client_id))
        return _device_info

    def power_device(self, on_off: bytes) -> bool:
        """
        Power on or off the device.
        Args:
            on_off: 1 for on, 0 for off
        Returns:
            True: device is open
            False: device is closed
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.POWER_DEVICE,payload=on_off))
        return bool(resp.payload[0])

    def leave(self) -> bool:
        """
        Release the client ID, if this was the Config-Client than another client can grab the config ID from the server.
        Returns:
            True: if client was config client
            False: if client was not the config client
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.LEAVE))
        return bool(resp.payload[0])

    def start_measurement(self) -> bool:
        """
        Start measurement.
        Returns:
            True: if measurement is running
            False: else
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.START_MEASUREMENT))
        self._is_measuring = bool(resp.payload[0])
        return self._is_measuring

    def stop_measurement(self) -> bool:
        """
        Stop measurement.
        Returns:
            True: if no measurement is running anymore (stop was successfully executed - or not running at all)
            False: measurement still ongoing 
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.STOP_MEASUREMENT))
        self._is_measuring = bool(resp.payload[0])
        return self._is_measuring
    
    def get_config(self) -> bytes:
        """
        Get the configuration page data of the device.
        Returns:
            tmf8829 Configuration Registers data
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.GET_CONFIGURATION))
        return resp.payload

    def set_config(self, config_page: bytes) -> bool:
        """
        Set the configuration page data of the device.
        Args:
            config_page: tmf8829 Configuration Registers data
        Returns:
            True: if request has been processed by command server
            False: else
        """
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.SET_CONFIGURATION,payload=config_page))
        return bool(resp.payload[0])

    def get_result_data(self, timeout: float = 5.0) -> bytes:
        """
        Read result data.
        Args:
            timeout: Timeout in seconds.
        Returns:
            Result data.
        Raises:
            TimeoutError: When no result data is received before the timeout elapsed.
        """
        timeout_ms = int(timeout * 1000.0)
        if not self._result_socket.poll(timeout_ms, zmq.POLLIN):
            raise TimeoutError("No result data received")
        result_data = self._result_socket.recv()

        return result_data

    def set_pre_config(self, cmd: bytes) -> bool:
        """
        Set the preconfigure command to the device.
        CMD_LOAD_CFG_8X8, CMD_LOAD_CFG_8X8_LONG_RANGE, CMD_LOAD_CFG_8X8_HIGH_ACCURACY, CMD_LOAD_CFG_16X16, CMD_LOAD_CFG_16X16_HIGH_ACCURACY,
        CMD_LOAD_CFG_32X32, CMD_LOAD_CFG_32X32_HIGH_ACCURACY, CMD_LOAD_CFG_48X32, CMD_LOAD_CFG_48X32_HIGH_ACCURACY

        Args:
            command : preconfigure command CMD_LOAD_CFG_8X8 ... CMD_LOAD_CFG_48X32_HIGH_ACCURACY

        Returns:
            True: if request has been processed by command server
            False: else (not the first client that requested)
        """
        
        resp = self.send_request(Tmf8829zeroMQRequestMessage(client_id=self._client_id,request_id=Tmf8829zeroMQRequestId.SET_PRE_CONFIGURATION, payload=cmd))

        return bool(resp.payload[0])
    
####################################################################


class tmf8829_evm_connector:

    def __init__(self):
        """
        Get configuration from cfg_client.json, connect to EVM and configure device for measurement
        """
        self.debugMsg = False
        #####################################################
        ## Arguments 
        #####################################################
        self.use_linux_server = True
        self.use_shieldboard_server = True
        for arg in sys.argv[1:]:
            print ("arg: " + arg)
            if arg == "evm": # check only for linux server
                self.use_shieldboard_server = False
            if arg == "shieldboard": # check only for linux server
                self.use_linux_server = False
            break

        #####################################################
        ## CONFIGURATION - only valid if this client is 1st client for zeroMQ server 
        #####################################################
        self.default_client_cfg = {
            "measure_cfg": {},
            "logging": {"combined_results": True },
            "record_frames":3
        }
        #####################################################
        self.CONFIG_FILE = "./cfg_client.json"
        if self.use_linux_server:
            self.CONFIG_FILE = "/cfg_client.json"
        
        # exe or script
        if getattr(sys, 'frozen', False): 
            self.script_location = sys.executable
        else:
            self.script_location = os.path.abspath(__file__)
            # self.debugMsg = True
            
        self.script_location = os.path.dirname(self.script_location) 
    
        self.tmf8829logger = Tmf8829Logger()
        self.cfg = self.tmf8829logger.readCfgFile(filePathName=self.script_location + self.CONFIG_FILE, in_config=self.default_client_cfg)

        self.client = ZeroMqClient()
        self.localHostAvailable =False
        self.identify = False
        #####################################################
        # Local Host
        #####################################################
        if self.use_shieldboard_server:
            try:
                self.client.connect_local()
            except KeyboardInterrupt:
                print( "Exiting ... ")
                exit(0)

            # IDENTIFY - must be first command
            try:
                self.dev_info = self.client.identify()
                self.localHostAvailable =True
                self.identify = True
            except:
                self.localHostAvailable = False
                self.client.disconnect_local()
                print( "No connection to Shield board server !!!")
        
        #####################################################
        # Linux Host
        #####################################################
        if (self.localHostAvailable == False) and (self.use_linux_server == True):
            self.client = ZeroMqClient()
            try:
                self.client.connect_linux()
            except KeyboardInterrupt:
                print( "Exiting ... ")
                exit(0)
            try:
                self.dev_info = self.client.identify()
                self.identify = True
            except:
                self.client.disconnect_linux()
                print( "No connection to Evm board server !!!")
                time.sleep(2)
                exit(0)

        #####################################################
        if self.identify == False:
            exit(0)
        #####################################################

        print( "ClientID={}".format(self.client._client_id))
        print( ctypes2Dict(self.dev_info) )

        if "preconfig" in self.cfg:
            self.pre_config = "_" + self.cfg["preconfig"]
            logger.debug("Preconfig {}".format(self.pre_config))
            self.precmd = getattr(Tmf8829AppRegs.TMF8829_CMD_STAT._cmd_stat, self.pre_config, None)
            self.bprecmd =self.precmd.to_bytes(length=1,byteorder="little",signed=False)
            self.client.set_pre_config( cmd=self.bprecmd )

        # complete the user configuration with the device configuration
        self._cfg_bytes = self.client.get_config()                                        # get configuration as a bytestream from device
        self._cfg_dict = RegConv.readPageToDict(self._cfg_bytes, Tmf8829ConfigRegs())     # convert bytestream to dictionary
        Tmf8829Logger.patch_dict( self._cfg_dict, self.cfg["measure_cfg"] )               # external read config overwrites default config
        self._cfg_bytes2 = RegConv.readDictToPage( self._cfg_dict, Tmf8829ConfigRegs())   # bytearray
        if not self.client.set_config( self._cfg_bytes2 ):                                        # attempt to set configuration 
            print("Please start GUI after this script - this script need to configure TMF8829 on its own")
            time.sleep(2)
            exit(1)
        self._cfg_bytes = self.client.get_config()                                        # now in case we were not the 1st client, config might not have happened so read it back 
        self._cfg_dict = RegConv.readPageToDict(self._cfg_bytes, Tmf8829ConfigRegs())     # convert bytestream to dictionary
    
        if self.cfg["log_data"]:
            self.tmf8829logger.dumpConfiguration( self._cfg_dict )

        self.info = {}
        self.info["host version"] = list(self.dev_info.hostVersion)
        self.info["fw version"] = list(self.dev_info.fwVersion)
        self.info["logger version"] = self.client.VERSION
        self.info["serial number"] = self.dev_info.deviceSerialNumber
        if self.cfg["log_data"]:
            self.tmf8829logger.dumpInfo(self.info)

        if self._cfg_dict["select"] >= 1 and self.debugMsg:
            print("The result frames have the distance in 0.25mm, but will be logged in mm! ")
        
        self.cnt = 0

        self.started_measurement = False

    def measure(self):
        """
        Run a continuous measurement and return pixel results
        Log to file if configured
        """
        if self.started_measurement or self.client.start_measurement():  # start only the first time
            self.started_measurement = True
            try:
                zmq_result_data = self.client.get_result_data()
                zmqheader = tmf8829ContainerFrameHeader.from_buffer_copy(bytearray(zmq_result_data[0:ctypes.sizeof(tmf8829ContainerFrameHeader)]))
                if self.debugMsg:
                    print( ctypes2Dict(zmqheader))
                    print("zmq Result Frames:")
                resultFrame, histoFrames, refFrame = Tmf8829AppCommon.getFramesFromMeasurementResult(zmq_result_data[ctypes.sizeof(tmf8829ContainerFrameHeader):])
                if self.debugMsg:
                    for r in resultFrame:
                            fpMode = r[5]&TMF8829_FPM_MASK  
                            fId = r[5]&TMF8829_FID_MASK
                            print( "FID={}, FP={}, FNr={}".format(fId, fpMode, int.from_bytes(bytes=r[5+4:5+4+4],byteorder='little', signed=False)))

                self.cnt += 1
                if self.debugMsg:
                    print( "Set={} #resultFrames={} #histoFrames={} #refFrames={}".format(self.cnt,len(resultFrame),len(histoFrames),len(refFrame)))
                print(self.cnt, '\r', end="")  # stay pretty quiet

                self._toMM = False

                if self._cfg_dict["select"] >= 1:
                    self._toMM = True

                pixelResults = Tmf8829AppCommon.getFullPixelResult(frames=resultFrame, toMM=self._toMM, pointCloud=False, distanceToXYZ=True)

                # log the header of the first result frame
                fheader = tmf8829FrameHeader.from_buffer_copy( bytearray(resultFrame[0])[Tmf8829AppCommon.PRE_HEADER_SIZE: \
                            Tmf8829AppCommon.PRE_HEADER_SIZE+ctypes.sizeof(struct__tmf8829FrameHeader)])
                ffooter = tmf8829FrameFooter.from_buffer_copy( bytearray(resultFrame[0])[-ctypes.sizeof(struct__tmf8829FrameFooter):])

                res_info = {}
                res_info["frame_number"] = fheader.fNumber
                res_info["temperature"] = fheader.temperature[2]
                res_info["systick_t0"] = ffooter.t0Integration
                res_info["systick_t1"] = ffooter.t1Integration
                res_info["read_time"] = int.from_bytes( resultFrame[0][1:5],byteorder='little',signed=False )
                
                allframeStatus = 0
                for frame in histoFrames:
                    ffooter = tmf8829FrameFooter.from_buffer_copy( bytearray(frame)[-ctypes.sizeof(struct__tmf8829FrameFooter):])
                    allframeStatus |= ffooter.frameStatus
                for frame in resultFrame:
                    ffooter = tmf8829FrameFooter.from_buffer_copy( bytearray(frame)[-ctypes.sizeof(struct__tmf8829FrameFooter):])
                    allframeStatus |= ffooter.frameStatus

                res_info["warnings"] = allframeStatus & ~TMF8829_FRAME_VALID
                
                histogramResults = []
                refhistogramResults = []
                histogramResultsHA = []
                refhistogramResultsHA = []     
                
                if self._cfg_dict["histograms"] == 1:
                    if self._cfg_dict["dual_mode"] == 1:
                        refhistogramResultsHA, histogramResultsHA, \
                        refhistogramResults, histogramResults = Tmf8829AppCommon.getAllHistogramResultsDualMode(histoFrames)
                    else:
                        refhistogramResults, histogramResults = Tmf8829AppCommon.getAllHistogramResults(histoFrames)
                
                if self.cfg["log_data"]:
                    self.tmf8829logger.dumpMeasurement(pixel_results=pixelResults, \
                        pixel_histograms=histogramResults, reference_pixel_histograms=refhistogramResults,
                        pixel_histograms_HA=histogramResultsHA, reference_pixel_histograms_HA=refhistogramResultsHA,
                        reference_spad_frames=refFrame, measurement_info=res_info)
                                    
                return (pixelResults, res_info, histogramResults, refhistogramResults, histogramResultsHA, refhistogramResultsHA, refFrame)

            except KeyboardInterrupt:
                raise(KeyboardInterrupt)  # pass it to the caller
            except Exception as e:
                    if self.cfg["log_data"]:
                        self.tmf8829logger.dumpInfo({"Exception": "Get data from server"})
                    print( "Exception:Get data from server  !!!!!!", e)
        else:
            print( "Only Logger and no measurement is running, exiting")


    def stop_measurement(self):
        """
        Stop measurement 
        """
        self.started_measurement = False
        self.client.stop_measurement()


    def end_connection(self):
        """
        Finish measurement, close connection
        Save logfile if logging is enabled
        """

        try:
            self.client.stop_measurement()
            self.client.leave()  # if this client was config client free it again

            if self.localHostAvailable:
                self.client.disconnect_local()
            else:
                self.client.disconnect_linux()
        
        except Exception as e:
            if self.cfg["log_data"]:
                self.tmf8829logger.dumpInfo({"Exception": "Stop leave and disconnect from server"})
            print( "Exception: Stop Server !!!!!!", e)

        if self.cfg["log_data"]:
            self.tmf8829logger.dumpToJsonFile(compressed=False)

        print( "End" )
        time.sleep(2)


if __name__ == "__main__":

    import numpy as np

    # Configure NumPy to print the full array
    np.set_printoptions(threshold=np.inf, linewidth=np.inf)

    tmf8829_evm = tmf8829_evm_connector()

    for i in range(2):
        pixelResults, *_ = tmf8829_evm.measure()
        rows = len(pixelResults)
        cols = len(pixelResults[0])
        # extract z position (flat target corrected depth) of every pixel
        z_array = np.array([pixel['peaks'][0]['z'] for row in pixelResults for pixel in row]).reshape(cols, rows)
        print("Result")
        print(z_array)
    tmf8829_evm.end_connection()

    time.sleep(4)
