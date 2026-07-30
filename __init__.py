# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
""" Import this script to set up the python path.
"""

import os
import sys

TOF_PYTHON_ROOT_DIR = os.path.normpath(os.path.dirname(__file__) + "/tmf8829") 
"""Change this path depending on the relative path between this file and the TOF python root dir."""

if TOF_PYTHON_ROOT_DIR not in sys.path:
    sys.path.append(TOF_PYTHON_ROOT_DIR)
    sys.path.append(os.path.join(TOF_PYTHON_ROOT_DIR, 'zeromq'))

HEX_FILE = os.path.normpath( os.path.join(os.path.dirname(__file__), 'tmf8829', 'hex', 'tmf8829_application.hex') )