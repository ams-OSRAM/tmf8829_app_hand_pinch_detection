# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
"""This application does measurements using the TMF8829 sensor in dual mode with I3C and IBI support.

    ***************************************************************************
    *** WARNING : histograms cannot be read out currently with the H5 com.
    ***************************************************************************

"""

import __init__
import aos_com.ic_com as ic_com
from aos_com.h5_com import H5Com as HostCom
from aos_com.i3c_hal_register_io import I3cHalRegisterIo  as HostHal
from tmf8829_application import Tmf8829Application 
from tmf8829_application_registers import Tmf8829_application_registers as Tmf8829AppRegs
from utilities.tmf8829_application_printer import Tmf8829ApplicationPrinter
from tmf8829_application_defines import TMF8829_INT_HISTOGRAMS, TMF8829_INT_RESULTS
import time
from threading import Event     # used on the PC for interrupt handling

i3c_ibi_enable = { ic_com.I3C_CCC_ENEC: bytes([0x01]) } 
i3c_ibi_disable = { ic_com.I3C_CCC_DISEC: bytes([0x01]) } 


def findFileRoot():
    """Function searches for the file root in various places to be able to run it from different locations"""
    import os
    _file_root = ["..\\..\\..\\firmware\\application","..\\firmware\\application","firmware\\application"]  
    for _p in _file_root:
        if os.path.exists(_p):
            return _p
    return "."        

FILE_ROOT = findFileRoot()
HEX_FILE = "\\ROM_1V1_LINKED\\tmf8829_application.hex"
APP_ID = 0x01
BOOTLOADER_ID = 0x80
I3C_DYNAMIC_ADDRESS = 0x50


def tmf8829_ibi_isr_callback(target, msg_id, code, data):
    """This is the callback function that gets called when an I3C IBI is triggered. 
    It sets an event that the main thread is waiting on to read the data from the device.
    Args:
        target: The target number of the device- this is rpc specific .
        msg_id: The message ID of the IBI.
        code: An error code if there was an issue in the retrievel of the message or data.
        data: the data received with the IBI.
    """
    if code == None:
        _msg = ' '.join(f'{b:02X}' for b in data)
        print( "i3c ibi triggered for " + _msg)
    else:
        print( "i3c ibi error code {}".format(hex(code)) )
    event.set()


# main entry point of the application
event = Event()                                     # signaling between ISR and main thread for interrupt handling

# instanciate communciation, i3c HAL and Application.
com = HostCom(log=False,callback=tmf8829_ibi_isr_callback,callback_message_ids=[])
hal = HostHal(ic_com=com, dev_addr=I3C_DYNAMIC_ADDRESS)
app = Tmf8829Application( hal = hal, gpio_hal = hal)

# open communication, 
if not app.open( ):                                 # automatically does pull the enable pin low, so we need to pull enable pin high
    raise Exception("ERROR no communication, exiting") 

# enable TMF8829 and wait for bootloader 
app.enable(send_wake_up_sequence=False)
time.sleep(0.003)
app.blCmdSpiOff()                                   # disable SPI interface to use I3C

# download latest firmware patch to TMF8829
version = app.downloadAndStartApp( hex_file=FILE_ROOT+HEX_FILE, use_fifo=False, verify=False, app_id=APP_ID )
print( "APP {}.{}.{}.{}".format(int(version[0]),int(version[1]),int(version[2]),int(version[3])))
app.io.regWrite( app.reg.ENABLE, powerup_select = app.reg.ENABLE._powerup_select._RAM )     # make sure that we wakeup properly from standby-timed

# rotate through all avilable FP modes and perform xxx measurements in each mode
for fp_mode in [Tmf8829Application.FP_MODE_8x8A,Tmf8829Application.FP_MODE_16x16,Tmf8829Application.FP_MODE_32x32]:
    app.configure( period=33, fp_mode=fp_mode, signal_strength=0, xtalk=0, nr_peaks=1, iterations=600*12 )  # Warning: frames must be 
    app.configure( dual_mode=1, histograms=0, high_accuracy_iterations=400*12 ) # Warning: histograms cannot be read out currently with the H5 com in I3C mode.
    num_frames_per_measurement = app.numberOfFramesPerMeasurement()

    app.clearAndEnableInt( 0xFF )                                       # clear the interrupt status bits on the TMF8829 and enable them
    app.hal.i3cEnableIbi()                                              # enable the IBI on the TMF8829 device. 

    app.sendCommand(cmd = Tmf8829AppRegs.TMF8829_CMD_STAT._cmd_stat._CMD_MEASURE)
    print( "STARTED fpmode={}".format(fp_mode))

    for i in range(10):

        event.wait(timeout=10)                                          # this is the handshake with the ISR callback function at the top of this file
        if not event.is_set() :
            raise Exception("Timeout waiting for interrupt")
        event.clear()

        _interrupts = app.readAndClearInt(TMF8829_INT_RESULTS|TMF8829_INT_HISTOGRAMS)   # clear interrupt so that renambe of IBI does not trigger interrupt immediately again     
        app.hal.i3cEnableIbi()                                                          # enable the IBI on the TMF8829 device. 

        _frame, _ = app.readFrames(_interrupts)                 # now actually read the frame 
        if _frame != None:
            Tmf8829ApplicationPrinter.printFrame( frame=_frame, print_whole_frame=False)
        else:
            raise Exception("I3C No frame available")
                
    app.sendCommand(cmd = Tmf8829AppRegs.TMF8829_CMD_STAT._cmd_stat._CMD_STOP)
    app.hal.i3cDisableIbi()                                              # disable the IBI on the TMF8829 device.    
    print( "STOPPED")

app.disable()
app.close()
