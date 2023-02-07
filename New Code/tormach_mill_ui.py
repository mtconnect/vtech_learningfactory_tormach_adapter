#!/usr/bin/env python
# coding=utf-8
#-----------------------------------------------------------------------
# Copyright © 2014-2018 Tormach® Inc. All rights reserved.
# License: GPL Version 2
#-----------------------------------------------------------------------

# NOTE:
# If you have wingdbstub.py laying around, but you're using PyCharm, then the python process will segfault
# on launch in ways that are hard to figure out.
# so make a decision on which debugger if you want one, and comment out the other entirely.
#
# for debugging within Wing IDE
#try:
#    import wingdbstub
#except ImportError:
#    pass

# for debugging with PyCharm
try:
    import pydevd
    # Uncomment the next line if you have the PyCharm debug server listening.
    # Otherwise, this line pauses the load by 30 seconds on every launch which is very annoying.
    #pydevd.settrace('localhost', port=43777)
except ImportError:
    pass

# This is our own tormach debug console, has nothing to do with Wing or PyCharm
#import debugconsole

from locsupport import *
# This is a temp definition of _ to make it visible to pylint without complaint.
# At runtime below it is deleted right away and the _ alias that the gettext module import creates takes over
def _(msgid):
    return msgid

import gtk
import glib
import gobject
import sys
import redis
import linuxcnc
import hal
import gremlin
import os
import pango
import subprocess
import math
import errno
import time
import csv
import re
import threading
import thread
import ppglobals
import fswatch
import logging
from conversational import cparse
import dbus
import ast
from iniparse import SafeConfigParser

try:
    from fontTools import ttLib
    is_ttlib = True
except:
    is_ttlib = False

# Tormach modules
from constants import *
import crashdetection
import gremlinbase
from errors import *
import timer
import mill_conversational
import mill_probe
import ui_settings_mill
import numpad
import popupdlg
import tormach_file_util
import zbot_atc
from ui_common import *
from ui_support import *
import singletons
import gremlin_options
import machine
import plexiglass
import traceback
import mill_fs
from d2g.panel import MillD2gPanel
import tooltipmgr

sys.path.append(os.path.join(LINUXCNC_HOME_DIR, 'python', 'scanner2'))
import scanner2

logging.basicConfig(level=logging.DEBUG, format='(%(threadName)-10s) %(message)s')

# this is for customization like clearing or setting USBIO outputs upon E-Stop event or Reset or Stop Button pressed
# only if this import is found in ~/gcode/python will its functions be called
try:
    import ui_hooks
except ImportError:
    pass

DRILL_TABLE_BASIC_SIZE = 100

# Helper list to keep track of the main notebook page IDs
__page_ids = [
    "notebook_main_fixed",
    "notebook_file_util_fixed",
    "notebook_settings_fixed",
    "notebook_offsets_fixed",
    "conversational_fixed",
    "atc_fixed",
    "probe_fixed",
    "scanner_fixed",
    "injector_fixed",
    "alarms_fixed"
]

FILTER_TOOL_TABLE_ALL_TOOLS = 1
FILTER_TOOL_TABLE_USED_BY_GCODE = 2
FILTER_TOOL_TABLE_NONBLANK_DESCRIPTIONS = 3
FILTER_TOOL_TABLE_NONZERO = 4

FILTER_WORK_OFFSETS_ALL = 1
FILTER_WORK_OFFSETS_USED_BY_GCODE = 2
FILTER_WORK_OFFSETS_NONBLANK_DESCRIPTIONS = 3
FILTER_WORK_OFFSETS_NONZERO = 4

JOB_TABLE_ROWS = 30

class AxisState:
    """Simple class to store GUI axis data in iterable types with a numerical index."""
    def __init__(self):
        self.letters = ['x','y','z','a']
        self.dros = ['%s_dro' % l for l in self.letters]
        self.dtg_labels = ['%s_dtg_label' % l for l in self.letters]
        self.referenced = [False for l in self.letters]
        self.at_limit_display = [False for l in self.letters]
        #KLUDGE: skipping A axis home switch the easy way until hal pins are added
        self.home_switches=['home-switch-%s' % l for l in self.letters[0:3]]
        self.limit_leds=['%s_limit_led' % l for l in self.letters]
        self.ref_buttons = ['ref_%s' % l for l in self.letters]
        self.jog_enabled_local = [False for l in self.letters]
        self.jog_active_leds=['jog_%s_active_led' % l for l in self.letters]


# global needed because static event callback method has no other data to go on unfortunately.
_mill_instance = None
class FontDirFSHandler(fswatch.FileSystemEventHandler):
    @staticmethod
    def on_modified(event):
        # This is called anytime the contents of the path that the Watcher is monitoring is modified (files or dirs come or go - but not recursively).
        # NOTE!
        # This callback is NOT on the GUI thread so you can't
        # manipulate any Gtk objects.  The only thing we can really do is schedule a callback to
        # the GUI thread using glib.idle_add.
        assert ppglobals.GUI_THREAD_ID != thread.get_ident()
        global _mill_instance
        glib.idle_add(mill.setup_font_selector, _mill_instance)


def engrave_font_name_search_callback(engrave_font_liststore, column, key, iter, mill):
    # the columns use markup text for display so the built-in searching
    # doesn't know how to ignore or parse out the markup
    row = engrave_font_liststore.get_path(iter)[0]
    if string.find(mill.font_file_list[row], key) != -1:
        return False   # match
    return True    # no match


def workoffset_treeview_search_function(model, column, searchkey, iter, data):
    workoffset, description, x, y, z, a = model.get(iter, 0, 1, 2, 3, 4, 5)
    if searchkey.upper() in workoffset.upper():
        return False
    if searchkey.upper() in description.upper():
        return False
    # when comparing numbers, we only match from the start of the number, not in the middle.
    if str(x).find(searchkey) == 0:
        return False
    if str(y).find(searchkey) == 0:
        return False
    if str(z).find(searchkey) == 0:
        return False
    if str(a).find(searchkey) == 0:
        return False
    return True


def tool_treeview_search_function(model, column, searchkey, iter, data):
    tool_num, description, diameter, length = model.get(iter, 0, 1, 2, 3)
    if searchkey.upper() in description.upper():
        return False
    # when comparing numbers, we only match from the start of the number, not in the middle.
    if str(tool_num).find(searchkey) == 0:
        return False
    if diameter.find(searchkey) == 0:
        return False
    if length.find(searchkey) == 0:
        return False
    return True


class mill(TormachUIBase):

    G_CODES = [
        { 'Name' : 'G0',    'Function' : 'Rapid positioning'                               },
        { 'Name' : 'G1',    'Function' : 'Linear interpolation'                            },
        { 'Name' : 'G2',    'Function' : 'Clockwise circular interpolation'                },
        { 'Name' : 'G3',    'Function' : 'Counter clockwise circular interpolation'        },
        { 'Name' : 'G4',    'Function' : 'Dwell'                                           },
        { 'Name' : 'G17',   'Function' : 'Selects the XY plane'                            },
        { 'Name' : 'G18',   'Function' : 'Selects the XZ plane'                            },
        { 'Name' : 'G19',   'Function' : 'Selects the YZ plane'                            },
        { 'Name' : 'G20',   'Function' : 'Inch unit'                                       },
        { 'Name' : 'G21',   'Function' : 'Millimeter unit'                                 },
        { 'Name' : 'G30',   'Function' : 'Go to pre-defined position'                      },
        { 'Name' : 'G30.1', 'Function' : 'Store pre-defined position'                      },
        { 'Name' : 'G40',   'Function' : 'Cancel radius compensation'                      },
        { 'Name' : 'G41',   'Function' : 'Start radius compensation left'                  },
#       { 'Name' : 'G41.1', 'Function' : 'Start dynamic radius compensation left'          },
        { 'Name' : 'G42',   'Function' : 'Start radius compenstation right'                },
#       { 'Name' : 'G42.1', 'Function' : 'Start dynamic radius compensation right'         },
        { 'Name' : 'G54',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G55',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G56',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G57',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G58',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G59',   'Function' : 'Work offset coordinate system'                   },
        { 'Name' : 'G73',   'Function' : 'Canned cycle - drilling with chip-break'         },
        { 'Name' : 'G80',   'Function' : 'Cancel canned cycle mode'                        },
        { 'Name' : 'G81',   'Function' : 'Canned cycle - drilling'                         },
        { 'Name' : 'G82',   'Function' : 'Canned cycle - drilling with dwell'              },
        { 'Name' : 'G83',   'Function' : 'Canned cycle - peck drilling'                    },
#       { 'Name' : 'G85',   'Function' : 'Canned cycle - boring, feed out'                 },
        { 'Name' : 'G86',   'Function' : 'Canned cycle - boring, spindle stop, rapid out'  },
#       { 'Name' : 'G88',   'Function' : 'Canned cycle - boring, spindle stop, manual out' },
        { 'Name' : 'G89',   'Function' : 'Canned cycle - boring, dwell, feed out'          },
        { 'Name' : 'G90',   'Function' : 'Absolute distance mode'                          },
        { 'Name' : 'G91',   'Function' : 'Incremental distance mode'                       },
        { 'Name' : 'G90.1', 'Function' : 'I,J,K absolute distance mode'                    },
        { 'Name' : 'G91.1', 'Function' : 'I,J,K incremental distance mode'                 },
        { 'Name' : 'G93',   'Function' : 'Feed inverse time mode'                          },
        { 'Name' : 'G94',   'Function' : 'Feed per minute mode'                            },
        { 'Name' : 'G95',   'Function' : 'Feed per revolution mode'                        },
#       { 'Name' : 'G96',   'Function' : 'Constant surface speed mode'                     },
        { 'Name' : 'G97',   'Function' : 'RPM mode'                                        },
        { 'Name' : 'G98',   'Function' : 'Retract to initial Z height'                     },
        { 'Name' : 'G99',   'Function' : 'Retract to R height'                             }]

    _report_status = [linuxcnc.G_CODE_ORIGIN,
                      linuxcnc.G_CODE_DISTANCE_MODE,
                      linuxcnc.G_CODE_UNITS,
                      linuxcnc.G_CODE_MOTION_MODE,
                      linuxcnc.G_CODE_CUTTER_SIDE,
                      linuxcnc.G_CODE_FEED_MODE,
                      linuxcnc.G_CODE_SPINDLE_MODE,
                      linuxcnc.G_CODE_RETRACT_MODE,
                      linuxcnc.G_CODE_DISTANCE_MODE_IJK]

    _max_tool_number = MAX_NUM_MILL_TOOL_NUM
    _min_tool_number = 0

    def __init__(self):
        # glade setup
        gladefile = os.path.join(GLADE_DIR, 'tormach_mill_ui.glade')
        ini_file_name = sys.argv[2]

        TormachUIBase.__init__(self, gladefile, ini_file_name)

        # --------------------------------------------------------
        # linuxcnc command and status objects
        # --------------------------------------------------------
        self.command = linuxcnc.command()
        self.status = linuxcnc.stat()
        self.error = linuxcnc.error_channel()

        self.machine_type = MACHINE_TYPE_MILL

        self.program_exit_code = EXITCODE_SHUTDOWN
        self.DRILL_LIST_BASIC_SIZE =int(DRILL_TABLE_BASIC_SIZE)
        self.DRILL_TABLE_ROWS = int(DRILL_TABLE_BASIC_SIZE)


        #####################################################################
        # Initialization steps that don't depend on GTK

        # Define sets of keys that are disabled depending on the current page
        self.setup_key_sets()

        # be defensive if stuff exists in glade file that can't be found in the source anymore!
        missing_signals = self.builder.connect_signals(self)
        if missing_signals is not None:
            raise RuntimeError("Cannot connect signals: ", missing_signals)

        # -------------------------------------------------------------
        # HAL setup.  Pins/signals must be connected in POSTGUI halfile
        # -------------------------------------------------------------

        self.hal.newpin("coolant", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("coolant-iocontrol", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("mist", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("mist-iocontrol", hal.HAL_BIT, hal.HAL_IN)

        #TODO: ATC timing debugging, remove
        #self.hal.newpin("hal-spindle-lock", hal.HAL_BIT, hal.HAL_IN)
        #self.hal.newpin("hal-pdb-on", hal.HAL_BIT, hal.HAL_IN)
        #self.hal.newpin("hal-trayin", hal.HAL_BIT, hal.HAL_IN)

        self.hal.newpin("jog-axis-x-enabled", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("jog-axis-y-enabled", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("jog-axis-z-enabled", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("jog-axis-a-enabled", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("jog-step-button", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("jog-counts", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("jog-ring-speed-signed", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("jog-ring-selected-axis", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("jog-gui-step-index", hal.HAL_U32, hal.HAL_OUT)
        self.hal.newpin("jog-is-metric", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-1", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-2", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-3", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-4", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-5", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-6", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("jog-ring-speed-7", hal.HAL_FLOAT, hal.HAL_OUT)

        self.hal.newpin("motion-program-line", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("motion-next-program-line", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("motion-completed-program-line", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("motion-motion-type", hal.HAL_S32, hal.HAL_IN)

        self.hal.newpin("spindle-range", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("spindle-range-alarm", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("spindle-type", hal.HAL_S32, hal.HAL_OUT)
        self.hal.newpin("spindle-hispeed-min", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("spindle-hispeed-max", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("spindle-min-speed", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("spindle-max-speed", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("spindle-disable", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("spindle-on", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("spindle-set-bt30", hal.HAL_BIT, hal.HAL_IO)
        self.hal.newpin("spindle-orient-fault", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("spindle-zindex-state", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("spindle-bt30-offset", hal.HAL_S32, hal.HAL_IO)
        self.hal.newpin("spindle-at-speed", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("m200-vfd-rpm-feedback", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("spindle-fault", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("vfd-fault", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("pp-estop-fault", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("zindex-test", hal.HAL_BIT, hal.HAL_OUT)

        # enclosure door switch
        self.hal.newpin("enc-door-switch-enabled", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("enc-door-open-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("enc-door-open-max-rpm", hal.HAL_FLOAT, hal.HAL_OUT)

        # the new enclosure door sensor+lock assembly needs lock pins
        self.hal.newpin("enc-door-lock-drive", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("enc-door-locked-status", hal.HAL_BIT, hal.HAL_IN)

        # height gauge
        self.hal.newpin('hg-height', hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin('hg-zero-offset', hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin('hg-button-changed', hal.HAL_BIT, hal.HAL_IO)
        self.hal.newpin('hg-button-pressed', hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin('hg-mm-mode', hal.HAL_BIT, hal.HAL_IO)
        self.hal.newpin('hg-set-zero-offset', hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin('hg-present', hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin('hg-debug', hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin('hg-enable', hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin('hg-has-zero-button', hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("probe-active-high", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("probe-enable", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("probe-sim", hal.HAL_BIT, hal.HAL_OUT)
        self.zero_height_gauge_visible = True

        self.hal.newpin("acc-input-port2", hal.HAL_BIT, hal.HAL_IN)

        self.hal.newpin("mesa-watchdog-has-bit", hal.HAL_BIT, hal.HAL_IO)
        self.hal.newpin("cycle-time-hours", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("cycle-time-minutes", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("cycle-time-seconds", hal.HAL_U32, hal.HAL_IN)

        self.hal.newpin("run-time-hours", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("run-time-minutes", hal.HAL_U32, hal.HAL_IN)
        self.hal.newpin("run-time-seconds", hal.HAL_U32, hal.HAL_IN)

        # commanded speed feedback for Spindle DROs during g code program exectuion
        self.hal.newpin("spindle-speed-out", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("machine-ok", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("home-switch-x", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("home-switch-y", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("home-switch-z", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("home-switch-enable", hal.HAL_BIT, hal.HAL_OUT)

        self.hal.newpin("x-status-code", hal.HAL_S32, hal.HAL_IO)
        self.hal.newpin("y-status-code", hal.HAL_S32, hal.HAL_IO)
        self.hal.newpin("z-status-code", hal.HAL_S32, hal.HAL_IO)

        self.hal.newpin("x-motor-command", hal.HAL_S32, hal.HAL_IO)
        self.hal.newpin("y-motor-command", hal.HAL_S32, hal.HAL_IO)
        self.hal.newpin("z-motor-command", hal.HAL_S32, hal.HAL_IO)

        self.hal.newpin("x-motor-state", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("y-motor-state", hal.HAL_S32, hal.HAL_IN)
        self.hal.newpin("z-motor-state", hal.HAL_S32, hal.HAL_IN)

        #atc pins
        self.hal.newpin("atc-hal-request", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("atc-hal-data", hal.HAL_FLOAT, hal.HAL_OUT)
        self.hal.newpin("atc-hal-return", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("atc-hal-busy",hal.HAL_BIT,hal.HAL_IN)
        self.hal.newpin("atc-device-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-pressure-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-tray-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-vfd-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-draw-status", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-tray-position", hal.HAL_FLOAT, hal.HAL_IN)
        self.hal.newpin("atc-ngc-running", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("atc-tools-in-tray", hal.HAL_U32,hal.HAL_IN)
        self.hal.newpin("atc-trayref-status", hal.HAL_BIT, hal.HAL_IN)

        # usbio board pins for boards 0, 1, 2, 3 (if present)
        self.hal.newpin("usbio-enabled", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("usbio-input-0", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-1", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-2", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-3", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-4", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-5", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-6", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-7", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-8", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-9", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-10", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-11", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-12", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-13", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-14", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-input-15", hal.HAL_BIT, hal.HAL_IN)

        self.hal.newpin("usbio-output-0", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-1", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-2", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-3", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-4", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-5", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-6", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-7", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-8", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-9", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-10", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-11", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-12", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-13", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-14", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-output-15", hal.HAL_BIT, hal.HAL_IN)

        # usbio status for all boards as a group
        self.hal.newpin("usbio-status",hal.HAL_S32, hal.HAL_IN)

        self.hal.newpin("usbio-board-0-present",hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-board-1-present",hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-board-2-present",hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("usbio-board-3-present",hal.HAL_BIT, hal.HAL_IN)

        #manual control of smart_cool nozzle - hot key connected
        self.hal.newpin("smart-cool-man-auto", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("smart-cool-up", hal.HAL_BIT, hal.HAL_OUT)
        self.hal.newpin("smart-cool-down", hal.HAL_BIT, hal.HAL_OUT)

        self.hal.newpin("pc-ok-LED", hal.HAL_BIT, hal.HAL_OUT)

        # prompting communication - all responses to Gremlin messages or NGC prompts set this pin
        #   used by ATC
        self.hal.newpin("prompt-reply", hal.HAL_FLOAT, hal.HAL_OUT)

        # Pins to allow for monitoring of axis homing
        self.hal.newpin("axis-0-homing", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("axis-1-homing", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("axis-2-homing", hal.HAL_BIT, hal.HAL_IN)
        self.hal.newpin("axis-3-homing", hal.HAL_BIT, hal.HAL_IN)

        self.hal.ready()

        # -------------------------------------------------------
        # PostGUI HAL
        # -------------------------------------------------------

        # The postgui is dependent on a number of hal user space components being created and ready and
        # there can be timing variances where the postgui runs and the pin isn't quite ready yet to be connected
        # by signal.
        if not self.pause_for_user_space_comps(("zbotatc", "remap")):
            self.error_handler.log("Error: something failed waiting for user comps to be ready - aborting")
            sys.exit(1)

        postgui_halfile = self.inifile.find("HAL", "POSTGUI_HALFILE")
        if postgui_halfile:
            if subprocess.call(["halcmd", "-i", sys.argv[2], "-f", postgui_halfile]):
                self.error_handler.write("Error: something failed running halcmd on '" + postgui_halfile + "'", ALARM_LEVEL_DEBUG)
                sys.exit(1)
        else:
            # complain about missing POSTGUI_HALFILE
            self.error_handler.write("Error: missing POSTGUI_HALFILE in .INI file.", ALARM_LEVEL_DEBUG)
            sys.exit(1)

        # configure the ShuttleXpress (if preset)
        postgui_shuttlexpress_halfile = self.inifile.find("HAL", "POSTGUI_SHUTTLEXPRESS_HALFILE")
        if postgui_shuttlexpress_halfile:
            if subprocess.call(["halcmd", "-i", sys.argv[2], "-f", postgui_shuttlexpress_halfile]):
                self.error_handler.write("Warning: something failed running halcmd on '" + postgui_shuttlexpress_halfile + "'", ALARM_LEVEL_DEBUG)
        else:
            # complain about missing POSTGUI_SHUTTLEXPRESS_HALFILE
            self.error_handler.write("Warning: missing POSTGUI_SHUTTLEXPRESS_HALFILE in .INI file.", ALARM_LEVEL_DEBUG)

        # can't set any of these until after postguihal when pins are connected
        self.hal['hg-debug'] = 0
        self.hal['hg-mm-mode'] = 0

        self.hal['debug-level'] = 0

        # create a list of image object names
        #TODO move scanner images to scanner_gui_init
        image_set = ('cycle_start_image', 'single_block_image', 'm01_break_image', 'feedhold_image',
                           'coolant_image', 'ccw_image', 'cw_image', 'spindle_range_image', 'spindle_override_100_image',
                           'feed_override_100_image', 'maxvel_override_100_image', 'reset_image', 'jog_inc_cont_image',
                           'ref_x_image', 'ref_y_image', 'ref_z_image', 'ref_a_image',
                           'jog_zero_image', 'jog_one_image', 'jog_two_image', 'jog_three_image',
                           'jog_x_active_led', 'jog_y_active_led', 'jog_z_active_led', 'jog_a_active_led',
                           'm6_g43_image',
                           'tool_touch_chuck', 'touch_z_image',
                           'set_g30_image', 'x_limit_led', 'y_limit_led', 'z_limit_led',
                           'touch_entire_tray_ets_image', 'acc_input_led',
                           'acc_input_port2_led',
                           'probe_sensor_set_image',
                           'ets_image',
                           'injection_molder_image', 'door_sw_led', 'machine_ok_led',
                           'door_lock_led',
                           'usbio_input_0_led', 'usbio_input_1_led', 'usbio_input_2_led', 'usbio_input_3_led',
                           'usbio_output_0_led', 'usbio_output_1_led', 'usbio_output_2_led', 'usbio_output_3_led',
                           'LED_button_green', 'LED_button_black',
                           'face_spiral_rect_btn_image',
                           'thread_mill_ext_int_btn_image',
                           'drill_tap_btn_image',
                           'drill_tap_detail_image', 'drill_tap_main_image',
                           'drill_tap_clear_table_btn_image',
                           'drill_tap_raise_in_table_btn_image', 'drill_tap_lower_in_table_btn_image',
                           'conv_face_main_image',
                           'pocket_rect_circ_btn_image', 'profile_rect_circ_btn_image', 'conv_pocket_main_image', 'conv_profile_main_image', 'thread_mill_main_image',
                           'thread_mill_detail_image',
                           'atc_remove_image', 'atc_insert_image', 'atc_drawbar_image', 'atc_blast_image', 'set_tool_change_z_image', 'set_tool_change_m19_image', 'atc_tray_image',
                           'tray_in_led', 'vfd_running_led', 'vfd_fault_led', 'pressure_sensor_led',
                           'scanner_camera_on_off_image', 'scanner_camera_snap_image',
                           'scanner_status_update_image', 'scanner_scan_start_image',
                           'scanner_calibration_set_p1_image', 'scanner_calibration_set_p2_image',
                           'scanner_calibration_zoom_p1_image', 'scanner_calibration_zoom_p2_image',
                           'scanner_scope_capture_image', 'cam_post_to_file_image', 'finish-editing-button', 'internet_led', 'expandview_button_image',
                           'export_tool_table_image', 'import_tool_table_image')

        # create dictionary of key value pairs of image names, image objects
        # creating the dict this way lets us add named images at runtime that aren't in the glade file
        # like the door_lock_led which simply leverage the same led pixbufs as the other leds
        self.image_list = {}
        for name in image_set:
            self.image_list[name] = self.builder.get_object(name)
            if not self.image_list[name]:
                self.image_list[name] = gtk.Image()

        # Start to encapsulate machine config specifics in one place
        self.machineconfig = machine.MachineConfig(self, self.configdict, self.redis, self.error_handler, self.inifile)

        # settings tab init
        if self.machineconfig.model_name() == '440':
            self.settings = ui_settings_mill.mill_440_settings(self, self.redis, 'mill_440_settings.glade')
        else:
            self.settings = ui_settings_mill.mill_settings(self, self.redis, 'mill_settings.glade')

        tablabel = gtk.Label()
        tablabel.set_markup('<span weight="regular" font_desc="Roboto Condensed 10" foreground="black">Settings</span>')
        self.notebook.insert_page(self.settings.fixed, tab_label=tablabel, position=2)
        self.settings.fixed.put(self.gcodes_display.sw, 10, 10)

        self.hal['spindle-type'] = self.settings.spindle_type
        self.hal['spindle-hispeed-min'] = self.settings.spindle_hispeed_min
        self.hal['spindle-hispeed-max'] = self.settings.spindle_hispeed_max

        self.pc_ok_LED_status = 0

        # probe tab init
        self.mill_probe = mill_probe.mill_probe(self, self.redis, self.status, self.issue_mdi, 'mill_probe.glade')
        self.probe_notebook = self.mill_probe.notebook
        self.notebook.insert_page(self.mill_probe.fixed, self.mill_probe.tab_label, self.notebook.get_n_pages()-2)

        self.offsets_notebook = self.builder.get_object("offsets_notebook")
        self.fixed = self.builder.get_object("fixed")
        self.tool_offsets_fixed = self.builder.get_object("tool_offsets_fixed")
        self.work_offsets_fixed = self.builder.get_object("work_offsets_fixed")
        self.conv_drill_tap_pattern_notebook_fixed = self.builder.get_object("conv_drill_tap_pattern_notebook_fixed")
        self.conv_drill_tap_pattern_notebook = self.builder.get_object("conv_drill_tap_pattern_notebook_type")
        self.atc_fixed = self.builder.get_object("atc_fixed")
        self.conv_engrave_fixed  = self.builder.get_object("conv_engrave_fixed")
        self.camera_notebook     = self.builder.get_object("camera_notebook")

        # throw out mousewheel events to prevent scrolling through notebooks on wheel
        self.notebook.connect("scroll-event", self.on_mouse_wheel_event)
        self.conv_notebook.connect("scroll-event", self.on_mouse_wheel_event)
        self.offsets_notebook.connect("scroll-event", self.on_mouse_wheel_event)

        self.last_gcode_program_path = ''  #save this after loading program

        # max feedrate for user entry validation (in machine setup units - ipm)
        self.max_feedrate = 60 * self.ini_float('AXIS_0', 'MAX_VELOCITY', 135)

        # trajmaxvel from ini for maxvel slider
        self.maxvel_lin = self.ini_float('TRAJ', 'MAX_VELOCITY', 3)
        self.maxvel_ang = self.ini_float('TRAJ', 'MAX_ANGULAR_VELOCITY', 22)

        # axis max velocities for jog speed clamping on servo (M+ or MX) machines
        self.axis_unhomed_clamp_vel = {0:0, 1:0, 2:0, 3:0}
        self.axis_unhomed_clamp_vel[0] = self.ini_float('AXIS_0', 'MAX_VELOCITY', 0) * AXIS_SERVOS_CLAMP_VEL_PERCENT
        self.axis_unhomed_clamp_vel[1] = self.ini_float('AXIS_1', 'MAX_VELOCITY', 0) * AXIS_SERVOS_CLAMP_VEL_PERCENT
        self.axis_unhomed_clamp_vel[2] = self.ini_float('AXIS_2', 'MAX_VELOCITY', 0) * AXIS_SERVOS_CLAMP_VEL_PERCENT
        # toss the 4th axis in here so that we have less special case code later on
        self.axis_unhomed_clamp_vel[3] = self.ini_float('AXIS_3', 'MAX_VELOCITY', 0)

        # errors
        # ready to create real error handler that is more capable.  just replace the basic one, the API is the same.
        self.error_handler = error_handler(self.builder, self.moving)
        self.update_mgr.error_handler = self.error_handler
        self.mill_probe.set_error_handler(self.error_handler)

        # call this after error_handler is set
        self.mill_probe.read_persistent_storage()


        # --------------------------------------------------------
        # conversational
        # --------------------------------------------------------
        # spindle max/min are used by conversational DROs for validation
        # and the main UI DRO
        # spindle info can change at runtime as 'speeder' or 'hispeed' is selected
        # so do not rely on ranges being static in conversational checks
        # use the provided HAL min/max speeds that the spindle component maintains
        # based upon spindle type and current belt position
        #
        self.conversational = mill_conversational.conversational(self,
                                                                 self.status,
                                                                 self.error_handler,
                                                                 self.redis,
                                                                 self.hal)
        self.font_file_list = []

        # start with the coolant and mist off
        self.prev_coolant_iocontrol = self.prev_mist_iocontrol = self.hal['coolant'] = self.hal['mist'] = 0
        self.coolant_status = self.mist_status = 0
        self.coolant_ticker = self.mist_ticker = 0
        self.coolant_apply_at = self.mist_apply_at = 0
        self.hardkill_coolant = False   # RESET/STOP kills coolant hard

        #smart cool manual override state -
        self.smart_overriding = False

        # optional UI hooks for reset/stop buttons and estop events
        self.version_list = versioning.GetVersionMgr().get_version_list()
        self.ui_hooks = None
        try:
            self.ui_hooks = ui_hooks.ui_hooks(self.command, self.error_handler, self.version_list, digital_output_offset=0)
        except NameError:
            self.error_handler.write("optional ui_hooks module not found", ALARM_LEVEL_DEBUG)


        set_packet_read_timeout(self.inifile)

        # --------------------------------------------------------
        # config label - 1100 series 1,2,3, 770s, 440
        # --------------------------------------------------------

        tooltipmgr.TTMgrInitialize(ui=self, window=self.window, builder_list=[self.builder, self.mill_probe.builder])
        tooltipmgr.TTMgr().global_activate(self.settings.extended_tooltips_enabled)
        self.update_tooltipmgr_timers()

        config_label = self.builder.get_object('config_label')
        config_label.modify_font(pango.FontDescription('Bebas ultra-condensed 8'))
        text = self.machineconfig.model_name()
        if self.machineconfig.is_sim():
            text += " SIM"
        config_label.set_text(text)

        # Machine characteristics - used by conversational feeds and speeds
        self.mach_data = { "max_ipm" : self.max_feedrate, "motor_curve": None}

        # Motor curves - its a tuple of tuples
        # The inner tuples are RPM (int) and HP (float)
        # The curve can have as many points as desired, to date they all happen to have 4 points defined.

        # We have to use the real SafeConfigParser to read the power curves because they can use the
        # interpolation feature of ini files to refer to other key values within the same section.
        # The LinuxCNC self.inifile object doesn't know how to do that.
        cp = SafeConfigParser()
        cp.read(ini_file_name)
        powercurve = cp.get('SPINDLE', 'LO_POWER_CURVE')
        self.mach_data_lo = ast.literal_eval(powercurve)
        powercurve = cp.get('SPINDLE', 'HI_POWER_CURVE')
        self.mach_data_hi = ast.literal_eval(powercurve)

        if not self.machineconfig.shared_xy_limit_input():
            # these machines have tons of IO and never require any special
            # wiring changes when adding a door switch and lock assembly.
            self.redis.hset('machine_prefs', 'display_door_sw_x_ref_warning', 'False')

        # ready to create real error handler that is more capable.  just replace the basic one, the API is the same.
        self.error_handler = error_handler(self.builder, self.moving)

        if self.machineconfig.is_sim():
            probe_button = gtk.Button("Probe - lo ")
            probe_button.connect("button_press_event", self.on_probe_sim_button_press)
            probe_button.set_size_request(80, 30)
            # uncomment the line below to get a simulated "probe" button on the screen


        # --------------------------------------------------------
        # gremlin tool path display setup
        # --------------------------------------------------------

        GREMLIN_INITIAL_WIDTH = 680
        self.gremlin = Tormach_Mill_Gremlin(self, GREMLIN_INITIAL_WIDTH, 410)
        self.notebook_main_fixed.put(self.gremlin, 322, 0)
        # resize the message line so that it matches the width of the gremlin
        self.message_line.set_size_request(GREMLIN_INITIAL_WIDTH, 35)
        self.notebook_main_fixed.put(self.message_line, 322, 375)
        self.clear_message_line_text()

        self.notify_at_cycle_start = False  # when message text superimposed in Gremlin
        self.notify_answer_key = ''
        self.only_one_cable_warning = False  # warn when false

        # elapsed time label on top of gremlin
        # the Gtk fixed container doesn't support control over z-order of overlapping widgets.
        # so the behavior we get is arbitrary and seems to depend on order of adding the
        # widget to the container.  sweet.
        self.notebook_main_fixed.put(self.elapsed_time_label, 928, 390)
        self.notebook_main_fixed.put(self.remaining_time_label, 928, 370)
        self.notebook_main_fixed.put(self.preview_clipped_label, 904, 0)

        # add the correct gcode options for mills
        tablabel = gtk.Label()
        tablabel.set_markup('<span weight="regular" font_desc="Roboto Condensed 10" foreground="black">View Options</span>')

        self.gremlin_options = gremlin_options.gremlin_options(self, 'mill_gremlin_options.glade')
        self.gremlin_options.update_ui_view()
        self.gremlin_options.update_grid_size('med')
        self.gremlin.init_fourth_axis()
        self.gcode_options_notebook.append_page(self.gremlin_options.fixed, tab_label=tablabel)
        self.gcode_options_notebook.connect("switch-page", self.gcodeoptions_switch_page)

        # ---------------------------------------------
        # member variable init
        # ---------------------------------------------
        self.mach_data['motor_curve'] = self.mach_data_hi # this needs to be initialized to something

        # Make Feeds and Speeds manager construction explicit and controlled
        self.fs_mgr = mill_fs.MillFS(uiobject=self)
        self.material_data = ui_support.MaterialData(self, self.builder.get_object('conversational_fixed'))

        # Set initial toggle button states
        self.axes = AxisState()

        self.status.poll()

        self.error_handler.write("Mill __init__ after initial status.poll() - tool in spindle is %d" % self.status.tool_in_spindle, ALARM_LEVEL_DEBUG)

        self.first_run = True
        self.estop_alarm = True
        self.display_estop_msg = False
        self.interp_alarm = False
        self.single_block_active = False
        self.feedhold_active = threading.Event()
        self.m01_break_active = self.status.optional_stop
        self.spindle_direction = self.prev_spindle_direction = self.status.spindle_direction
        self.x_referenced = self.prev_x_referenced = 0
        self.y_referenced = self.prev_y_referenced = 0
        self.z_referenced = self.prev_z_referenced = 0
        self.a_referenced = self.prev_a_referenced = 0
        self.door_open_status = self.prev_door_open_status = False
        self.door_locked_status = False
        self.program_paused_for_door_sw_open = False
        self.probe_tripped_display = False
        self.notebook_locked = False
        self.dros_locked = False
        self.key_release_count = 0
        self.is_gcode_program_loaded = False
        self.prev_notebook_page_id = 'notebook_main_fixed'
        self.F1_page_toggled = False
        self.tlo_mismatch_count = 0    # track sucessive TLO misalignment
        self.cpu_usage = 0
        self.engrave_just = 'left'
        self.thread_mill_rhlh = 'right'
        self.tool_liststore_stale = 0
        self.current_g5x_offset = self.status.g5x_offset
        self.current_g92_offset= self.status.g92_offset

        self.conv_face_spiral_rect = 'spiral'
        self.conv_thread_mill_ext_int = 'external'
        self.conv_thread_mill_retract = 'minimal' #'minimal' or 'center'
        self.conv_drill_tap = 'drill'
        self.conv_pocket_rect_circ = 'rect'
        self.conv_profile_rect_circ = 'rect'
        self.conv_engrave_flat_circ = 'flat'
        self.conv_dxf_flat_circ = 'flat'

        self.scope_circle_dia = 30
        self.scope_row = 0

        self.tap_2x_enabled = False


        # -------------------------------------------------
        # Buttons (gtk.eventbox)
        # -------------------------------------------------

        # gtk.eventboxes
        self.button_list = ('cycle_start', 'single_block', 'm01_break', 'feedhold', 'stop', 'coolant', 'reset',
                            'feedrate_override_100', 'rpm_override_100', 'maxvel_override_100', 'jog_inc_cont',
                            'ref_x', 'ref_y', 'ref_z', 'ref_a',
                            'zero_x', 'zero_y', 'zero_z', 'zero_a',
                            'jog_zero', 'jog_one', 'jog_two', 'jog_three',
                            'ccw', 'spindle_stop', 'cw', 'spindle_range', 'm6_g43',
                            'set_g30', 'goto_g30', 'touch_z',
                            'exit',
                            'logdata_button',
                            'atc_insert', 'atc_delete', 'atc_delete_all', 'atc_tray_forward', 'atc_tray_reverse',
                            'atc_goto_tray_load', 'atc_retract', 'atc_drawbar', 'atc_blast', 'atc_ref_tray',
                            'atc_minus_minus', 'atc_plus_plus', 'atc_remove', 'atc_rev', 'atc_fw',
                            'atc_store', 'atc_touch_entire_tray', 'atc_set_tool_change_z', 'atc_set_tool_change_m19',
                            'inject',
                            'post_to_file', 'append_to_file', 'update', 'exit', 'clear', 'zero_height_gauge',
                            'move_and_set_tool_length',
                            'move_and_set_work_offset',
                            'face_spiral_rect',
                            'thread_mill_ext_int',
                            'drill_tap', 'drill_tap_clear_table',
                            'drill_tap_lower_in_table', 'drill_tap_raise_in_table',
                            'drill_tap_insert_row_table','drill_tap_delete_row_table',
                            'profile_rect_circ',
                            'pocket_rect_circ',
                            'scanner_camera_on_off', 'scanner_camera_snap',
                            'scanner_status_update', 'scanner_scan_start',
                            'scanner_calibration_set_p1', 'scanner_calibration_set_p2',
                            'scanner_calibration_zoom_p1', 'scanner_calibration_zoom_p2',
                            'scanner_scope_capture', 'cam_post_to_file','expandview_button',
                            'usbio_output_0_led_button', 'usbio_output_1_led_button', 'usbio_output_2_led_button', 'usbio_output_3_led_button',
                            'internet_led_button', 'export_tool_table', 'import_tool_table')

        # create dictionary of glade names, eventbox objects
        self.button_list = dict(((i, self.builder.get_object(i))) for i in self.button_list)

        # merge probe buttons into main button dictionary
        self.button_list.update(self.mill_probe.button_list)

        self.composite_png_button_images()

        # Create additional buttons manually
        self.setup_gcode_buttons()
        self.setup_copy_buttons()

        # get initial x/y locations for eventboxes
        for name, eventbox in self.button_list.iteritems():
            eventbox.x = ui_misc.get_x_pos(eventbox)
            eventbox.y = ui_misc.get_y_pos(eventbox)

        self.set_button_permitted_states()
        self.mill_probe.set_button_permitted_states()

        # ------------------------------------------------
        # DROs (gtk.entry)
        # ------------------------------------------------

        # main screen
        self.dro_list = ('x_dro', 'y_dro', 'z_dro', 'a_dro',
                         'feed_per_min_dro', 'spindle_rpm_dro', 'tool_dro',
                         'touch_z_dro', 'inject_dwell_dro',
                         'atc_manual_insert_dro', 'atc_auto_dro')

        # dictionary of DRO names, gtk.entry objects
        self.dro_list = dict(((i, self.builder.get_object(i))) for i in self.dro_list)
        dro_font_description  = pango.FontDescription('helvetica ultra-condensed 22')
        for name, dro in self.dro_list.iteritems():
            dro.modify_font(dro_font_description)
            dro.masked = False

        # when X/Y rotation is present via G10 L2 the X and Y DROs display in italic font
        self.xy_dro_font_description = dro_font_description
        self.rotation_xy_dro_font_description = pango.FontDescription('helvetica italic ultra-condensed 22')
        # only modify the X and Y DRO font if rotation changes
        self.prev_self_rotation_xy = 0

        # DROs common to all conversational routines
        self.current_normal_z_feed_rate = ''
        self.conv_dro_list = (
            'conv_title_dro',
            'conv_work_offset_dro',
            'conv_tool_number_dro',
            'conv_rpm_dro',
            'conv_feed_dro',
            'conv_z_feed_dro',
            'conv_z_clear_dro')

        self.conv_dro_list = dict(((i, self.builder.get_object(i))) for i in self.conv_dro_list)

        self.chip_load_hint = self.builder.get_object('chip_load_hint')
        self.stepover_chip_load = self.builder.get_object('chip_load_at_stepover_hint')

        for name, dro in self.conv_dro_list.iteritems(): dro.modify_font(self.conv_dro_font_description)
        self.add_modify_callback(self.conv_dro_list['conv_tool_number_dro'],self._update_stepover_hints)
        self.add_modify_callback(self.conv_dro_list['conv_tool_number_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.conv_dro_list['conv_tool_number_dro'],self.feeds_speeds_update_advised)


        self.conv_dro_list['conv_title_dro'].modify_font(pango.FontDescription('helvetica ultra-condensed 18'))



        # Face DROs
        self.face_dro_list = (
            'face_x_start_dro',
            'face_x_end_dro',
            'face_y_start_dro',
            'face_y_end_dro',
            'face_z_start_dro',
            'face_z_end_dro',
            'face_z_doc_dro',
            'face_stepover_dro')

        self.face_dro_list = dict(((i, self.builder.get_object(i))) for i in self.face_dro_list)
        for name, dro in self.face_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)
        self.face_stepover_hint_label = self.builder.get_object('face_stepover_hint_text')
        self.create_page_DRO_attributes(page_id='conv_face_fixed',common=self.conv_dro_list,spec=self.face_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],\
                                        rpm=self.conv_dro_list['conv_rpm_dro'],stepover=self.face_dro_list['face_stepover_dro'],r_doc=self.face_dro_list['face_z_doc_dro'],\
                                        r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.face_dro_list['face_z_start_dro'],\
                                        z_end=self.face_dro_list['face_z_end_dro'],stepover_hint=self.face_stepover_hint_label)
        self.add_modify_callback(self.face_dro_list['face_z_doc_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.face_dro_list['face_stepover_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.face_dro_list['face_stepover_dro'],self._update_stepover_hints)
        self.face_dro_list['face_stepover_dro']

        # Profile DROs
        self.profile_dro_list = (
            'profile_z_doc_dro',
            'profile_z_end_dro',
            'profile_z_start_dro',
            'profile_stepover_dro',
            'profile_y_end_dro',
            'profile_y_start_dro',
            'profile_x_end_dro',
            'profile_x_start_dro',
            'profile_x_prfl_start_dro',
            'profile_y_prfl_end_dro',
            'profile_x_prfl_end_dro',
            'profile_y_prfl_start_dro',
            'profile_radius_dro',
            'profile_circ_z_doc_dro',
            'profile_circ_z_end_dro',
            'profile_circ_z_start_dro',
            'profile_circ_stepover_dro',
            'profile_circ_y_end_dro',
            'profile_circ_y_start_dro',
            'profile_circ_x_end_dro',
            'profile_circ_x_start_dro',
            'profile_circ_diameter_dro',
            'profile_x_center_dro',
            'profile_y_center_dro')

        self.profile_dro_list = dict(((i, self.builder.get_object(i))) for i in self.profile_dro_list)
        for name, dro in self.profile_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)
        self.profile_stepover_hint_label = self.builder.get_object('profile_stepover_hint_text')
        self.create_page_DRO_attributes(page_id='conv_profile_fixed',common=self.conv_dro_list,spec=self.profile_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],stepover=self.profile_dro_list['profile_stepover_dro'],r_doc=self.profile_dro_list['profile_z_doc_dro'],
                                        r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.profile_dro_list['profile_z_start_dro'],
                                        z_end=self.profile_dro_list['profile_z_end_dro'],stepover_hint=self.profile_stepover_hint_label)
        self.create_page_DRO_attributes(page_id='conv_profile_fixed',attr='profile_circ_dros',common=self.conv_dro_list,spec=self.profile_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],stepover=self.profile_dro_list['profile_circ_stepover_dro'],r_doc=self.profile_dro_list['profile_z_doc_dro'],
                                        r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.profile_dro_list['profile_z_start_dro'],
                                        z_end=self.profile_dro_list['profile_z_end_dro'],stepover_hint=self.profile_stepover_hint_label)
        self.add_modify_callback(self.profile_dro_list['profile_z_doc_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.profile_dro_list['profile_stepover_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.profile_dro_list['profile_stepover_dro'],self._update_stepover_hints)
        self.add_modify_callback(self.profile_dro_list['profile_circ_stepover_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.profile_dro_list['profile_circ_stepover_dro'],self._update_stepover_hints)

        self.profile_x_prfl_start_label = self.builder.get_object('profile_x_prfl_start_text')
        self.profile_x_prfl_end_label = self.builder.get_object('profile_x_prfl_end_text')
        self.profile_y_prfl_start_label = self.builder.get_object('profile_y_prfl_start_text')
        self.profile_y_prfl_end_label = self.builder.get_object('profile_y_prfl_end_text')
        self.profile_radius_label = self.builder.get_object('profile_radius_text')
        self.profile_circ_diameter_label = self.builder.get_object('profile_circ_diameter_text')
        self.profile_x_center_label = self.builder.get_object('profile_x_center_text')
        self.profile_y_center_label = self.builder.get_object('profile_y_center_text')


        # Pocket-Rectangular DROs
        self.pocket_rect_dro_list = (
            'pocket_rect_x_start_dro',
            'pocket_rect_x_end_dro',
            'pocket_rect_y_start_dro',
            'pocket_rect_y_end_dro',
            'pocket_rect_z_start_dro',
            'pocket_rect_z_end_dro',
            'pocket_rect_z_doc_dro',
            'pocket_rect_stepover_dro',
            'pocket_rect_corner_radius_dro')

        self.pocket_rect_dro_list = dict(((i, self.builder.get_object(i))) for i in self.pocket_rect_dro_list)
        for name, dro in self.pocket_rect_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.pocket_rect_stepover_hint_label = self.builder.get_object('pocket_rect_stepover_hint_text')
        self.create_page_DRO_attributes(page_id='conv_pocket_fixed',common=self.conv_dro_list,spec=self.pocket_rect_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],stepover=self.pocket_rect_dro_list['pocket_rect_stepover_dro'],r_doc=self.pocket_rect_dro_list['pocket_rect_z_doc_dro'],
                                        r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.pocket_rect_dro_list['pocket_rect_z_start_dro'],
                                        z_end=self.pocket_rect_dro_list['pocket_rect_z_end_dro'],stepover_hint=self.pocket_rect_stepover_hint_label)
        self.add_modify_callback(self.pocket_rect_dro_list['pocket_rect_z_doc_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.pocket_rect_dro_list['pocket_rect_stepover_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.pocket_rect_dro_list['pocket_rect_stepover_dro'],self._update_stepover_hints)

        self.pocket_rect_x_start_label       = self.builder.get_object('pocket_rect_x_start_text')
        self.pocket_rect_x_end_label         = self.builder.get_object('pocket_rect_x_end_text')
        self.pocket_rect_y_start_label       = self.builder.get_object('pocket_rect_y_start_text')
        self.pocket_rect_y_end_label         = self.builder.get_object('pocket_rect_y_end_text')
        self.pocket_rect_corner_radius_label = self.builder.get_object('pocket_rect_corner_radius_text')


        # Pocket-Circular DROs
        self.pocket_circ_dro_list = (
            'pocket_circ_z_end_dro',
            'pocket_circ_z_start_dro',
            'pocket_circ_z_doc_dro',
            'pocket_circ_stepover_dro',
            'pocket_circ_diameter_dro')

        self.pocket_circ_dro_list = dict(((i, self.builder.get_object(i))) for i in self.pocket_circ_dro_list)
        for name, dro in self.pocket_circ_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.pocket_circ_stepover_hint_label = self.builder.get_object('pocket_circ_stepover_hint_text')
        self.create_page_DRO_attributes(page_id='conv_pocket_fixed',attr='pocket_circ_dros',common=self.conv_dro_list,spec=self.pocket_circ_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],stepover=self.pocket_circ_dro_list['pocket_circ_stepover_dro'],r_doc=self.pocket_circ_dro_list['pocket_circ_z_doc_dro'],
                                        r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.pocket_circ_dro_list['pocket_circ_z_start_dro'],
                                        z_end=self.pocket_circ_dro_list['pocket_circ_z_end_dro'],stepover_hint=self.pocket_circ_stepover_hint_label)
        self.add_modify_callback(self.pocket_circ_dro_list['pocket_circ_z_doc_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.pocket_circ_dro_list['pocket_circ_stepover_dro'],self.update_chip_load_hint)
        self.add_modify_callback(self.pocket_circ_dro_list['pocket_circ_stepover_dro'],self._update_stepover_hints)

        self.pocket_circ_x_center_label = self.builder.get_object('pocket_circ_x_center_text')
        self.pocket_circ_y_center_label = self.builder.get_object('pocket_circ_y_center_text')
        self.pocket_circ_diameter_label = self.builder.get_object('pocket_circ_diameter_text')


        # Drill extras list - toggle for JA thread mill editing...
        self.drill_tap_extras = (
            'drill_tap_main_image',
            'drill_tap_detail_image',
            'drill_z_clear_text',
            'drill_tap_z_end_text'
        )
        self.drill_tap_extras = dict(((i, self.builder.get_object(i))) for i in self.drill_tap_extras)

        # Drill DROs
        self.drill_dro_list = (
            'drill_z_start_dro',
            'drill_peck_dro',
            'drill_z_end_dro',
            'drill_spot_tool_number_dro',
            'drill_spot_tool_doc_dro')

        self.drill_dro_list = dict(((i, self.builder.get_object(i))) for i in self.drill_dro_list)
        for name, dro in self.drill_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.create_page_DRO_attributes(page_id='conv_drill_tap_fixed',common=self.conv_dro_list,spec=self.drill_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],peck=self.drill_dro_list['drill_peck_dro'],r_feed=self.conv_dro_list['conv_feed_dro'],
                                        z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.drill_dro_list['drill_z_start_dro'],z_end=self.drill_dro_list['drill_z_end_dro'])

        self.drill_circular_dro_list = (
            'drill_tap_pattern_circular_holes_dro',
            'drill_tap_pattern_circular_start_angle_dro',
            'drill_tap_pattern_circular_diameter_dro',
            'drill_tap_pattern_circular_center_x_dro',
            'drill_tap_pattern_circular_center_y_dro')

        self.drill_circular_dro_list = dict(((i, self.builder.get_object(i))) for i in self.drill_circular_dro_list)
        for name, dro in self.drill_circular_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        drill_fields = ['spot_note',
                        'peck',
                        'spot_tool_number',
                        'spot_tool_doc',
                        'z_start']

        self.drill_labels = dict((f, self.get_obj('drill_%s_text' % f)) for f in drill_fields)

        self.drill_calc_font = pango.FontDescription('helvetica ultra-condensed 22')
        self.drill_through_hole_hint_label = self.builder.get_object('drill_through_hole_hint_text')

        # Tap DROs
        self.tap_dro_list = (
            'tap_z_end_dro',
            'tap_dwell_dro',
            'tap_pitch_dro',
            'tap_tpu_dro')

        self.tap_dro_list = dict(((i, self.builder.get_object(i))) for i in self.tap_dro_list)

        self.create_page_DRO_attributes(page_id='conv_drill_tap_fixed',attr='tap_dros',common=self.conv_dro_list,spec=self.tap_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],r_feed=self.conv_dro_list['conv_feed_dro'],
                                        z_feed=self.conv_dro_list['conv_z_feed_dro'],z_start=self.drill_dro_list['drill_z_start_dro'],z_end=self.tap_dro_list['tap_z_end_dro'])


        for name, dro in self.tap_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        tap_fields = ['dwell_note',
                      'dwell_sec',
                      'dwell_travel',
                      'pitch',
                      'tpu',
                      'mult',
                      'rpm_pitch',
                      '60_2',
                      'dwell_travel_calc',
                      'rpm_feed']

        #Generate the dictionary from just the field names (no need to retype the full labels)
        self.tap_labels=dict((f, self.get_obj('tap_%s_text' % f)) for f in tap_fields)

        self.tap_hsep = self.builder.get_object('tap_hseparator')

        self.drill_pattern_notebook_page = 'pattern'

        # Thread Mill DROs
        # External
        thread_mill_ext_dro_list = (
            ##'thread_mill_ext_x_dro',
            ##'thread_mill_ext_y_dro',
            'thread_mill_ext_z_start_dro',
            'thread_mill_ext_z_end_dro',
            'thread_mill_ext_major_dia_dro',
            'thread_mill_ext_minor_dia_dro',
            'thread_mill_ext_doc_dro',
            'thread_mill_ext_passes_dro',
            'thread_mill_ext_pitch_dro',
            'thread_mill_ext_tpu_dro')

        self.thread_mill_ext_dro_list = dict((i,self.get_obj(i)) for i in thread_mill_ext_dro_list)
        for name, dro in self.thread_mill_ext_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.create_page_DRO_attributes(page_id='conv_thread_mill_fixed',common=self.conv_dro_list,spec=self.thread_mill_ext_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],
                                        r_doc=self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'],z_start=self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'],
                                        z_end=self.thread_mill_ext_dro_list['thread_mill_ext_z_end_dro'])

        # Internal
        self.thread_mill_int_dro_list = (
            ##'thread_mill_int_x_dro',
            ##'thread_mill_int_y_dro',
            'thread_mill_int_z_start_dro',
            'thread_mill_int_z_end_dro',
            'thread_mill_int_major_dia_dro',
            'thread_mill_int_minor_dia_dro',
            'thread_mill_int_doc_dro',
            'thread_mill_int_passes_dro',
            'thread_mill_int_pitch_dro',
            'thread_mill_int_tpu_dro')

        self.thread_mill_int_dro_list = dict(((i, self.builder.get_object(i))) for i in self.thread_mill_int_dro_list)
        for name, dro in self.thread_mill_int_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.create_page_DRO_attributes(page_id='conv_thread_mill_fixed',attr='thread_internal_dros',common=self.conv_dro_list,spec=self.thread_mill_int_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],
                                        r_doc=self.thread_mill_int_dro_list['thread_mill_int_doc_dro'],z_start=self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'],
                                        z_end=self.thread_mill_int_dro_list['thread_mill_int_z_end_dro'])

        self.thread_mill_int_minimal_retract_check = self.builder.get_object('thread_mill_minimal_retract_checkbutton')
        self.thread_mill_int_minimal_retract_check.set_active(True)
        self.thread_mill_tpu_label = self.builder.get_object('thread_mill_tpu_text')
        self.thread_mill_pitch_label = self.builder.get_object('thread_mill_pitch_text')

        # thread data selector
        self.thread_chart_combobox = self.builder.get_object('thread_combobox')
        self.thread_chart_g20_liststore = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.thread_chart_g21_liststore = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.thread_chart_combobox.set_model(self.thread_chart_g20_liststore)

        cell = gtk.CellRendererText()
        self.thread_chart_combobox.pack_start(cell, True)
        self.thread_chart_combobox.add_attribute(cell, 'text', 0)
        cellview = self.thread_chart_combobox.get_child()
        cellview.set_displayed_row(0)

        self.refresh_thread_data_liststores()


        # Engrave DROs
        self.engrave_text_dro = self.builder.get_object("engrave_text_dro")
        self.engrave_dro_list = (
            'engrave_text_dro',
            'engrave_x_base_dro',
            'engrave_y_base_dro',
            'engrave_z_start_dro',
            'engrave_height_dro',
            'engrave_z_doc_dro',
            'engrave_sn_start_dro')

        self.engrave_dro_list = dict(((i, self.builder.get_object(i))) for i in self.engrave_dro_list)
        for name, dro in self.engrave_dro_list.iteritems():
            dro.modify_font(self.conv_dro_font_description)

        self.create_page_DRO_attributes(page_id='conv_engrave_fixed',common=self.conv_dro_list,spec=self.engrave_dro_list,tool=self.conv_dro_list['conv_tool_number_dro'],
                                        rpm=self.conv_dro_list['conv_rpm_dro'],r_feed=self.conv_dro_list['conv_feed_dro'],z_feed=self.conv_dro_list['conv_z_feed_dro'],
                                        r_doc=self.engrave_dro_list['engrave_z_doc_dro'])




        # --------------------------------------------
        # Call Scanner / Scope setup routines
        # --------------------------------------------

        self.scanner_gui_init()
        self.scope_gui_init()
        self.dxf_gui_init()

        # --------------------------------------------
        # Labels
        # --------------------------------------------
        self.get_version_string()

        # dtg labels
        self.x_dtg_label = self.builder.get_object('x_dtg_label')
        self.y_dtg_label = self.builder.get_object('y_dtg_label')
        self.z_dtg_label = self.builder.get_object('z_dtg_label')
        self.a_dtg_label = self.builder.get_object('a_dtg_label')

        dtg_font_description = pango.FontDescription('helvetica ultra-condensed 22')
        self.x_dtg_label.modify_font(dtg_font_description)
        self.y_dtg_label.modify_font(dtg_font_description)
        self.z_dtg_label.modify_font(dtg_font_description)
        self.a_dtg_label.modify_font(dtg_font_description)

        # atc_labels
        self.atc_pocket_list = ('atc_carousel_0', 'atc_carousel_1', 'atc_carousel_2', 'atc_carousel_3', 'atc_carousel_4', 'atc_carousel_5',
                                'atc_carousel_6', 'atc_carousel_7', 'atc_carousel_8', 'atc_carousel_9', 'atc_carousel_10', 'atc_carousel_11')

        self.atc_pocket_list = dict(((i, self.builder.get_object(i))) for i in self.atc_pocket_list)

        for name, label in self.atc_pocket_list.iteritems():
            label.modify_font(dtg_font_description)

        self.tlo_label = self.builder.get_object("tlo_label")

        # ------------------------------------------------
        # Check buttons
        # ------------------------------------------------

        self.checkbutton_list = ('tap_2x_checkbutton',
                                 'engrave_left_radiobutton',
                                 'engrave_center_radiobutton',
                                 'engrave_right_radiobutton',
                                 'thread_mill_right_radiobutton',
                                 'thread_mill_left_radiobutton')

        for cb in self.checkbutton_list:
            self.builder.get_object(cb).modify_bg(gtk.STATE_PRELIGHT, TormachUIBase._check_button_hilight_color)
        self.checkbutton_list = dict(((i, self.builder.get_object(i))) for i in self.checkbutton_list)

        self.setup_filechooser()

        self.setup_gcode_marks()

        self.hal['probe-enable'] = 1  # turn on for all mills and A axis accessories.  This only needs to be
                                      # turned off for certain new accessories

        # axis scale factors
        for axis_letter in ['x', 'y', 'z']:
            redis_key = '%s_axis_scale_factor' % axis_letter
            if self.redis.hexists('machine_prefs', redis_key):
                axis_scale_factor = float(self.redis.hget('machine_prefs', redis_key))
                self.error_handler.write("Found %s axis scale factor %f in settings" % (axis_letter.upper(), axis_scale_factor), ALARM_LEVEL_DEBUG)
                self._set_axis_scale(axis_letter, axis_scale_factor)
            else:
                self.error_handler.write("No %s axis scale factor stored in redis. This is not an error." % axis_letter.upper(), ALARM_LEVEL_DEBUG)

        # axis backlash
        for axis_letter in ['x', 'y', 'z']:
            redis_key = '%s_axis_backlash' % axis_letter
            if self.redis.hexists('machine_prefs', redis_key):
                axis_backlash = float(self.redis.hget('machine_prefs', redis_key))
                self.error_handler.write("Found %s axis backlash %f in settings" % (axis_letter.upper(), axis_backlash), ALARM_LEVEL_DEBUG)
                self._set_axis_backlash(axis_letter, axis_backlash)
            else:
                self.error_handler.write("No %s axis backlash stored in redis. This is not an error." % axis_letter.upper(), ALARM_LEVEL_DEBUG)

        # Engraving fonts
        self.setup_font_selector()
        self.ef_num_rows = len(self.engrave_font_liststore)

        # start an efficient inotify based file system watcher on the USB
        # mount point directory so we can tell when the user plugs in a USB drive.
        global _mill_instance
        _mill_instance = self
        self.watcher = fswatch.Watcher(ENGRAVING_FONTS_DIR)
        self.watcher.start(FontDirFSHandler())

        self.hal['jog-gui-step-index'] = 0

        # set jog speed
        ini_jog_speed = (
            self.inifile.find("DISPLAY", "DEFAULT_LINEAR_VELOCITY")
            or self.inifile.find("TRAJ", "DEFAULT_LINEAR_VELOCITY")
            or self.inifile.find("TRAJ", "DEFAULT_VELOCITY")
            or 1.0)
        self.jog_speed = (float(ini_jog_speed))
        self.jog_speeds = [float(self.inifile.find("AXIS_%d" % ind, "MAX_JOG_VELOCITY_UPS")) for ind in range(4)]
        # set jog speed percentage
        if not self.redis.hexists('machine_prefs', 'jog_override_percentage'):
            self.redis.hset('machine_prefs', 'jog_override_percentage', 0.4)
        self.jog_override_pct = float(self.redis.hget('machine_prefs', 'jog_override_percentage'))

        # default to continuous jog mode
        self.jog_mode = linuxcnc.JOG_CONTINUOUS
        self.keyboard_jog_mode = linuxcnc.JOG_CONTINUOUS
        # initial jog percent to 40
        self.jog_speed_adjustment.set_value(self.jog_override_pct * 100)

        # keyboard jogging - connect keypress to callbacks
        self.window.connect("key_press_event", self.on_key_press_or_release)
        self.window.connect("key_release_event", self.on_key_press_or_release)


        # mode/state tracking (debug only)
        self.prev_lcnc_task_mode = -1
        self.prev_lcnc_interp_state = -1
        self.prev_task_state = -1

        # Always hide the USBIO interface until first run setup and Reset button are hit.
        self.hide_usbio_interface()

        # ---------------------------------------------------
        # tool change type and zbot atc init
        # ---------------------------------------------------

        self.atc = zbot_atc.zbot_atc(self.machineconfig, self.status, self.command, self.issue_mdi,
                                     self.hal, self.redis, self.atc_pocket_list, self.dro_list,
                                     self.atc_fixed, self.window, self.error_handler, self.set_image,
                                     self.mill_probe)

        # holds path to currently loaded gcode file
        # slow periodic polls for changes and reloads if appropriate
        self.set_current_gcode_path('')

        #timers for various ATC cabling or connection faults...
        self.atc_hardware_check_stopwatch = timer.Stopwatch()  # ATC comm USB failure timer
        self.atc_cable_check_stopwatch = timer.Stopwatch()     # cable failure timer

        try:
            tc_type = self.redis.hget('machine_prefs', 'toolchange_type')
            if tc_type == MILL_TOOLCHANGE_TYPE_REDIS_ZBOT:
                self.error_handler.log("Tool change type set to ATC")
                self.atc.enable()
                self.show_atc_diagnostics()
                self.settings.checkbutton_list['use_atc_checkbutton'].set_active(True)
                change_z = float(self.redis.hget('zbot_slot_table', 'tool_change_z'))
                if change_z < -1.5 and change_z > -3.5:
                    self.set_image('set_tool_change_z_image', 'Set-TC-POS-Green.png')
            else:
                self.error_handler.log("Tool change type set to Manual")
                self.atc.disable()
                self.hide_atc_diagnostics()
                self.settings.checkbutton_list['use_manual_toolchange_checkbutton'].set_active(True)
        except:
            self.error_handler.write("No toolchange_type found in redis machine prefs database", ALARM_LEVEL_DEBUG)
            self.atc.disable()
            self.settings.checkbutton_list['use_manual_toolchange_checkbutton'].set_active(True)

        # -----------------------------------------
        # tool table init (gtk.treeview)
        # -----------------------------------------
        # using a treeview/liststore for the tool table, on the tools page of the notebook
        # tool number
        # tool description
        # tool diameter
        # tool length
        # ?
        # background cell color based on if tool is used by current program or not
        self.tool_liststore = gtk.ListStore(int, str, str, str, object, str)

        # Create a TreeView and let it know about the model we created above
        self.tool_treeview = gtk.TreeView(self.tool_liststore)
        self.treeselection = self.tool_treeview.get_selection()
        self.treeselection.set_mode(gtk.SELECTION_SINGLE)

        tool_font = pango.FontDescription('Roboto Condensed 10')

        self.tool_table_filename = self.inifile.find("EMCIO", "TOOL_TABLE") or ""
        if self.tool_table_filename == "":
            self.tool_table_filename = "~/mill_data/tool.tbl"
        self.tool_table_filename = os.path.expanduser(self.tool_table_filename)
        self.tool_table_file_mtime = os.stat(self.tool_table_filename).st_mtime
        self.tool_liststore_prev_linear_scale = 0.0

        # create columns
        self.tool_num_column           = gtk.TreeViewColumn('Tool')
        self.tool_description_column   = gtk.TreeViewColumn('Description')
        self.tool_diameter_column      = gtk.TreeViewColumn('Diameter')
        self.tool_length_column        = gtk.TreeViewColumn('Length')

        # add columns to treeview
        self.tool_treeview.append_column(self.tool_num_column)
        self.tool_treeview.append_column(self.tool_description_column)
        self.tool_treeview.append_column(self.tool_diameter_column)
        self.tool_treeview.append_column(self.tool_length_column)

        tool_col_renderer = gtk.CellRendererText()
        tool_col_renderer.set_property('editable', False)
        tool_col_renderer.set_property('font-desc', tool_font)

        self.tool_num_column.pack_start(tool_col_renderer, True)
        # we have the tool number column use the 5th element of the tool liststore as the value for the background propery
        self.tool_num_column.set_attributes(tool_col_renderer, text=0, cell_background=5)

        tool_description_renderer = gtk.CellRendererText()
        tool_description_renderer.set_property('editable', True)
        tool_description_renderer.set_property('cell-background', '#D5E1B3')
        tool_description_renderer.set_property('font-desc', tool_font)
        self.tool_description_column.pack_start(tool_description_renderer, True)
        self.tool_description_column.set_attributes(tool_description_renderer, text=1)
        self.tool_description_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.tool_description_column.set_fixed_width(self.fs_mgr.tool_column_width())
        tool_description_renderer.connect( 'edited', self.on_tool_description_column_edited, self.tool_liststore )

        tool_diameter_renderer = gtk.CellRendererText()
        tool_diameter_renderer.set_property('editable', True)
        tool_diameter_renderer.set_property('cell-background', '#D6D76C')
        tool_diameter_renderer.set_property('font-desc', tool_font)
        self.tool_diameter_column.pack_start(tool_diameter_renderer, True)
        self.tool_diameter_column.set_attributes(tool_diameter_renderer, text=2)
        tool_diameter_renderer.connect( 'edited', self.on_tool_diameter_column_edited, self.tool_liststore )
        tool_diameter_renderer.connect( 'editing-started', self.on_tool_diameter_column_editing_started)

        tool_length_renderer = gtk.CellRendererText()
        tool_length_renderer.set_property('editable', True)
        tool_length_renderer.set_property('cell-background', '#B3E1D7')
        tool_length_renderer.set_property('font-desc', tool_font)
        self.tool_length_column.pack_start(tool_length_renderer, True)
        self.tool_length_column.set_attributes(tool_length_renderer, text=3)
        tool_length_renderer.connect( 'edited', self.on_tool_length_column_edited, self.tool_liststore )
        tool_length_renderer.connect( 'editing-started', self.on_tool_length_column_editing_started)


        # show in notebook

        # create a scrolled window to hold the treeview
        self.scrolled_window_tool_table = gtk.ScrolledWindow()
        self.scrolled_window_tool_table.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)


        self.tool_offsets_fixed.put(self.scrolled_window_tool_table, 365, 35)
        self.scrolled_window_tool_table.add(self.tool_treeview)
        self.scrolled_window_tool_table.set_size_request(605, 320)
        self.tool_descript_entry = ToolDescriptorEntry(self,MAX_NUM_MILL_TOOL_NUM, self.fs_mgr.tool_description_parse_data())
        self.key_mask[type(self.tool_descript_entry)] = self.tool_descript_keys

        self.tool_search_entry = self.builder.get_object('tool_search_entry')
        self.tool_search_entry.set_icon_from_stock(1, gtk.STOCK_FIND)
        self.tool_search_entry.connect('key-press-event', self.search_entry_key_press_event)

        self.tool_treeview.set_search_entry(self.tool_search_entry)
        self.tool_treeview.set_search_equal_func(tool_treeview_search_function, self)
        self.tool_treeview.set_enable_search(True)

        # this takes ~5 seconds on a slow Brix so we broke it up into the initial load
        # and then later the refresh of existing values which is much faster.
        self.load_initial_tool_liststore()
        # -----------------------------------------
        # drill table init (gtk.treeview)
        # -----------------------------------------
        drill_font = pango.FontDescription('helvetica ultra-condensed 18')
        drill_i_font = pango.FontDescription('helvetica ultra-condensed 16')

        self.drill_liststore = gtk.ListStore(str, str, str)


        for id_cnt  in range(1, self.DRILL_TABLE_ROWS + 1):
            self.drill_liststore.append([id_cnt, '', ''])

        self.drill_treeview = gtk.TreeView(self.drill_liststore)

        self.drill_i_column  = gtk.TreeViewColumn()
        self.drill_x_column  = gtk.TreeViewColumn('')
        self.drill_y_column  = gtk.TreeViewColumn('')

        self.drill_treeview.append_column(self.drill_i_column)
        self.drill_treeview.append_column(self.drill_x_column)
        self.drill_treeview.append_column(self.drill_y_column)

        self.drill_treeview.set_rules_hint(True)
        self.drill_treeview.set_headers_visible(False)
        self.drill_treeview.set_grid_lines(gtk.TREE_VIEW_GRID_LINES_BOTH)

        drill_i_renderer = gtk.CellRendererText()
        drill_i_renderer.set_property('editable', False)
        drill_i_renderer.set_property('cell-background', '#EEBBBB')
        drill_i_renderer.set_property('font-desc', drill_i_font)
        drill_i_renderer.set_property('xalign',0.5)
        drill_i_renderer.set_property('yalign',1)
        drill_i_renderer.set_property('height',28)
        self.drill_i_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.drill_i_column.set_fixed_width(30)
        self.drill_i_column.pack_start(drill_i_renderer, True)
        self.drill_i_column.set_attributes(drill_i_renderer, text=0)

        drill_x_renderer = gtk.CellRendererText()
        drill_x_renderer.set_property('editable', True)
        drill_x_renderer.set_property('font-desc', drill_font)
        drill_x_renderer.set_property('xalign',0.8)
        drill_x_renderer.set_property('yalign',1)
        drill_x_renderer.set_property('height',28)
#       drill_x_renderer.set_property('rise',12)
#       drill_x_renderer.set_property('rise-set',True)
        self.drill_x_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.drill_x_column.set_fixed_width(105)
        self.drill_x_column.pack_start(drill_x_renderer, True)
        self.drill_x_column.set_attributes(drill_x_renderer, text=1)
        drill_x_renderer.connect('edited', self.on_drill_x_column_edited, self.drill_liststore)

        drill_y_renderer = gtk.CellRendererText()
        drill_y_renderer.set_property('editable', True)
        drill_y_renderer.set_property('font-desc', drill_font)
        drill_y_renderer.set_property('xalign',0.8)
        drill_y_renderer.set_property('yalign',1)
        drill_y_renderer.set_property('height',28)
#       drill_y_renderer.set_property('rise',12)
        self.drill_y_column.set_fixed_width(105)
        self.drill_y_column.pack_start(drill_y_renderer, True)
        self.drill_y_column.set_attributes(drill_y_renderer, text=2)
        drill_y_renderer.connect('edited', self.on_drill_y_column_edited, self.drill_liststore)

        drill_x_renderer.connect('editing-started', self.on_drill_x_column_editing_started, drill_font)
        drill_y_renderer.connect('editing-started', self.on_drill_y_column_editing_started, drill_font)
        self.drill_x_renderer = drill_x_renderer
        self.drill_y_renderer = drill_y_renderer

        # show in notebook

        # create a scrolled window to hold the treeview
        self.scrolled_window_drill_table = gtk.ScrolledWindow()
        self.scrolled_window_drill_table.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

        self.conv_drill_tap_pattern_notebook_fixed.put(self.scrolled_window_drill_table, 7, 32)

        # the treeview knows about scrolling so do NOT add it using add_with_viewport or you
        # break all inherent keyboard navigation.
        self.scrolled_window_drill_table.add(self.drill_treeview)
        self.scrolled_window_drill_table.set_size_request(270, 270)

        # restore last used values on conversational screens
        self.restore_conv_parameters()

        # update the step-over hints



        # -----------------------------------------
        # Work Offset table init (gtk.treeview)
        # -----------------------------------------
        self.work_font = work_font = pango.FontDescription('Roboto Condensed 11')

        self.work_liststore = gtk.ListStore(str, str, str, str, str, str, str, str, int, str)

        # Create a TreeView and let it know about the model we created above
        self.work_treeview = gtk.TreeView(self.work_liststore)

        work_id_column = gtk.TreeViewColumn('')
        work_id_label = gtk.Label('ID')
        work_id_label.modify_font(work_font)
        work_id_column.set_widget(work_id_label)
        work_id_label.show()

        work_desc_column = gtk.TreeViewColumn('')
        work_desc_label = gtk.Label('Description')
        work_desc_label.modify_font(work_font)
        work_desc_column.set_widget(work_desc_label)
        work_desc_label.show()

        work_x_column  = gtk.TreeViewColumn('')
        work_x_label = gtk.Label('X')
        work_x_label.modify_font(work_font)
        work_x_column.set_widget(work_x_label)
        work_x_label.show()

        work_y_column  = gtk.TreeViewColumn('')
        work_y_label = gtk.Label('Y')
        work_y_label.modify_font(work_font)
        work_y_column.set_widget(work_y_label)
        work_y_label.show()

        work_z_column  = gtk.TreeViewColumn('')
        work_z_label = gtk.Label('Z')
        work_z_label.modify_font(work_font)
        work_z_column.set_widget(work_z_label)
        work_z_label.show()

        work_a_column  = gtk.TreeViewColumn('')
        work_a_label = gtk.Label('A')
        work_a_label.modify_font(work_font)
        work_a_column.set_widget(work_a_label)
        work_a_label.show()

        self.work_treeview.append_column(work_id_column)
        self.work_treeview.append_column(work_desc_column)
        self.work_treeview.append_column(work_x_column)
        self.work_treeview.append_column(work_y_column)
        self.work_treeview.append_column(work_z_column)
        self.work_treeview.append_column(work_a_column)

        self.work_treeview.set_rules_hint(True)

        work_id_renderer = gtk.CellRendererText()
        work_id_renderer.set_property('editable', False)
        work_id_renderer.set_property('font-desc', work_font)
        work_id_renderer.set_property('width',84)
        work_id_column.pack_start(work_id_renderer, True)
        work_id_column.set_attributes(work_id_renderer, text=0, cell_background=9)

        work_desc_renderer = gtk.CellRendererText()
        work_desc_renderer.set_property('editable', True)
        work_desc_renderer.set_property('font-desc', work_font)
        work_desc_renderer.set_property('xalign',0)
        work_desc_renderer.set_property('width',354)
        work_desc_column.pack_start(work_desc_renderer, True)
        work_desc_column.set_attributes(work_desc_renderer, text=1, foreground=6, background=7)

        work_x_renderer = gtk.CellRendererText()
        work_x_renderer.set_property('editable', True)
        work_x_renderer.set_property('font-desc', work_font)
        work_x_renderer.set_property('xalign',0.8)
        work_x_renderer.set_property('width',90)
        work_x_column.pack_start(work_x_renderer, True)
        work_x_column.set_attributes(work_x_renderer, text=2, foreground=6, background=7)

        work_y_renderer = gtk.CellRendererText()
        work_y_renderer.set_property('editable', True)
        work_y_renderer.set_property('font-desc', work_font)
        work_y_renderer.set_property('xalign',0.8)
        work_y_renderer.set_property('width',90)
        work_y_column.pack_start(work_y_renderer, True)
        work_y_column.set_attributes(work_y_renderer, text=3, foreground=6, background=7)

        work_z_renderer = gtk.CellRendererText()
        work_z_renderer.set_property('editable', True)
        work_z_renderer.set_property('font-desc', work_font)
        work_z_renderer.set_property('xalign',0.8)
        work_z_renderer.set_property('width',90)
        work_z_column.pack_start(work_z_renderer, True)
        work_z_column.set_attributes(work_z_renderer, text=4, foreground=6, background=7)

        work_a_renderer = gtk.CellRendererText()
        work_a_renderer.set_property('editable', True)
        work_a_renderer.set_property('font-desc', work_font)
        work_a_renderer.set_property('xalign',0.8)
        work_a_renderer.set_property('width',90)
        work_a_column.pack_start(work_a_renderer, True)
        work_a_column.set_attributes(work_a_renderer, text=5, foreground=6, background=7)

        # Callbacks for when a work offset has begun being edited
        # args are next column name and how many to increment the row
        # number by
        work_desc_renderer.connect( 'editing-started',
                                   self.on_work_column_editing_started,
                                   work_x_column, 0)
        work_x_renderer.connect( 'editing-started',
                                 self.on_work_column_editing_started,
                                 work_y_column, 0)
        work_y_renderer.connect( 'editing-started',
                                 self.on_work_column_editing_started,
                                 work_z_column, 0)
        work_z_renderer.connect( 'editing-started',
                                 self.on_work_column_editing_started,
                                 work_a_column, 0)
        work_a_renderer.connect( 'editing-started',
                                 self.on_work_column_editing_started,
                                 work_desc_column, 1)

        # Callbacks for when a work offset has finished being edited
        # arg is the axis letter
        work_desc_renderer.connect( 'edited',
                                   self.on_work_column_edited,
                                   self.work_liststore, 'description')
        work_x_renderer.connect( 'edited', self.on_work_column_edited,
                                 self.work_liststore, 'x' )
        work_y_renderer.connect( 'edited', self.on_work_column_edited,
                                 self.work_liststore, 'y' )
        work_z_renderer.connect( 'edited', self.on_work_column_edited,
                                 self.work_liststore, 'z' )
        work_a_renderer.connect( 'edited', self.on_work_column_edited,
                                 self.work_liststore, 'a' )

        self.workoffset_search_entry = self.builder.get_object('workoffset_search_entry')
        self.workoffset_search_entry.set_icon_from_stock(1, gtk.STOCK_FIND)
        self.workoffset_search_entry.connect('key-press-event', self.search_entry_key_press_event)
        self.workoffset_search_entry.modify_font(pango.FontDescription('Roboto Condensed 11'))

        self.work_treeview.set_search_entry(self.workoffset_search_entry)
        self.work_treeview.set_search_equal_func(workoffset_treeview_search_function, self)
        self.work_treeview.set_enable_search(True)

        # work offsets filtering combobox
        self.filter_work_offsets = FILTER_WORK_OFFSETS_ALL   # All Work Offsets on startup always to reduce tech support calls
        self.filter_work_offsets_liststore = gtk.ListStore(str, int)
        self.filter_work_offsets_combobox = self.builder.get_object("filter_work_offsets_combobox")
        self.filter_work_offsets_combobox.set_model(self.filter_work_offsets_liststore)
        cell = gtk.CellRendererText()
        self.filter_work_offsets_combobox.pack_start(cell, True)
        self.filter_work_offsets_combobox.add_attribute(cell, 'markup', 0)
        self.filter_work_offsets_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 10">All Offsets</span>', FILTER_WORK_OFFSETS_ALL])
        self.filter_work_offsets_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 10">Offsets Used by G-Code File</span>', FILTER_WORK_OFFSETS_USED_BY_GCODE])
        self.filter_work_offsets_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 10">Offsets with Descriptions</span>', FILTER_WORK_OFFSETS_NONBLANK_DESCRIPTIONS])
        self.filter_work_offsets_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 10">Offsets with Values</span>', FILTER_WORK_OFFSETS_NONZERO])

        self.filter_work_offsets_combobox.set_property("has-tooltip", True)
        self.filter_work_offsets_combobox.set_active(0)  # first row of list store = All Work Offsets to start
        self.filter_work_offsets_combobox.connect("query-tooltip", self.on_filter_combobox_querytooltip)

        # show in notebook

        # create a scrolled window to hold the treeview
        self.scrolled_window_work_table = gtk.ScrolledWindow()
        self.scrolled_window_work_table.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)

        self.work_offsets_fixed.put(self.scrolled_window_work_table, 8, 36)
        # the treeview knows about scrolling so do NOT add it using add_with_viewport or you
        # break all inherent keyboard navigation.
        self.scrolled_window_work_table.add(self.work_treeview)
        self.scrolled_window_work_table.set_size_request(840, 320)

        # Keep track of work offset probes
        self.work_probe_in_progress = False


        # end job table init (gtk.treeview)
        # -----------------------------------------

        self.hal['spindle-range'] = self.redis.hget('machine_prefs', 'spindle_range') == "hi"

        if self.hal['spindle-range']:
            # high
            self.set_image('spindle_range_image', 'Spindle_Range_HI_Highlight.png')
            self.mach_data['motor_curve'] = self.mach_data_hi
            FSBase.update_spindle_range()
        else:
            # low
            self.set_image('spindle_range_image', 'Spindle_Range_LO_Highlight.png')
            self.mach_data['motor_curve'] = self.mach_data_lo
            FSBase.update_spindle_range()

        # See if we really have HI/LO belt position option
        if self.ini_int('SPINDLE', 'LO_RANGE_MIN') == self.ini_int('SPINDLE', 'HI_RANGE_MIN') and \
           self.ini_int('SPINDLE', 'LO_RANGE_MAX') == self.ini_int('SPINDLE', 'HI_RANGE_MAX'):
           # Hide the button
            self.button_list['spindle_range'].set_no_show_all(True)
            self.button_list['spindle_range'].hide()


        self.set_home_switches()

        self.settings.configure_g30_settings()

        try:
            self.injector_dwell = float(self.redis.hget('machine_prefs', 'injector_dwell'))
        except:
            #self.error_handler.write("exception looking for 'machine_prefs', 'injector_dwell' in redis, defaulting to 20 sec.", ALARM_LEVEL_LOW)
            # write to redis to avoid future messages
            self.redis.hset('machine_prefs', 'injector_dwell', '20')
            self.injector_dwell = 20.

        self.dro_list['inject_dwell_dro'].set_text(self.dro_medium_format % self.injector_dwell)

        # drive the solenoid firmly so we know it is unlocked
        self.unlock_enclosure_door()

        speed_str = self.redis.hget('machine_prefs', 'enc_door_open_max_rpm')
        if speed_str == None:
            self.error_handler.write('no enc_door_open_max_rpm found in redis defaulting to 0', ALARM_LEVEL_DEBUG)
            speed_str = '0'
        self.enc_open_door_max_rpm = int(speed_str)
        self.error_handler.write('enclosure door open max rpm: %d' % self.enc_open_door_max_rpm, ALARM_LEVEL_DEBUG)
        self.hal['enc-door-open-max-rpm'] = self.enc_open_door_max_rpm

        # numlock status
        self.numlock_on = True
        try:
            redis_response = self.redis.hget('machine_prefs', 'numlock_on')
            if redis_response == 'True' or redis_response == None:
                self.numlock_on = True
            else:
                self.numlock_on = False
        except:
            #self.error_handler.write("exception looking for 'machine_prefs', 'numlock_on' in redis, defaulting to True", ALARM_LEVEL_LOW)
            # write to redis to avoid future messages
            self.redis.hset('machine_prefs', 'numlock_on', 'True')
        #self.checkbutton_list['numlock_on'].set_active(self.numlock_on)
        #self.set_numlock(self.numlock_on)

        # Due to what we think is a race condition between the init method and gtk's realization of the
        # notebook widget, this call doesn't always work
        self.notebook.connect("realize", self.show_enabled_notebook_tabs)

        self.alt_keyboard_shortcuts = (
            (gtk.keysyms.r, self.button_list['cycle_start']),
            (gtk.keysyms.R, self.button_list['cycle_start']),
            (gtk.keysyms.s, self.button_list['stop']),
            (gtk.keysyms.S, self.button_list['stop']),
            (gtk.keysyms.f, self.button_list['coolant']),
            (gtk.keysyms.F, self.button_list['coolant'])
        )

        self.ctrl_keyboard_shortcuts = (
            #(gtk.keysyms.a, self.button_list['foo']),
            #(gtk.keysyms.b, self.button_list['bar']),
            #(gtk.keysyms.c, self.button_list['baz'])
        )

        self._update_size_of_gremlin()

        self.window.show_all()

        if self.machineconfig.model_name() == '440':
            self.do_440_setup()

        if not self.machineconfig.has_ecm1(): #Leave showing for all ECM machines as they have m200 VFD
            self.image_list['vfd_running_led'].set_no_show_all(True)
            self.image_list['vfd_running_led'].hide()

            self.builder.get_object('vfd_running_text').set_no_show_all(True)
            self.builder.get_object('vfd_running_text').hide()

            self.image_list['vfd_fault_led'].set_no_show_all(True)
            self.image_list['vfd_fault_led'].hide()

            self.builder.get_object('vfd_fault_text').set_no_show_all(True)
            self.builder.get_object('vfd_fault_text').hide()

        # if reverse not availabe then adjust the controls
        if not self.machineconfig.has_spindle_reverse():
            self.button_list['ccw'].set_no_show_all(True)
            self.button_list['ccw'].hide()
            self.button_list['spindle_stop'].x = 690
            self.button_list['cw'].x = 759
            self.fixed.move(self.button_list['spindle_stop'], self.button_list['spindle_stop'].x, self.button_list['spindle_stop'].y)
            self.fixed.move(self.button_list['cw'], self.button_list['cw'].x, self.button_list['cw'].y)

        self.limit_switches_seen = 0          # bit flags where x = 1, y = 2, z = 4
        self.limit_switches_seen_time = 0

        # tool table filtering combobox
        self.filter_tool_table = FILTER_TOOL_TABLE_ALL_TOOLS   # All Tools on startup always to reduce tech support calls
        self.filter_tool_table_liststore = gtk.ListStore(str, int)
        self.filter_tool_table_combobox = self.builder.get_object("filter_tool_table_combobox")
        self.filter_tool_table_combobox.set_model(self.filter_tool_table_liststore)
        cell = gtk.CellRendererText()
        self.filter_tool_table_combobox.pack_start(cell, True)
        self.filter_tool_table_combobox.add_attribute(cell, 'markup', 0)
        self.filter_tool_table_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 9">All Tools</span>', FILTER_TOOL_TABLE_ALL_TOOLS])
        self.filter_tool_table_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 9">Tools Used by G-Code File</span>', FILTER_TOOL_TABLE_USED_BY_GCODE])
        self.filter_tool_table_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 9">Tools with Descriptions</span>', FILTER_TOOL_TABLE_NONBLANK_DESCRIPTIONS])
        self.filter_tool_table_liststore.append(['<span weight="normal" font_desc="Roboto Condensed 9">Tools with Values</span>', FILTER_TOOL_TABLE_NONZERO])

        self.filter_tool_table_combobox.set_property("has-tooltip", True)
        self.filter_tool_table_combobox.set_active(0)  # first row of list store = All Tools to start
        self.filter_tool_table_combobox.connect("query-tooltip", self.on_filter_combobox_querytooltip)

        # check for supported kernel version
        warning_msg = versioning.GetVersionMgr().get_kernel_mismatch_warning_msg()
        if warning_msg and not self.machineconfig.is_sim():
            self.error_handler.write(warning_msg, ALARM_LEVEL_MEDIUM)

        # do this once at init time manually to drive the proper appearance of the File tab
        self.usb_mount_unmount_event_callback()

        self.setup_jog_stepping_images()

        # Configure the A axis hardware
        self.configure_a_axis(self.machineconfig.a_axis.selected())

        self.machineconfig.a_axis.set_error_handler(self.error_handler)

        # Setup BT30 spindle offset position for orientation
        self.error_handler.log('machine spindle type is %s ' % self.machineconfig.spindle_collet_type())
        if self.machineconfig.spindle_collet_type() == machine.MachineConfig.COLLET_BT30_WITH_DOGS:
            bt30_offset_str = self.redis.hget("machine_prefs", "bt30_offset")
            bt30_offset = BT30_OFFSET_INVALID
            if bt30_offset_str != None:
                bt30_offset = int(bt30_offset_str)

            self.hal['spindle-bt30-offset'] = bt30_offset

            if bt30_offset == BT30_OFFSET_INVALID:
                self.error_handler.write('no or invalid bt30 offset found in redis', ALARM_LEVEL_DEBUG)
                self.set_image('set_tool_change_m19_image', 'Set-TC-M19-Black.png')
            else:
                bt30msg = 'bt30 offset from redis is %s' % bt30_offset_str
                self.error_handler.write(bt30msg, ALARM_LEVEL_DEBUG)
                self.set_image('set_tool_change_m19_image', 'Set-TC-M19-Green.png')
        else:
            # Hide the Set TC M19 button as its confusing on the ATC page
            # when you don't have a BT30 spindle.
            self.button_list['atc_set_tool_change_m19'].set_no_show_all(True)
            self.button_list['atc_set_tool_change_m19'].hide()

        # this takes awhile so only do this on debug runs when we are validating tool tip data on
        # startup (because some tooltips are dynamic and wire into methods created by the job assignment init)
        # NOTE: job_assignment is needed to resolve tooltip dynamic references...
        self.job_assignment = job_assignment.JAObj(ui=self)
        if __debug__:
            # expose problems with tool tip definitions right away
            tooltipmgr.TTMgr().validate_all_tooltips()

        self.error_handler.write("Mill __init__ complete - tool in spindle is %d" % self.status.tool_in_spindle, ALARM_LEVEL_DEBUG)


    def gcode_status_codes(self):
        return self.__class__._report_status

    # call optional UI hook function
    def call_ui_hook(self, method_name):
        if hasattr(self.ui_hooks, method_name):
            method = getattr(self.ui_hooks, method_name)
            self.ensure_mode(linuxcnc.MODE_MANUAL)
            method()
        else:
            self.error_handler.write("optional ui_hooks.%s() not defined" % method_name, ALARM_LEVEL_DEBUG)


    def do_440_setup(self):
        # make sure no warning on ref
        self.redis.hset('machine_prefs', 'display_door_sw_x_ref_warning', 'False')

        # no tapping
        self.builder.get_object('drill_tap_tab_label').set_text("Drill")
        self.button_list['drill_tap'].hide()
        self.conversational.routine_names['routines']['Pattern Tap']['edit'] = None
        self.conversational.routine_names['routines']['Circular Tap']['edit'] = None

        self.show_hide_injector_page(show=False)


    def show_hide_scanner_page(self, show):
        page = self.builder.get_object('scanner_fixed')
        if show:
            page.show()
            if self.scanner == None:
                self.scanner = scanner2.Scanner(self.status, render_target=self.scanner_common_camera_image)
        else:
            page.hide()


    def show_hide_injector_page(self, show):
        page = self.builder.get_object('injector_fixed')
        if show:
            page.show()
        else:
            page.hide()


    def show_usbio_interface(self):
        TormachUIBase.show_usbio_interface(self)

        # the choices in the usbio_module_liststore are added by subclasses because the pin numbering
        # text is different for mills vs. lathes.
        self.usbio_module_liststore.clear()
        self.usbio_combobox_id_to_index = {}

        if self.hal["usbio-board-0-present"]:
            self.usbio_module_liststore.append(['1  :  Pins P0 - P3'])
            self.usbio_combobox_id_to_index[0] = len(self.usbio_module_liststore)-1

        if self.hal["usbio-board-1-present"]:
            self.usbio_module_liststore.append(['2  :  Pins P4 - P7'])
            self.usbio_combobox_id_to_index[1] = len(self.usbio_module_liststore)-1

        if self.hal["usbio-board-2-present"]:
            self.usbio_module_liststore.append(['3  :  Pins P8 - P11'])
            self.usbio_combobox_id_to_index[2] = len(self.usbio_module_liststore)-1

        if self.hal["usbio-board-3-present"]:
            self.usbio_module_liststore.append(['4  :  Pins P12 - P15'])
            self.usbio_combobox_id_to_index[3] = len(self.usbio_module_liststore)-1

        # the board selected redis state is the board ID, not the index into the comboxbox.
        self.usbio_boardid_selected = 0   # default
        if self.redis.hexists('uistate', 'usbio_boardid_selected'):
            self.usbio_boardid_selected = int(self.redis.hget('uistate', 'usbio_boardid_selected'))

        if len(self.usbio_module_liststore) > 0:
            if self.usbio_boardid_selected in self.usbio_combobox_id_to_index:
                self.usbio_board_selector_combobox.set_active(self.usbio_combobox_id_to_index[self.usbio_boardid_selected])
            else:
                # boardid selected may have been stale in redis from previous time where different boards or switch settings
                # were found. Just slam it to the first available in the combobox. The combobox_changed signal handler will update
                # redis.
                self.usbio_board_selector_combobox.set_active(0)


    def setup_key_sets(self):
        """ Add custom disable jog pages for Mill UI when setting up key sets"""
        # Call parent setup function in base class
        TormachUIBase.setup_key_sets(self)

        # Define page list here since some values are redefined
        self.disable_jog_page_ids = set([
            'notebook_file_util_fixed',
            "notebook_settings_fixed",
            "conversational_fixed",
            "alarms_fixed",
        ])

    def scanner_gui_init(self):
        # Define scanner fixed regions for later use
        self.scanner_fixed = self.builder.get_object("scanner_fixed")
        # FIXME move this gtkimage to the glade file?
        self.scanner_common_camera_image = self.builder.get_object("scanner_common_camera_image")

        self.scanner = None
        if self.settings.scanner_enabled:
            self.scanner = scanner2.Scanner(self.status, render_target=self.scanner_common_camera_image)

        # Scanner Scan DROs
        self.scanner_scan_dro_list = (
            'scanner_scan_x_start_dro',
            'scanner_scan_x_end_dro',
            'scanner_scan_y_start_dro',
            'scanner_scan_y_end_dro')

        scanner_dro_font_description  = pango.FontDescription('helvetica ultra-condensed 22')
        self.scanner_scan_dro_list = dict(((i, self.builder.get_object(i))) for i in self.scanner_scan_dro_list)
        for name, dro in self.scanner_scan_dro_list.iteritems():
            dro.modify_font(scanner_dro_font_description)
            dro.masked = False

        if self.scanner:
            #KLUDGE scanner specific stuff should only happen if scanner is enabled?
            self.scanner.set_render_target(self.scanner_common_camera_image)

        ##############################################################
        # Initialize scanner DRO's
        # TODO: move to separate init function, pass in list of DRO's?

        self.scanner_brightness_adjustment = self.builder.get_object("scanner_brightness_adjustment")
        self.scanner_brightness_scale = self.builder.get_object("scanner_brightness_scale")
        self.scanner_brightness_scale.connect("scroll-event", self.on_mouse_wheel_event)
        self.scanner_brightness_adj_label = self.builder.get_object("scanner_brightness_adj_label")
        self.scanner_brightness_adjustment.set_value(50)

        self.scanner_contrast_adjustment = self.builder.get_object("scanner_contrast_adjustment")
        self.scanner_contrast_scale = self.builder.get_object("scanner_contrast_scale")
        self.scanner_contrast_scale.connect("scroll-event", self.on_mouse_wheel_event)
        self.scanner_contrast_adj_label = self.builder.get_object("scanner_contrast_adj_label")
        self.scanner_contrast_adjustment.set_value(50)

        self.scanner_scope_circle_dia_adjustment = self.builder.get_object("scanner_scope_circle_dia_adjustment")
        self.scanner_scope_circle_dia_scale = self.builder.get_object("scanner_scope_circle_dia_scale")
        self.scanner_scope_circle_dia_scale.connect("scroll-event", self.on_mouse_wheel_event)
        self.scanner_scope_circle_dia_adj_label = self.builder.get_object("scanner_scope_circle_dia_adj_label")
        self.scanner_scope_circle_dia_adjustment.set_value(30)

        self.scanner_status_textview = self.builder.get_object('scanner_status_textview')
        self.scanner_status_textbuffer = self.scanner_status_textview.get_buffer()
        self.scanner_status_textbuffer.set_text("Camera Status")

        self.scanner_common_working_fov_adjustment = self.builder.get_object('scanner_common_working_fov_adjustment')
        self.scanner_common_working_fov_hscrollbar = self.builder.get_object('scanner_common_working_fov_hscrollbar')
        self.scanner_common_working_fov_hscrollbar.connect("scroll-event", self.on_mouse_wheel_event)
        self.scanner_common_working_fov_adj_label = self.builder.get_object("scanner_common_working_fov_adj_label")
        self.scanner_common_working_fov_adjustment.set_value(70)
        self.scanner_common_working_fov_adj_label.set_text('70%')

        self.scanner_calibration_p1_text = self.builder.get_object('scanner_calibration_p1_text')
        self.scanner_calibration_p2_text = self.builder.get_object('scanner_calibration_p2_text')

        self.scanner_calibration_scale_text = self.builder.get_object('scanner_calibration_scale_text')

        # Define update function to poll camera and capture frames at slightly
        # faster than 30Hz to prevent frames from buffering up
        glib.timeout_add(65, self.scanner_periodic, priority=glib.PRIORITY_DEFAULT_IDLE)


    def scope_gui_init(self):
        """ Initialize objects in scanner scope tab of camera notebook"""

        # -----------------------------------------
        # scope table init (gtk.treeview)
        # -----------------------------------------
        self.scanner_scope_fixed = self.builder.get_object("scanner_scope_fixed")
        scope_font = pango.FontDescription('helvetica ultra-condensed 22')
        scope_i_font = pango.FontDescription('helvetica ultra-condensed 18')
        self.scope_row = 0

        self.scope_liststore = gtk.ListStore(str, str, str)

        for id_cnt  in range(1, self.DRILL_TABLE_ROWS + 1):
            self.scope_liststore.append([id_cnt, '', ''])

        self.scope_treeview = gtk.TreeView(self.scope_liststore)

        self.scope_i_column  = gtk.TreeViewColumn()
        self.scope_x_column  = gtk.TreeViewColumn('')
        self.scope_y_column  = gtk.TreeViewColumn('')

        self.scope_treeview.append_column(self.scope_i_column)
        self.scope_treeview.append_column(self.scope_x_column)
        self.scope_treeview.append_column(self.scope_y_column)

        self.scope_treeview.set_rules_hint(True)
        self.scope_treeview.set_headers_visible(False)
        self.scope_treeview.set_grid_lines(gtk.TREE_VIEW_GRID_LINES_BOTH)

        scope_i_renderer = gtk.CellRendererText()
        scope_i_renderer.set_property('editable', False)
        scope_i_renderer.set_property('cell-background', '#EEBBBB')
        scope_i_renderer.set_property('font-desc', scope_i_font)
        scope_i_renderer.set_property('xalign',0.5)
        self.scope_i_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.scope_i_column.set_fixed_width(30)
        self.scope_i_column.pack_start(scope_i_renderer, True)
        self.scope_i_column.set_attributes(scope_i_renderer, text=0)

        scope_x_renderer = gtk.CellRendererText()
        scope_x_renderer.set_property('editable', True)
        scope_x_renderer.set_property('font-desc', scope_font)
        scope_x_renderer.set_property('xalign',0.8)
        self.scope_x_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.scope_x_column.set_fixed_width(105)
        self.scope_x_column.pack_start(scope_x_renderer, True)
        self.scope_x_column.set_attributes(scope_x_renderer, text=1)
        scope_x_renderer.connect('edited', self.on_scope_x_column_edited, self.scope_liststore)

        scope_y_renderer = gtk.CellRendererText()
        scope_y_renderer.set_property('editable', True)
        scope_y_renderer.set_property('font-desc', scope_font)
        scope_y_renderer.set_property('xalign',0.8)
        self.scope_y_column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.scope_y_column.set_fixed_width(105)
        self.scope_y_column.pack_start(scope_y_renderer, True)
        self.scope_y_column.set_attributes(scope_y_renderer, text=2)
        scope_y_renderer.connect('edited', self.on_scope_y_column_edited, self.scope_liststore)

        #scope_x_renderer.connect('editing-started', self.on_scope_x_column_editing_started, scope_font)
        #scope_y_renderer.connect('editing-started', self.on_scope_y_column_editing_started, scope_font)
        self.scope_x_renderer = scope_x_renderer
        self.scope_y_renderer = scope_y_renderer

        # show in notebook

        # create a scrolled window to hold the treeview
        self.scrolled_window_scope_table = gtk.ScrolledWindow()
        self.scrolled_window_scope_table.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

        self.scanner_scope_fixed.put(self.scrolled_window_scope_table, 10, 120)
        # the treeview knows about scrolling so do NOT add it using add_with_viewport or you
        # break all inherent keyboard navigation.
        self.scrolled_window_scope_table.add(self.scope_treeview)
        self.scrolled_window_scope_table.set_size_request(270, 200)

    def dxf_gui_init(self):
        self.dxf_panel = MillD2gPanel(self, self.conv_dro_list)
        self.dxf_panel.connect('errored', self.on_dxf_panel_errored)
        self.dxf_panel.connect('open-file-requested', self.on_dxf_file_requested)
        self.dxf_panel.get_tool_diameter_cb = self.on_dxf_panel_get_tool_diameter
        self.dxf_panel.validate_and_format_dro_cb = self.on_dxf_validate_and_format_dro
        self.dxf_panel.gui_is_metric_cb = lambda: self.g21
        self.dxf_panel.get_plexiglass_cb = lambda: plexiglass.PlexiglassInstance(singletons.g_Machine.window)
        self.dxf_panel.restore_dros(self.redis.hgetall('conversational'))

        self.create_page_DRO_attributes(page_id='conv_dxf_fixed',
            common=self.conv_dro_list,spec=self.dxf_panel._dxf_dro_list,
            tool=self.conv_dro_list['conv_tool_number_dro'],
            rpm=self.conv_dro_list['conv_rpm_dro'],
            r_feed=self.conv_dro_list['conv_feed_dro'],
            z_feed=self.conv_dro_list['conv_z_feed_dro'],
            r_doc=self.dxf_panel._dxf_dro_list['dxf_z_slice_depth_dro'])

        #Add the DXF2Gcode fixed panel to the conversational notebook
        self.add_conversational_page(self.dxf_panel.panel_fixed, "DXF (Mill)")

        self.start_dxf2gcode()

    def start_dxf2gcode(self):
        config_folder = os.path.join(LINUXCNC_HOME_DIR, 'configs/tormach_{:s}/dxf2gcode'.format(self.machineconfig.machine_class()))
        process = subprocess.Popen(['dxf2gcode_dbus', '--config-folder', config_folder])
        self.dxf2gcode_pid = process.pid

    def load_dxf_file(self, path, plot=True):
        set_current_notebook_page_by_id(self.notebook, 'conversational_fixed')
        self.set_conv_page_from_id('conv_dxf_fixed')
        self.window.set_focus(None)
        # Large files can take a long time so give some feedback with busy cursor
        self.dxf_panel.load_dxf_file(path, plot)

    def on_dxf_panel_errored(self, _widget, message):
        self.error_handler.write(message, ALARM_LEVEL_MEDIUM)

    def on_dxf_file_requested(self, _widget):
        self.window.set_focus(None)
        with tormach_file_util.file_open_popup(self.window, os.path.dirname(self.get_current_gcode_path()), '*.[dD][xX][fF]') as dialog:
            if dialog.response != gtk.RESPONSE_OK:
                return
            # Extract dialog information for later use
            path = dialog.get_path()
        if path:
            basepath, ext = os.path.splitext(path)
            if ext.upper() == '.DXF':
                self.load_dxf_file(path)

    def on_dxf_panel_get_tool_diameter(self, index):
        if (index >= 0) and (index < len(self.status.tool_table)):
            return self.status.tool_table[index].diameter * self.ttable_conv
        else:
            return 0.0

    def on_dxf_validate_and_format_dro(self, widget, format_):
        (valid, number, error_msg) = self.conversational.validate_param(widget, is_metric=self.g21, update_alarms=format_)
        if format_:
            if not valid:
                self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            else:
                widget.set_text('%s' % self.dro_long_format % number)
        return valid

    # ----------------------------------------------------------------------------------------------
    # feeds and speeds related ...
    #-----------------------------------------------------------------------------------------------

    def update_feeds_speeds(self):
        # this may get called before 'fs' is created..
        assert self.fs_mgr, "Fix the call path and init order - why is this getting called now?"
        if not self.fs_mgr: return

        valid, problem = self.fs_mgr.update_feeds_speeds()
        if not valid: self.error_handler.write(problem, ALARM_LEVEL_LOW)

    def feeds_speeds_update_advised(self):
        self.material_data.update_btn_on()

    # ----------------------------------------------------------
    # callbacks
    # ----------------------------------------------------------
    def get_linear_scale(self):
        """Return the scale factor for all linear axes based on current G20/G21 mode"""
        return 25.4 if self.g21 else 1.0

    def get_axis_scale(self, axis_ind):
        return self.get_linear_scale() if axis_ind < 3 else 1.0

    def setup_font_selector(self):
        """ Create font selector for conversational engraving"""
        num_fonts = 0
        if not is_ttlib:  # do we have font utilities?
            return num_fonts
        if not os.path.isdir(ENGRAVING_FONTS_DIR):  # do we have a font directory?
            return num_fonts

        # preserve the current selection by font file name, not by index
        selected_font_file_name = None
        if len(self.font_file_list) > 0:
            selected_font_file_name = self.font_file_list[self.engrave_font_row]

        # build (or rebuild) the entire font list now from the directory
        self.font_file_list = []
        ef_name = ''
        ef_family = ''

        dirlist = os.listdir(ENGRAVING_FONTS_DIR)
        if len(dirlist) == 0:
            # folder is empty
            self.error_handler.write("engraving_fonts folder is empty.", ALARM_LEVEL_LOW)
            return num_fonts

        for engrave_font_file in dirlist:  # presort
            # only want files -- not directories, too
            if os.path.isfile(os.path.join(ENGRAVING_FONTS_DIR, engrave_font_file)):
                self.font_file_list.append(engrave_font_file)

        self.font_file_list = sorted(self.font_file_list)

        self.engrave_font_liststore = gtk.ListStore(str, str)  # file name, (name, family)

        for engrave_font_file in self.font_file_list:  # validate and build liststore
            try:
                (ef_name, ef_family) = self.get_ttfont_name(os.path.join(ENGRAVING_FONTS_DIR, engrave_font_file))
            except:
                pass

            if ef_name and ef_family:
                self.error_handler.write("Found engraving font: %s." % engrave_font_file, ALARM_LEVEL_DEBUG)
                self.engrave_font_liststore.append([
                    ('<span font_desc="Roboto Condensed 14">%s</span>' %
                     engrave_font_file),
                    ('<span font_family="%s" font_desc="%s 14" foreground="blue">AaBbGgYy12370</span>' %
                     (ef_family, ef_name))])

        try:
            # generates exception if TreeView not yet created
            # no need for full TreeView initialization
            # only need to set the new model
            self.engrave_font_treeview.set_model(self.engrave_font_liststore)

        except AttributeError:
            # first time through will get this exception for TreeView.set_model()
            self.engrave_font_treeview = gtk.TreeView(self.engrave_font_liststore)
            font_column_renderer = gtk.CellRendererText()
            font_column = gtk.TreeViewColumn('Font', font_column_renderer, markup=0)
            self.engrave_font_treeview.append_column(font_column)
            self.engrave_font_treeview.set_search_column(0)
            self.engrave_font_treeview.set_search_equal_func(engrave_font_name_search_callback, self)

            sample_column_renderer = gtk.CellRendererText()
            sample_column =  gtk.TreeViewColumn('Sample', sample_column_renderer, markup=1)
            self.engrave_font_treeview.append_column(sample_column)

            self.engrave_font_treeview.set_headers_visible(False)

            self.scrolled_window_engrave_font = gtk.ScrolledWindow()
            self.scrolled_window_engrave_font.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

            self.conv_engrave_fixed.put(self.scrolled_window_engrave_font, 55, 66)
            # the treeview knows about scrolling so do NOT add it using add_with_viewport or you
            # break all inherent keyboard navigation.
            self.scrolled_window_engrave_font.add(self.engrave_font_treeview)
            self.scrolled_window_engrave_font.set_size_request(450, 175)

            # events to handle
            self.engrave_font_treeview.connect("cursor_changed", self.on_engrave_font_tview_cursor_changed)  # centers active row, updates sample


        self.engrave_font_row = 0   # reset the row in case we have no selection or former selection got deleted
        if selected_font_file_name:
            for ix in range(len(self.font_file_list)):
                if selected_font_file_name == self.font_file_list[ix]:
                    self.engrave_font_row = ix
                    break

        tvselection = self.engrave_font_treeview.get_selection()
        tvselection.select_path(self.engrave_font_row)
        self.engrave_font_treeview.scroll_to_cell(self.engrave_font_row)
        self.engrave_font_pf = os.path.join(ENGRAVING_FONTS_DIR, self.font_file_list[self.engrave_font_row])

        # update the engrave text DRO with the new font selection
        self.engrave_sample_update()

        return False  # Must return False as this is called from glib.idle_add() sometimes (otherwise could fall into infinite loop)


    def on_filter_combobox_querytooltip(self, widget, x, y, keyboard_mode, tooltip, data=None):
        # generic and used by both the tool table filtering combobox and the work offsets filtering combobox
        ev = gtk.gdk.Event(gtk.gdk.ENTER_NOTIFY)
        display = gtk.gdk.display_get_default()
        screen, xroot, yroot, mod = display.get_pointer()
        ev.x_root = float(xroot)
        ev.y_root = float(yroot)
        tooltipmgr.TTMgr().on_mouse_enter(widget, ev)
        return False


    def load_gcode_file(self, path):
        if self.moving():
            if self.feedhold_active.is_set():
                self.error_handler.write("Machine is in feedhold - press stop or reset to clear feedhold before loading a g code program")
                return
            self.error_handler.write("Cannot load a g code program while machine is moving.")
            return

        self.use_hal_gcode_timers = False

        # Call base class behavior
        TormachUIBase.load_gcode_file(self, path)

        self.gremlin_load_needs_plexiglass = False   # be optimistic

        # switch to gcode listing MDI main tab
        if not self.interp_alarm:
            self.notebook.set_current_page(self.notebook.page_num(self.notebook_main_fixed))
        self.window.set_focus(None)

        # Large files can take a long time so give some feedback with busy cursor
        with plexiglass.PlexiglassInstance(singletons.g_Machine.window) as p:

            self.is_gcode_program_loaded = True

            # see if we're simply reloading the same file after somebody tweaked it.
            same_file_reload = (self.get_current_gcode_path() == path)

            # remember what was last loaded to watch for changes on disk and reload
            self.set_current_gcode_path(path)
            if not path:
                self.gcodelisting_buffer.set_text('')
                return

            # note the time stamp
            st = os.stat(path)
            self.gcode_file_mtime = st.st_mtime

            # disable syntax coloring for files larger than 2 MB because
            # gedit and the gtksourceview widget suck for performance and memory use when trying to
            # syntax color large files. A 1M line (35 MB) g-code file took 10-15 minutes to load and used
            # hundreds of megabytes of extra ram.
            if st.st_size > (2*1024*1024):
                self.set_gcode_syntaxcoloring(False)
                self.error_handler.write('Disabled g-code colors due to large file size for better performance.', ALARM_LEVEL_LOW)

            # prevent changes to the combo box from causing file loads
            self.combobox_masked = True
            # remove filename from previous model position if it was previously in the model
            sort_file_history(self.file_history_liststore, path, None)
            # add filename, path to the model
            self.file_history_liststore.prepend([os.path.basename(path), path])

            # have to set active one, else the active file won't be displayed on the combobox
            self.loaded_gcode_filename_combobox.set_active(0)

            # unmask
            self.combobox_masked = False

            # read file directly into buffer
            tormach_file_util.open_text_file(self, path, self.gcodelisting_buffer)

            # can change this with right-click menu in source view
            # this is one based, the textbuffer is zero based
            self.gcode_start_line = 1
            # must switch to mdi, then back to force clear of _setup.file_pointer, otherwise
            # we can't open a program if one is already open
            self.ensure_mode(linuxcnc.MODE_MDI)
            # load file into LinuxCNC
            self.ensure_mode(linuxcnc.MODE_AUTO)

            # We read the whole g-code file into memory at once.  But linuxcnc doesn't.  This can
            # cause all sorts of confusing behavior if the file is updated from another computer.
            # Reliable solution is to always copy the entire g-code file to a spot the user cannot
            # see or maniuplate and tell linuxcnc to load that file.  Then its behavior will be consistent
            # with the UI and it won't start using new file data until the user answers the "File changed, reload?"
            # dialog prompt.
            #
            # shutil.copy2 retains attributes such as date/time
            shutil.copy2(path, LINUXCNC_GCODE_FILE_PATH)

            # Sigh.  We can't actually do this here currently, even though it appears correct. program_close() currently
            # re-inits the g-code interpreter state from the .ini file. So just the act of loading a file (but not executing any of it)
            # will change modal interp state.  Worst impact example is if you were in G21 and then load a file, you end up in G20.
            # Long term fix is stopping program_close() from calling the interp init() method, but that needs closer examination.
            # 10/07/2019 jwf  PP-2647
            #self.command.program_close()
            #self.command.wait_complete()

            self.command.program_open(LINUXCNC_GCODE_FILE_PATH)

            # gremlin is unpredictable at the moment
            # wrap it for exceptions
            try:
                self.gremlin.clear_live_plotter()
            except Exception as e:
                self.error_handler.write("gremlin.clear_live_plotter() raised an exception", ALARM_LEVEL_DEBUG)
                msg = "An exception of type {0} occured, these were the arguments:\n{1!r}"
                self.error_handler.write(msg.format(type(e).__name__, e.args), ALARM_LEVEL_DEBUG)
                #traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))

            try:
                # with no filename given, gremlin will ask LinuxCNC for the filename
                loadtm = timer.Stopwatch()
                result, seq, warnings = self.gremlin.load()
                seconds = loadtm.get_elapsed_seconds()
                self.error_handler.write("gremlin.load of %s took %f seconds" % (path, seconds), ALARM_LEVEL_DEBUG)
                if seconds > 2.0:
                    # we must have a larger or complicated file as it took gremlin over 2 seconds
                    # to load the file.
                    # set the flag so that all future gremlin.load() calls are plexiglassed
                    self.error_handler.write("gremlin.load took too long so future gremlin.load on this file will use plexiglass", ALARM_LEVEL_DEBUG)
                    self.gremlin_load_needs_plexiglass = True

                #Quick way to dump warnings to status window
                self.gremlin.report_gcode_warnings(warnings,os.path.basename(path))

            except Exception as e:
                self.error_handler.write("gremlin.load() raised an exception", ALARM_LEVEL_DEBUG)
                msg = "An exception of type {0} occured, these were the arguments:\n{1!r}"
                self.error_handler.write(msg.format(type(e).__name__, e.args), ALARM_LEVEL_DEBUG)
                #traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))

            # this makes sure that the previous "next" line in the gcode display doesn't errantly
            # show the line from the PREVIOUS gcode program loaded.
            try:
                self.gremlin.set_highlight_line(None)
            except Exception as e:
                self.error_handler.write("gremlin.set_highlight_line() raised an exception", ALARM_LEVEL_DEBUG)
                msg = "An exception of type {0} occured, these were the arguments:\n{1!r}"
                self.error_handler.write(msg.format(type(e).__name__, e.args), ALARM_LEVEL_DEBUG)

            try:
                self.gremlin.set_top_view()
            except Exception as e:
                self.error_handler.write("gremlin.set_top_view raised an exception", ALARM_LEVEL_DEBUG)
                msg = "An exception of type {0} occured, these were the arguments:\n{1!r}"
                self.error_handler.write(msg.format(type(e).__name__, e.args), ALARM_LEVEL_DEBUG)
                #traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))

            self.last_runtime_sec = self.stats_mgr.get_last_runtime_sec()

            # this list of integer tool numbers is in the order the program uses them and will contain duplicates
            self.gcode_program_tools_used = self.gremlin.get_tools_used()

            # force refresh the tool list store as we color code it based on if the tools are used by the program or not
            self.refresh_tool_liststore(forced_refresh=True)

            self.gremlin_options.show_all_tools()


        # complete switching to main MDI tab after loading is done
        self.gcodelisting_mark_start_line()
        self.gcode_pattern_search.on_load_gcode()
        self.lineno_for_last_m1_image_attempt = 0

        # only reset the override slider values if we're changing files entirely. otherwise from your last run to this one
        # you may have been dialing in your sliders and then we whack them on you.
        if not same_file_reload:
            self.safely_reset_override_slider_values()


    # MDI line
    # most of this moved to ui_common

    def on_mdi_line_activate(self, widget):
        self.mdi_history_index = -1
        command_text = self.mdi_line.get_text()
        # remove leading white space
        command_text = command_text.lstrip()
        # remove trailing white space
        command_text = command_text.rstrip()
        # ignore empty command text
        if len(command_text) == 0:
            # empty command text means "give up focus" so I can now jog easily from the keyboard
            self.window.set_focus(None)
            return

        # insert into history
        self.mdi_history.insert(0, command_text)
        history_len = len(self.mdi_history)
        # limit number of history entries
        if history_len > self.mdi_history_max_entry_count:
            # remove oldest entry
            self.mdi_history.pop()
        # delete second occurance of this command if present
        try:
            second_occurance = self.mdi_history.index(command_text, 1)
            if second_occurance > 0:
                self.mdi_history.pop(second_occurance)
        except ValueError:
            # not a problem
            pass

        if (self.mdi_find_command(command_text)):
            return

        if (self.mdi_admin_commands(command_text)):
            return

        if not (self.x_referenced and self.y_referenced and self.z_referenced):
            self.error_handler.write("Must reference X, Y, and Z axes before issuing command: " + command_text, ALARM_LEVEL_MEDIUM)
            self.mdi_line.set_text("")
            self.window.set_focus(None)
            return

        #KLUDGE test for exclusive MDI access by other stuff (scanner, etc.)
        if self.scanner and self.scanner.moving():
            self.error_handler.write('Cannot execute an MDI motion during a scan')
            return

        # do the command
        self.issue_mdi(command_text)

        # clear the text on the input line
        self.mdi_line.set_text("")


    # ---------------------------------------
    # Program Control Group
    # ---------------------------------------

    def on_cycle_start_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        # Call base class behavior
        abort_action = TormachUIBase.on_cycle_start_button(self)
        if abort_action:
            return

        #KLUDGE check for scanner running
        #TODO refactor this to handle pre-conditions more consistently
        if self.scanner and self.scanner.moving():
            if self.feedhold_active.is_set():
                self.feedhold_active.clear()
                return
            else:
                self.error_handler.write('Cannot start program during a scan')
                return

        if self.status.axis[0]['homing'] or self.status.axis[1]['homing'] or self.status.axis[2]['homing']:
            self.error_handler.write('Cannot start program while machine is referencing')
            return

        if self.door_open_status:
            self.error_handler.write("Must close enclosure door before starting program", ALARM_LEVEL_LOW)
            return

        # cycle start after text line message in Gremlin
        # order of these is important.  Answer queries first, then check for random stop/reset presses
        if self.notify_at_cycle_start:  # is anyone waiting on us
            self.notify_at_cycle_start = False

            if not self.lock_enclosure_door():
                # door lock failure.  must abort.
                self.set_response_cancel()
                return

            # Clue in the ATC that cycle start was pressed.
            try:
                self.redis.hset("TormachAnswers", self.notify_answer_key, "Y")  #start pressed message
                self.hal['prompt-reply'] = 1
                self.error_handler.write("prompt output pin set to 1 by cycle start", ALARM_LEVEL_DEBUG)
            except Exception as e:
                traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))
                self.error_handler.write("Whooops! - Tormach message reply not set to Y. Exception: %s" % traceback_txt, ALARM_LEVEL_DEBUG)

            # only return early if we aren't in this specific situation:
            #   - ATC python or ngc code asked the user to insert/remove tools and is busy waiting
            #   - user opens the door, which then triggers a feedhold, interpreter pause, and coolant state change
            #   - user clicks cycle start to resume
            # in those conditions we would early out here and not perform the actions needed to clear the feedhold
            # so the user would have to click Cycle Start again a second time because we were still in feedhold = confusing
            if (self.status.paused and self.program_paused_for_door_sw_open and self.feedhold_active.is_set()) == False:
                return  # wake up process waiting on message answer

        if not self.atc.feed_hold_clear.is_set():     # we are only resuming a change operation now
            self.atc.feed_hold_clear.set()            # feedhold cleared by cycle start so set event to unblock ATC worker thread
            self.set_image('feedhold_image', 'Feedhold-Black.jpg')
            if self.status.paused:   #start up operation even if on ATC page
                if self.single_block_active:
                    # Hack to fix "queueing" behavior where pushing cycle start
                    # multiple times steps through multiple segments
                    if self.status.current_vel < 1e-9:
                        self.command.auto(linuxcnc.AUTO_STEP)
                else:
                    self.command.auto(linuxcnc.AUTO_RESUME)
            return   #continue changing


        if self.current_notebook_page_id != 'notebook_main_fixed':
            self.error_handler.write("Cannot start program while not on Main screen", ALARM_LEVEL_LOW)
            return

        if not (self.x_referenced and self.y_referenced and self.z_referenced):
            self.error_handler.write("Must reference X, Y, and Z axes before executing a gcode program", ALARM_LEVEL_MEDIUM)
            return

        if self.program_paused_for_door_sw_open:
            self.error_handler.write("Resuming program because door sw was closed", ALARM_LEVEL_DEBUG)
            self.program_paused_for_door_sw_open = False
            # iocontrol.coolant is checked in the 50ms periodic.  If it doesn't match the previous state,
            # we flip the hal.coolant bit accordingly.  This next line will force this to happen
            self.prev_coolant_iocontrol = not self.hal['coolant-iocontrol']

        # pressing CS should always clear feedhold
        self.feedhold_active.clear()
        self.set_image('feedhold_image', 'Feedhold-Black.jpg')

        self.hide_m1_image()
        self.use_hal_gcode_timers = True

        # make sure we aren't walking and chewing gum at same time. Cycle start can sneak in between
        # process queue thread requests. Any problems clearing the tray require human intervention.
        # Also, we need to make sure we aren't just cycle starting a halted M6 remap here.

        if self.atc.operational and (not self.hal['atc-ngc-running']):   #now check the tray
            r = self.atc.cycle_start()
            if r == 'queue active':
                self.error_handler.write('ATC - Wait until action in process completes, then try again', ALARM_LEVEL_MEDIUM)
                return
            if r == 'tray in':  #returned with problem clearing tool tray automatically
                self.error_handler.write('ATC - Retract tool tray before cycle start', ALARM_LEVEL_MEDIUM)
                self.command.auto(linuxcnc.AUTO_PAUSE)

        # about to light it up so lock the door
        if not self.lock_enclosure_door():
            # failed to lock the door must abort - above method already issues error to status page
            return

        # if status.paused, we're already in MODE_AUTO, so resume the program
        if self.status.paused:
            if self.single_block_active:
                self.command.auto(linuxcnc.AUTO_STEP)
            else:
                self.command.auto(linuxcnc.AUTO_RESUME)
                return

        if not self.is_gcode_program_loaded:
            self.error_handler.write("Must load a g-code program before pressing cycle start.", ALARM_LEVEL_MEDIUM)
            return

        # this helps avoid cycle start button presses while a program is already running from causing
        # extra log lines and messing up the remaining time clock.
        if not self.program_running():
            # if we are starting the program at the beginning then load up
            # the last runtime so we can calculate remaining time
            if self.gcode_start_line <= 1:
                self.last_runtime_sec = self.stats_mgr.get_last_runtime_sec()

            if self.is_gcode_program_loaded:
                self.stats_mgr.log_cycle_start(self.gcode_start_line)

            # clear live plotter if the last program ran to completion and ended gracefully
            # or if the program is starting at the beginning.
            # only time an existing live plot tool path is valuable to retain is when
            # starting from the middle of the program and you want to discern when old vs. new cuts
            # might be happening.
            if self.status.program_ended or self.status.program_ended_and_reset or (self.gcode_start_line <= 1):
                self.gremlin.clear_live_plotter()

        # now that stop button doesn't slam the gcode listing to line 0, be sure the
        # current start line is visible if we're just kicking things off.  If we're
        # single blocking and nailing cycle start button all the time, current_line
        # won't be zero so we avoid flashing the window.
        if self.status.current_line == 0:
            self.sourceview.scroll_to_mark(self.gcodelisting_start_mark, 0, True, 0, 0.5)
            self.gcodelisting_mark_current_line(self.gcode_start_line)

        self.gcode_pattern_search.clear()
        # Otherwise, switch to MODE_AUTO and run the code
        if self.status.interp_state == linuxcnc.INTERP_IDLE:
            self.ensure_mode(linuxcnc.MODE_AUTO)
            if self.single_block_active:
                #Starting for the first time in single block mode
                #Takes 3 steps to execute the first line
                if self.gcode_start_line != 1:
                    self.error_handler.log("Cycle start with {:d} as gcode start line".format(self.gcode_start_line))
                    self.command.auto(linuxcnc.AUTO_RUN, self.gcode_start_line)
                    self.command.auto(linuxcnc.AUTO_PAUSE)
                    self.command.auto(linuxcnc.AUTO_STEP)
                else:
                    self.command.auto(linuxcnc.AUTO_STEP)
            else:
                self.error_handler.log("Cycle start with {:d} as gcode start line".format(self.gcode_start_line))
                self.command.auto(linuxcnc.AUTO_RUN, self.gcode_start_line)


    def lock_enclosure_door(self):
        if self.machineconfig.has_door_lock() and self.settings.door_sw_enabled:
            self.error_handler.log("Attempting to lock enclosure door.")

            self.hal['enc-door-lock-drive'] = 1

            sw = timer.Stopwatch()
            while self.hal['enc-door-locked-status'] == 0:
                if sw.get_elapsed_seconds() >= 0.5:
                    # door lock is broken
                    self.error_handler.log("Enclosure door locked status never went high in 500 milliseconds.  Aborting.")
                    self.error_handler.write("Enclosure door failed to lock. Check door lock assembly for proper function and wiring.", ALARM_LEVEL_HIGH)
                    return False
                time.sleep(0.05)  # 50 milliseconds
            self.error_handler.log("Enclosure door locked status is 1.  Door is locked.")

        # if no lock, pretend its locked as it makes code maintenance easier
        return True


    def unlock_enclosure_door(self):
        if self.machineconfig.has_door_lock() and self.settings.door_sw_enabled:
            log = False
            if self.hal['enc-door-lock-drive'] == 1:
                # only do this on the actual state transition to 0 or it gets too noisy in the log
                # as this is called repeatedly in the 500ms periodic at certain times.
                log = True
                self.error_handler.log("Attempting to unlock enclosure door.")

            self.hal['enc-door-lock-drive'] = 0

            # don't bother waiting or logging errors if machine-ok is down because the lock solenoid
            # won't have power and can't possibly unlock the door anyway.  We just fill up the log
            # otherwise.
            if self.hal['machine-ok']:
                sw = timer.Stopwatch()
                while self.hal['enc-door-locked-status'] == 1:
                    if sw.get_elapsed_seconds() >= 0.5:
                        # door lock is broken or there's pressure on the door lock and the solenoid can't be released properly
                        self.error_handler.log("Enclosure door locked status never went low in 500 milliseconds.")
                        self.error_handler.write("Enclosure door failed to unlock.  Push doors closed to release any tension on door lock solenoid assembly and try again.", ALARM_LEVEL_HIGH)
                        return False

                    if sw.get_elapsed_seconds() >= 0.4:
                        # as a last ditch effort try toggling the solenoid
                        self.hal['enc-door-lock-drive'] = 1
                        time.sleep(0.05)  # 50 milliseconds
                        self.hal['enc-door-lock-drive'] = 0
                        self.error_handler.log("Enclosure door locked status never went low in 400 milliseconds so trying to toggle it.")

                    time.sleep(0.05)  # 50 milliseconds

                if log:
                    self.error_handler.log("Enclosure door locked status is 0.  Door is unlocked.")
            else:
                return False

        return True


    def on_single_block_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # unconditionally set sb_active flag and button image
        if self.single_block_active:
            self.single_block_active = False
            self.set_image('single_block_image', 'Single-Block-Black.jpg')
        else:
            self.single_block_active = True
            self.set_image('single_block_image', 'Single-Block-Green.jpg')

        # if machine is in feedhold, do notihing (SB button press should not cause machine to come out of feedhold)
        if self.feedhold_active.is_set(): return
        if self.command_in_progress():
            if not self.single_block_active:
                # only do the auto_resume if we're already in the middle of a move!
                if self.status.current_vel != 0:
                    self.command.auto(linuxcnc.AUTO_RESUME)
            else:
                self.command.auto(linuxcnc.AUTO_PAUSE)
                self.command.auto(linuxcnc.AUTO_STEP)



    def on_m01_break_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if  self.m01_break_active:
            self.command.set_optional_stop(False)
            self.m01_break_active = False
            self.set_image('m01_break_image', 'M01-Break-Black.jpg')
        else:
            self.command.set_optional_stop(True)
            self.m01_break_active = True
            self.set_image('m01_break_image', 'M01-Break-Green.jpg')


    def on_feedhold_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        # should have no effect when the machine isn't moving, except in middle of atc cycle
        if self.atc.in_a_thread.is_set():  #if a thread is running, hold on til cycle start
            self.atc.feed_hold_clear.clear()
            self.command.auto(linuxcnc.AUTO_PAUSE)
            self.set_image('feedhold_image', 'Feedhold-Green.jpg')

        #KLUDGE set feedhold active so that the scanner thread knows
        if self.scanner and self.scanner.moving():
            self.feedhold_active.set()

        if self.moving():
            if not self.feedhold_active.is_set():
                self.command.auto(linuxcnc.AUTO_PAUSE)
                self.feedhold_active.set()
                self.set_image('feedhold_image', 'Feedhold-Green.jpg')

            self.unlock_enclosure_door()


    def on_stop_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.hide_m1_image()
        self.clear_message_line_text()
        self.stop_motion_safely()
        self.set_response_cancel()  # check for outstanding user prompts and cancel
        self.call_ui_hook('stop_button')
        if self.scanner is not None:
            self.scanner.stop_threads()
        self.unlock_enclosure_door()

        # Make sure the override sliders are enabled.  The ATC code disables them and tries to restore them, but
        # in certain aborted situations, they can get stuck off.
        self.command.set_feed_override(True)
        self.command.set_spindle_override(True)


    # Function to actually do halcmd calls to "dynamically" reconfigure HAL, or whatever other future backend functions
    # may need to be called to initialize an A axis.

    def configure_a_axis(self, new_axis):
        # TODO:
        # In addition to the dyn_dict keys (a.k.a. .ini defines) used below there are the following possible
        # MAX_VELOCITY, MAX_ACCELERATION, MAX_JOG_VELOCITY_UPS, MIN_JOG_VELOCITY_UPS, MAX_ANGULAR_VELOCITY
        # that could/should be added to the dyn_dict

        #Master dictionary of all possible "dynamic" variables and their matching HAL "back end"
        # the unimplemented elifs below don't have such mapping and will have to do something other than
        # halcmd calls
        dyn_dict = {'SCALE' : 'position-scale',
                    'STEPGEN_MAX_VEL' : 'maxvel',
                    'STEPGEN_MAXACCEL' : 'maxaccel' }

        board = self.inifile.find("HOSTMOT2", "BOARD")
        if board == None:
            self.error_handler.log("In simulator, no axis scale to set")

        hal_label = None

        #iterate through all the possible dyn_dict keys, setting the corresponding variables into HAL
        for dyn_key in dyn_dict.keys():
            if dyn_key == 'SCALE':
                hal_label = dyn_dict[dyn_key]
            #elif dyn_key == 'MAX_VELOCITY': ##tormach mill_ui.py line 257 ""
            #    hal_label = None
            #elif dyn_key == 'MAX_ACCELERATION': #tormach mill_ui.py line 257
            #    hal_label = None
            elif dyn_key == 'STEPGEN_MAX_VEL':
                hal_label = dyn_dict[dyn_key]
            elif dyn_key == 'STEPGEN_MAXACCEL':
                hal_label = dyn_dict[dyn_key]
            #elif dyn_key == 'MAX_JOG_VELOCITY_UPS': # see tormach_mill_ui.py, line 1320?? and self.jog_speeds in mill_ui.py
            #    hal_lable = None
            #elif dyn_key == 'MIN_JOG_VELOCITY_UPS': # see tormach_mill_ui.py, line 1320?? and self.jog_speeds in mill_ui.py
            #    hal_label = None
            else: # unhandled ini define
                 self.error_handler.log("unknown handler for dyn_dict key %s" % dyn_key)

            if hal_label != None:
                if new_axis == 'A_AXIS_440_RT':
                    self.hal['probe-enable'] = 0  # this device is mutually exclusive to the 440 RT
                else:
                    self.hal['probe-enable'] = 1  # all other A axes can and should have probing enabled

                try:
                    ini_value = float(self.inifile.find(new_axis, dyn_key))
                except:
                    self.error_handler.log("Error: Required %s A axis data for %s not found in ini file" % (hal_label, new_axis))
                    ini_value = None

                #cmd = "halcmd setp hm2_%s.0.stepgen.03.%s %.4f" % (board, hal_label, ini_value)

                if ini_value != None:
                    cmd = ["halcmd", "setp", "hm2_%s.0.stepgen.03.%s" % (board, hal_label), "%.5f" % ini_value]
                    self.error_handler.log(' '.join(cmd))
                    if board != None:  #skip halcmd call in sim mode
                        if subprocess.call(cmd):
                            self.error_handler.log("Error: This command failed \"%s\"" % ' '.join(cmd))
                            self.error_handler.write("Error configuring A axis properly.", ALARM_LEVEL_HIGH)


    def stop_motion_safely(self):
        #Send abort message to motion to stop any movement
        self.command.abort()
        self.command.wait_complete()

        self.status.poll()  # help the rest of the code after this realize that the state of the world is quite changed.

        if self.atc.in_a_thread.is_set():
            self.atc.stop_reset.set()   #only if atc thread in progress
        self.hardkill_coolant = True  #can the spray
        self.coolant_ticker = 0
        if self.feedhold_active.is_set():
            self.feedhold_active.clear()
            self.set_image('feedhold_image', 'Feedhold-Black.jpg')


    def on_coolant_button_release_event(self, widget, data=None):
        # POSTGUI_HALFILE contains:
        # net coolant-flood tormach.coolant => parport.0.pin-14-out
        # net coolant-flood-io iocontrol.0.coolant-flood => tormach.coolant-iocontrol
        # The UI code here watches tormach.coolant-iocontrol for changes from LinuxCNC.
        # See the periodic handler for details
        if not self.is_button_permitted(widget): return
        # use our tormach.coolant HAL pin to track actual coolant state
        # only toggle flood on and off if mist isn't on
        # but turn off mist if on, mist must turn on only with M7

        if  not self.hal['mist']:
            self.hal['coolant'] = not self.hal['coolant']
        if self.hal['mist']:
            self.hal['mist']= self.hal['coolant'] = False


    def on_reset_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        btn.ImageButton.unshift_button(widget)
        self.window.set_focus(None)

        self.hal['pp-estop-fault'] = 0   #clear any existing pp software estops
        self.halt_world_flag = False # TODO: note issues with halt world.  Do we lock it out during reset
                                    # and then check or reset this at end of on_reset_button_release
        self.clear_message_line_text()
        self.hide_m1_image()
        self.unlock_enclosure_door()

        if self.hal['mesa-watchdog-has-bit']:
            # since resetting the mesa card io_error parameter is more involved now with ethernet,
            # only do this if we really did see a watchdog bite.

            # clear Mesa IO errors (if any).  this must be done PRIOR to setting the mesa-watchdog-has-bit pin low.
            clear_hostmot2_board_io_error(self.inifile)

            # clear Mesa card watchdog
            self.hal['mesa-watchdog-has-bit'] = 0
            self.mesa_watchdog_has_bit_seen = False

            # give it a second to re-establish IO link before jamming commands at it.
            time.sleep(1.0)
            self.status.poll()

            # did the watchdog re-bite already?  If so, re-establishing the IO link didn't work.
            # leave us in e-stop.
            if self.hal['mesa-watchdog-has-bit']:
                self.mesa_watchdog_has_bit_seen = True
                self.error_handler.write("Machine interface error. Check cabling and power to machine and then press RESET.", ALARM_LEVEL_MEDIUM)
                self.call_ui_hook('reset_button')
                return

        # order of these is important.  Answer queries first, then check for random stop/reset presses
        if self.set_response_cancel(): return        #check for outstanding prompts and cancel,True is message answered

        if self.atc.in_a_thread.is_set():
            self.atc.stop_reset.set()   #only if atc thread in progress
            self.atc.feed_hold_clear.set()  # signal that any feed holds are cleared
            self.set_image('feedhold_image', 'Feedhold-Black.jpg')

        # clear feedhold
        if self.feedhold_active.is_set():
            self.feedhold_active.clear()
            self.set_image('feedhold_image', 'Feedhold-Black.jpg')

        # reset e-stop
        if self.status.task_state != linuxcnc.STATE_ESTOP_RESET:
            # this actually ends up doing a linuxcnc command abort internally
            # and that will run any on_abort ngc code.
            self.command.state(linuxcnc.STATE_ESTOP_RESET)
            self.command.wait_complete()
            self.status.poll()
            if self.status.task_state not in [linuxcnc.STATE_ESTOP_RESET, linuxcnc.STATE_ON]:
                self.error_handler.write("Failed to bring machine out of E-stop. Please check machine power, limit switches, and communication cable from the controller to the machine.")
                self.call_ui_hook('reset_button')
                return

        # clear alarm
        self.estop_alarm = False
        self.display_estop_msg = True

        # Prevent coming out of Reset if a limit switch is active.
        if (self.status.limit[0] != 0):
            error_msg = 'X limit switch active.'
            self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
        if (self.status.limit[1] != 0):
            error_msg = 'Y limit switch active.'
            self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
        if (self.status.limit[2] != 0):
            error_msg = 'Z limit switch active.'
            self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
        if (self.status.limit[0] != 0) or (self.status.limit[1] != 0) or (self.status.limit[2] != 0):
            error_msg = 'Disable limit switches in Settings, then push Reset, then carefully jog off limit switch, then re-enable limit switches in Settings.'
            self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
            self.call_ui_hook('reset_button')
            return

        # must be turned on again after being reset from estop
        if self.status.task_state != linuxcnc.STATE_ON:
            # this actually ends up doing a linuxcnc command abort internally
            # and that will run any on_abort ngc code.
            self.command.state(linuxcnc.STATE_ON)
            self.command.wait_complete()
            self.status.poll()
            if self.status.task_state != linuxcnc.STATE_ON :
                self.error_handler.write("Failed to bring machine out of E-stop. Please check machine power, limit switches, and communication cable from the controller to the machine.")
                return

            if self.atc.operational:  # is atc enabled
                st = timer.Stopwatch()
                for i in range(10):
                    time.sleep(.5)  # give hal time to find the board and set tool #
                    if self.hal['atc-device-status']:
                        self.atc.map_graphics() # set up atc GUI
                        break
                self.error_handler.log("reset handler waited for atc-device-status - {}".format(str(st)))

        # saw a rare case where the ATC stuff above times out after taking 5 long seconds and during that
        # time, the operator presses the e-stop button.  So just check again to be sure before we start
        # running commands.  If it is e-stopped, the periodics will take appropriate action.
        if self.hal['machine-ok'] == False:
            return

        # stop motion
        self.command.abort()
        self.command.wait_complete()

        # suppress coolant action for full second
        self.hardkill_coolant = True
        self.coolant_ticker = 0

        # reset/rewind program
        if (self.status.limit[0] == 0) and (self.status.limit[1] == 0) and (self.status.limit[2] == 0):
            self.issue_mdi('M30')

        # clear SB status
        self.single_block_active = False
        self.set_image('single_block_image', 'Single-Block-Black.jpg')

        # clear live plotter
        self.gremlin.clear_live_plotter()

        # refresh work offsets
        self.refresh_work_offset_liststore()

        # rewind program listing and set starting line
        if self.is_gcode_program_loaded:
            self.gcodelisting_mark_start_line(1)

            # some folks got confused because their program ended, the M30 reset current line to 0 and
            # the 50ms periodic auto-scrolled back up to the start line.  But then they managed to scroll
            # around in the view and then press the Reset button and they expect it to auto-scroll to the
            # top again.  The 50ms periodic doesn't do anything because the current line hasn't 'changed'
            # from 0 so we need this here to always smack the display back to the start line.
            self.sourceview.scroll_to_mark(self.gcodelisting_start_mark, 0, True, 0, 0.5)


        self.call_ui_hook('reset_button')

        self.do_first_run_setup()

        self.axis_motor_command(0, MOTOR_CMD_NORMAL)
        self.axis_motor_command(1, MOTOR_CMD_NORMAL)
        self.axis_motor_command(2, MOTOR_CMD_NORMAL)

        # Make sure the override sliders are enabled.  The ATC code disables them and tries to restore them, but
        # in certain aborted situations, they can get stuck off.
        self.command.set_feed_override(True)
        self.command.set_spindle_override(True)

        # g21 and machineconfig need to be accurate before setting scaled jog increment
        jog_ix = self.hal['jog-gui-step-index']
        if self.g21:
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g21()[jog_ix]
        else:
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g20()[jog_ix]


    def do_first_run_setup(self):
        if not self.first_run:
            return

        self.first_run = False
        #purge any left over message and answersfrom prior aborts in redis queue
        try:
            self.redis.delete('TormachMessage')
            self.redis.delete('TormachAnswers')
            self.error_handler.log("Purged TormachMessage and TormachAnswers msg queues")
        except:
            traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))
            self.error_handler.log("Exception purging TormachMessage and TormachAnswers msg queues.  Exception: %s" % traceback_txt)

        self.ensure_mode(linuxcnc.MODE_MANUAL)

        #For some bizarre reason, changing to mode manual turns on mist pins
        #Just overlay the input pin it networked to with a False to cancel the wierdness
        self.hal["mist-iocontrol"] = False

        # custom X/Y/Z soft limits
        self.ensure_mode(linuxcnc.MODE_MANUAL)
        if self.redis.hexists('machine_prefs', 'x_soft_limit'):
            self.x_soft_limit = float(self.redis.hget('machine_prefs', 'x_soft_limit'))
            self.error_handler.write("setting X soft limit to: %f" % self.x_soft_limit, ALARM_LEVEL_DEBUG)
            self.set_axis_minmax_limit(0, self.x_soft_limit)
        else:
            self.error_handler.write("No X soft limit stored in redis, not setting.", ALARM_LEVEL_DEBUG)

        if self.redis.hexists('machine_prefs', 'y_soft_limit'):
            self.y_soft_limit = float(self.redis.hget('machine_prefs', 'y_soft_limit'))
            self.error_handler.write("setting Y soft limit to: %f" % self.y_soft_limit, ALARM_LEVEL_DEBUG)
            self.set_axis_minmax_limit(1, self.y_soft_limit)
        else:
            self.error_handler.write("No Y soft limit stored in redis, not setting.", ALARM_LEVEL_DEBUG)

        if self.redis.hexists('machine_prefs', 'z_soft_limit'):
            self.z_soft_limit = float(self.redis.hget('machine_prefs', 'z_soft_limit'))
            self.error_handler.write("setting Z soft limit to: %f" % self.z_soft_limit, ALARM_LEVEL_DEBUG)
            self.set_axis_minmax_limit(2, self.z_soft_limit)
        else:
            self.error_handler.write("No Z soft limit stored in redis, not setting.", ALARM_LEVEL_DEBUG)

        self.ensure_mode(linuxcnc.MODE_MDI)
        try:
            if self.redis.hget('machine_prefs', 'g21') == "True":
                self.issue_mdi("G21")
                # need wait_complete or else subsequent tool change will fail
                self.command.wait_complete()

            # RESET TOOL IN SPINDLE WITH M61 TO BYPASS TOOL CHANGING
            tool_num = self.redis.hget('machine_prefs', 'active_tool')
            if tool_num == None or int(tool_num) < 0:
                tool_num = '0'
            self.issue_mdi("M61 Q" + tool_num)
            self.command.wait_complete()
            self.issue_mdi('G43')

            feedrate = self.redis.hget('machine_prefs', 'feedrate')
            self.error_handler.write("feedrate: %s" % feedrate, ALARM_LEVEL_DEBUG)
            if feedrate != '0' and feedrate != None:
                g94_command = "G94 F%.4f" % float(feedrate)
                self.issue_mdi(g94_command)

            spind_speed = self.redis.hget('machine_prefs', 'spindle_speed')
            if spind_speed != '0' and spind_speed != None:
                s_command = "S%.4f" % float(spind_speed)
                self.issue_mdi(s_command)



        except Exception as e:
            self.error_handler.write("Redis failed to retrieve tool information!  %s" % str(e), ALARM_LEVEL_DEBUG)
            pass

        # Now that we are out of Reset for the first time, see what USBIO stuff we have.
        if self.settings.usbio_enabled:
            self.show_usbio_interface()
        else:
            self.hide_usbio_interface()


    def on_feedrate_override_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_feedrate_override(100)

    def on_rpm_override_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_spindle_override(100)

    def on_maxvel_override_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_maxvel_override(100)

    # TODO: move below conversational and probing handler sections?
    # -------------------------------------------------------------------------------------------------
    # Scanner Handlers
    # -------------------------------------------------------------------------------------------------

    def on_camera_notebook_switch_page(self, notebook, page, page_num):
        #KLUDGE using numbers here
        if page_num == 0: #Calibration
            pass
        elif page_num == 1: #Scan
            #Ugly way to force all DRO's to update, spams output though
            #FIXME, long recalculation with lots of points
            self.on_scanner_scan_x_start_dro_activate(self.scanner_scan_dro_list['scanner_scan_x_start_dro'])
            self.on_scanner_scan_x_end_dro_activate(self.scanner_scan_dro_list['scanner_scan_x_end_dro'])
            self.on_scanner_scan_y_start_dro_activate(self.scanner_scan_dro_list['scanner_scan_y_start_dro'])
            self.on_scanner_scan_y_end_dro_activate(self.scanner_scan_dro_list['scanner_scan_y_end_dro'])
            try:
                self.scanner.camera.set_window_from_fov(self.scanner.scene.fov_ratio)
            except AttributeError:
                pass

    def on_scanner_common_working_fov_adjustment_value_changed(self, adjustment):
        fov_ratio = float(adjustment.value)/100.0
        try:
            self.scanner.scene.set_fov_ratio(fov_ratio)
            #FIXME fails on startup since camera doesn't exist at first. Maybe move this to a scene setting instead?
            self.scanner.scene.update_scanpoints(self.scanner.camera.get_frame_size())
            self.scanner_display_scanpoints()
        except AttributeError:
            pass
        #TODO simplify this conversion
        self.scanner_common_working_fov_adj_label.set_text(str(int(adjustment.value))+"%")

    def on_scanner_brightness_adjustment_value_changed(self, adjustment):
        self.scanner_brightness_adj_label.set_text(str(int(adjustment.value))+"%")

        brightness = adjustment.value / 100.0
        #TODO avoid redundant checks like this by controlling sensitivity on toggle
        if self.scanner and self.scanner.camera:
            self.scanner.camera.set_brightness(brightness)
        #os.system('v4l2-ctl --set-ctrl=brightness=%s' % brightness)

    def on_scanner_contrast_adjustment_value_changed(self, adjustment):
        self.scanner_contrast_adj_label.set_text(str(int(adjustment.value))+"%")
        contrast = adjustment.value / 100.0
        #os.system('v4l2-ctl --set-ctrl=contrast=%s' % contrast)
        if self.scanner and self.scanner.camera:
            self.scanner.camera.set_contrast(contrast)

    def on_scanner_scope_circle_dia_adjustment_value_changed(self, adjustment):
        self.scanner_scope_circle_dia_adj_label.set_text(str(int(adjustment.value))+"px")
        if self.scanner:
            self.scanner.scope_circle_dia = adjustment.value

    def on_scanner_camera_on_off_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        if self.scanner.camera is not None:
            self.set_image('scanner_camera_on_off_image', 'button_camera_off.png')
            self.scanner.remove_camera()
        else:
            if self.scanner.create_camera():
                self.set_image('scanner_camera_on_off_image', 'button_camera_on.png')
            else:
                self.set_image('scanner_camera_on_off_image', 'button_camera_off.png')

    def on_scanner_camera_snap_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.scanner.save_snapshot()
        self.error_handler.write("saved snapshot", ALARM_LEVEL_DEBUG)

    def on_scanner_scan_start_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        path = self.last_used_save_as_path + os.path.sep + ''
        if self.scanner and self.scanner.running():
            self.error_handler.write("Can't start a scan while already running as scan",ALARM_LEVEL_LOW)
            return
        with tormach_file_util.file_save_as_popup(self.window, 'Choose scan file name.', path, '.jpg', self.settings.touchscreen_enabled,
                                                  usbbutton=False, closewithoutsavebutton=False) as dialog:
            # Get information from dialog popup
            response = dialog.response
            path = dialog.path
            self.scanner.set_filename(path)
            self.last_used_save_as_path = dialog.current_directory

        if response != gtk.RESPONSE_OK:
            return
        #TODO validation of parameters in scanner
        #TODO better validation that GUI state has propagated to scanner
        self.scanner.use_inch = not self.g21
        self.scanner.start(self.feedhold_active)
        self.save_conv_parameters(self.scanner_scan_dro_list)

    def on_scanner_status_update_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        scanner_text_proc = subprocess.Popen(['v4l2-ctl --all'], stdout=subprocess.PIPE, shell=True)
        (stp_out, stp_err) = scanner_text_proc.communicate()
        scanner_menu_proc = subprocess.Popen(['v4l2-ctl --list-ctrls-menus'], stdout=subprocess.PIPE, shell=True)
        (smp_out, smp_err) = scanner_menu_proc.communicate()

        self.scanner_status_textbuffer.set_text('*** Camera Information\n' + stp_out + '\n*** Control Menu List\n' + smp_out)

    def on_scanner_calibration_complete(self):
        self.get_obj("scanner_calibration_complete_image").set_from_stock(gtk.STOCK_APPLY,gtk.ICON_SIZE_LARGE_TOOLBAR)
        self.get_obj("scanner_scan_start").set_sensitive(True)

    def on_scanner_calibration_set_p1_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # read and store machine position for P1
        xypos = self.get_local_position()[0:2]
        # If we got a scale factor, indicate to the user that calibration is
        # done
        if self.scanner.scene.set_first_point(xypos):
            self.on_scanner_calibration_complete()
        self.scanner_calibration_p1_text.set_markup('<span weight="light" font_desc="Bebas 12" font_stretch="ultracondensed" foreground="white" >P1    :    (   %s  ,  %s    )</span>' % (self.dro_long_format, self.dro_long_format) % tuple(xypos))
        self.scanner_calibration_scale_text.set_markup('<span weight="light" font_desc="Bebas 12" font_stretch="ultracondensed" foreground="white" >Scale   :   %s   ,   Angle  :  %s &#xB0;   </span>' % (self.dro_long_format, self.dro_long_format) % (self.scanner.scene.scale,self.scanner.scene.angle))

    def on_scanner_calibration_set_p2_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        xypos = self.get_local_position()[0:2]
        # If we got a scale factor, indicate to the user that calibration is
        # done
        if self.scanner.scene.set_second_point(xypos):
            self.on_scanner_calibration_complete()
        self.scanner_calibration_p2_text.set_markup('<span weight="light" font_desc="Bebas 12" font_stretch="ultracondensed" foreground="white" >P1    :    (   %s  ,  %s    )</span>' % (self.dro_long_format, self.dro_long_format) % tuple(xypos))
        self.scanner_calibration_scale_text.set_markup('<span weight="light" font_desc="Bebas 12" font_stretch="ultracondensed" foreground="white" >Scale   :   %s   ,   Angle  :  %s  &#xB0;  </span>' % (self.dro_long_format, self.dro_long_format) % (self.scanner.scene.scale,self.scanner.scene.angle))

    def on_scanner_calibration_zoom_p1_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # zoom the area around P1 to finish jogging target
        if self.scanner.zoom_state == 'p1':
            #self.set_image('scanner_zoom_p1_on_off_image', 'button_zoom_p1_off.png')
            self.scanner.zoom_state = 'off'
        else:
            #self.set_image('scanner_zoom_p1_on_off_image', 'button_zoom_p1_on.png')
            self.scanner.zoom_state = 'p1'

    def on_scanner_calibration_zoom_p2_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # zoom the area around P1 to finish jogging target
        if self.scanner.zoom_state == 'p2':
            #self.set_image('scanner_zoom_p2_on_off_image', 'button_zoom_p2_off.png')
            self.scanner.zoom_state = 'off'
        else:
            #self.set_image('scanner_zoom_p2_on_off_image', 'button_zoom_p2_on.png')
            self.scanner.zoom_state = 'p2'

    def scanner_display_scanpoints(self):
        """ Using the scanner's internal state, display useful information in the Scan window"""
        # Get local arguments
        points_label = self.get_obj('scanner_scan_points_label')
        rows_label = self.get_obj('scanner_scan_rows_label')
        time_label = self.get_obj('scanner_scan_time_label')

        points_label.set_markup(self.format_dro_string('Points: {0}'.format(self.scanner.scene.points_count),11))
        rows_label.set_markup(self.format_dro_string('Rows: {0} , Columns: {1}'.format(self.scanner.scene.rows,self.scanner.scene.columns),11))
        time_data=datetime.timedelta(seconds=round(self.scanner.scene.estimated_time))
        time_label.set_markup(self.format_dro_string('Estimated Time: {0}'.format(time_data),11))

    def on_scanner_update_bounds(self, index, value):
        if self.scanner is not None and self.scanner.camera is not None:
            self.scanner.scene.bounds[index] = value
            self.scanner.scene.update_scanpoints(self.scanner.camera.get_frame_size())
            self.scanner_display_scanpoints()
        return

    #TODO come up with a cleaner way to do parameter validation here, maybe a standard set of validation params for each DRO?
    # i.e. each parameter has an associated min / max value, data type, etc.
    def on_scanner_scan_x_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        # Have a valid numerical value
        (in_limits, error_msg) = self.validate_local_position(value,0)
        if not valid or not in_limits:
            cparse.raise_alarm(widget, error_msg)
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        cparse.clr_alarm(widget)
        widget.set_text(self.dro_long_format % value)
        self.on_scanner_update_bounds(0, value)
        self.scanner_scan_dro_list['scanner_scan_x_end_dro'].grab_focus()

    def on_scanner_scan_x_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        (in_limits, error_msg) = self.validate_local_position(value,0)
        if not valid or not in_limits:
            cparse.raise_alarm(widget, error_msg)
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        cparse.clr_alarm(widget)
        widget.set_text(self.dro_long_format % value)
        self.on_scanner_update_bounds(1, value)
        self.scanner_scan_dro_list['scanner_scan_y_start_dro'].grab_focus()
        return

    def on_scanner_scan_y_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        (in_limits, error_msg) = self.validate_local_position(value,1)
        if not valid or not in_limits:
            cparse.raise_alarm(widget, error_msg)
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.on_scanner_update_bounds(2, value)
        self.scanner_scan_dro_list['scanner_scan_y_end_dro'].grab_focus()

    def on_scanner_scan_y_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        (in_limits, error_msg) = self.validate_local_position(value,1)
        if not valid or not in_limits:
            cparse.raise_alarm(widget, error_msg)
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.on_scanner_update_bounds(3, value)
        self.window.set_focus(None)

    def on_scanner_scan_tolerance_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.scanner_scan_dro_list['scanner_scan_feature_size_dro'].grab_focus()

    def on_scanner_scan_feature_size_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_short_format % value)
        self.scanner_scan_dro_list['scanner_scan_x_start_dro'].grab_focus()

    def on_scanner_scope_capture_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # capture current X and Y and store in table
        #scope_pos = self.status.actual_position
        abs_pos = self.status.position
        scope_pos = self.to_local_position(abs_pos)

        scope_x = ('%0.4f' % scope_pos[0])
        scope_y = ('%0.4f' % scope_pos[1])
        self.scope_liststore[self.scope_row][1] = scope_x
        self.scope_liststore[self.scope_row][2] = scope_y
        self.scope_row += 1

    def on_scope_x_column_edited(self, cell, row, value, model):
        # TODO - connect to mill_conversational.validate_param
        #valid, value, error_msg = mill_conversational.validate_param(value)
        #if not valid:
        #    self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
        #    return

        self.error_handler.write("Editing X column : on_scope", ALARM_LEVEL_DEBUG)
        if value == '' or value == '??':
            model[row][1] = ""
            return
        try:
            value = float(value)
        except ValueError:
            self.error_handler.write("Invalid position specified for drill table", ALARM_LEVEL_LOW)

        row = 0 if row == '' else int(row)
        model[row][1] = "%0.4f" % value

    def on_scope_y_column_edited(self, cell, row, value, model):
        # TODO - connect to mill_conversational.validate_param
        #valid, value, error_msg = mill_conversational.validate_param(value)
        #if not valid:
        #    self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
        #    return

        self.error_handler.write("Editing Y column : on_scope", ALARM_LEVEL_DEBUG)
        if value == '' or value == '??':
            model[row][2] = ""
            return
        try:
            value = float(value)
        except ValueError:
            self.error_handler.write("Invalid position specified for drill table", ALARM_LEVEL_LOW)

        row = 0 if row == '' else int(row)
        model[row][2] = "%0.4f" % value

    # ~~~~~~ Scanner Common DROs, Buttons and Bows
    def on_scanner_common_working_fov_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_short_format % value)
        #self.scanner_scan_dro_list['scanner_scan_x_start_dro'].grab_focus()
        return


    # Position/Status Readout Group

    # common dro callbacks

    def on_dro_gets_focus(self, widget, event):
        # this clues in the tool tip mgr to stop the state machine from displaying the tool tip for this dro.
        # the user is already in the midst of editing the DRO value so they don't need help anymore, its just
        # annoying otherwise.
        tooltipmgr.TTMgr().on_button_press(widget, event)

        if self.moving() or not widget.has_focus():
            return
        widget.prev_val = widget.get_text()
        widget.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color(HIGHLIGHT))
        widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('black'))
        if not widget.masked:
            # only highlight the whole field if the user hasn't selected a portion of it
            widget.select_region(0, -1)

        widget.masked = True

        if self.settings.touchscreen_enabled:
            np = numpad.numpad_popup(self.window, widget)
            np.run()
            widget.masked = False
            widget.select_region(0, 0)
            self.window.set_focus(None)

    def on_dro_loses_focus(self, widget, data=None):
        if widget_in_alarm_state(widget): return
        if FSBase.dro_in_calc_state(widget): return
        widget.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color('white'))
        widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('black'))
        if not self.settings.touchscreen_enabled:
            widget.masked = False
            widget.select_region(0, 0)

    def on_dro_key_press_event(self, widget, event, data=None):
        kv = event.keyval
        if kv == gtk.keysyms.Escape:
            widget.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color('white'))
            widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('black'))
            widget.masked = False
            self.window.set_focus(None)
            return True

    def on_qwerty_dro_gets_focus(self, widget, data=None):
        # this clues in the tool tip mgr to stop the state machine from displaying the tool tip for this dro.
        # the user is already in the midst of editing the DRO value so they don't need help anymore, its just
        # annoying otherwise.
        tooltipmgr.TTMgr().on_button_press(widget, data)

        if self.settings.touchscreen_enabled:
            np = numpad.numpad_popup(self.window, widget, True)
            np.run()
            self.window.set_focus(None)
            return True

    def on_conv_dro_gets_focus(self, widget, data=None):
        # really the button release event
        widget.prev_val = widget.get_text()
        widget.select_region(0, -1)
        if self.settings.touchscreen_enabled:
            keypad = numpad.numpad_popup(self.window, widget)
            keypad.run()
            widget.select_region(0, 0)
            self.window.set_focus(None)

    def on_dro_focus_in_event(self, widget, data=None):
        widget.prev_val = widget.get_text()

    # ref button callbacks

    def on_ref_x_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # check if door sw is enabled and warn user about wiring change
        if self.settings.door_sw_enabled:
            # have we already warned the user about door sw wiring?
            if self.redis.hget('machine_prefs', 'display_door_sw_x_ref_warning') == 'True':
                dialog = popupdlg.ok_cancel_popup(self.window, 'Enclosure door switch is enabled on settings tab.  Has switch been installed and wiring changes been made?')
                dialog.run()
                response = dialog.response
                dialog.destroy()
                if response != gtk.RESPONSE_OK:
                    return
                self.redis.hset('machine_prefs', 'display_door_sw_x_ref_warning', 'False')

        self.ref_axis(0)


    def on_ref_y_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.ref_axis(1)

    def on_ref_z_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.ref_axis(2)

    def on_ref_a_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.ref_axis(3)


    def on_usbio_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        current_usbio_button = gtk.Buildable.get_name(widget)
        #fetch digit character within usbio_output_#_led
        index = str(int(current_usbio_button[USBIO_STR_DIGIT_INDEX]) + (self.usbio_boardid_selected * 4))

        if self.hal["usbio-output-" + index]: #if relay on
            command = 'M65 P' + index  #turn off
        else:
            command = 'M64 P' + index  #turn on

        # log this to the status tab since they are actually clicking the button.
        # it will help remind them what commands the buttons are doing for integration diagnostics
        self.error_handler.write("USBIO button executing: {}".format(command), ALARM_LEVEL_QUIET)

        self.issue_mdi(command)

    def ref_axis(self, axis):
        axis_dict = {0:'X', 1:'Y', 2:'Z', 3:'A'}

        # ignore the request if the axis is already in the middle of homing, be patient...
        if self.hal['axis-{:d}-homing'.format(axis)]:
            self.error_handler.log("Ignoring ref request for axis {:s} as it is already homing.".format(axis_dict[axis]))
            return

        # make sure we're not on a limit right now!
        if (self.status.limit[axis] == 3) and self.settings.home_switches_enabled:
            self.error_handler.write("Cannot reference this axis when on a limit switch.  Move the machine off limit switch before proceeding.")
            return

        # kludge for issue #1115:
        if axis == 0 and self.settings.door_sw_enabled and self.settings.home_switches_enabled:
            if self.status.limit[1] == 3:
                self.error_handler.write("Cannot reference this axis when on a limit switch.  Move the machine off limit switch before proceeding.")
                return

        # warn if about to re-reference
        if self.status.homed[axis]:
            dialog = popupdlg.ok_cancel_popup(self.window, axis_dict[axis] + ' axis already referenced.  Re-reference?')
            dialog.run()
            response = dialog.response
            dialog.destroy()
            if response != gtk.RESPONSE_OK:
                return

        # on servo machines, this puts the motor into homing mode, but doesn't really initiate
        # any homing motion yet.  on steppers its a no-op.
        self.axis_motor_command(axis, MOTOR_CMD_HOME)

        if self.settings.door_sw_enabled and self.machineconfig.shared_xy_limit_input():
            # queue these buttons using atc queue
            self.atc.queue_ref_axis(axis)
        elif axis == 2:
            # always ref z through ATC code to prevent ref with tray in
            self.atc.ref_z()
        else:
            self.ensure_mode(linuxcnc.MODE_MANUAL)
            self.command.home(axis)

    # Zero DRO callbacks

    def on_zero_x_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_work_offset("X", 0)

    def on_zero_y_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_work_offset("Y", 0)

    def on_zero_z_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_work_offset("Z", 0)

    def on_zero_a_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_work_offset("A", 0)

    # dro events

    def on_x_dro_activate(self, widget):
        valid, dro_val, error_msg = self.conversational.validate_x_point(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.set_work_offset("X", dro_val)
        # allow updates
        widget.masked = False
        self.window.set_focus(None)


    def on_y_dro_activate(self, widget):
        valid, dro_val, error_msg = self.conversational.validate_y_point(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.set_work_offset("Y", dro_val)
        # allow updates
        widget.masked = False
        self.window.set_focus(None)


    def on_z_dro_activate(self, widget):
        valid, dro_val, error_msg = self.conversational.validate_z_point(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.set_work_offset("Z", dro_val)
        # allow updates
        widget.masked = False
        self.window.set_focus(None)


    def on_a_dro_activate(self, widget):
        valid, dro_val, error_msg = self.conversational.validate_z_point(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.set_work_offset("A", dro_val)
        # allow updates
        widget.masked = False
        self.window.set_focus(None)

    def on_spindle_rpm_dro_activate(self, widget, data=None):
        # unmask DRO
        widget.masked = False
        # user entry validation
        valid, dro_val, error_msg = self.conversational.validate_max_spindle_rpm(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        rpm = abs(dro_val)
        s_command = "S%.0f" % (rpm)
        self.issue_mdi(s_command)
        self.window.set_focus(None)


    def on_feed_per_min_dro_activate(self, widget, data=None):
        # get DRO value
        valid, dro_val, error_msg = self.conversational.validate_feedrate(widget, self.g21)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        feed_per_min = abs(dro_val)
        if feed_per_min > self.max_feedrate * self.get_linear_scale():
            feed_per_min = self.max_feedrate * self.get_linear_scale()
            self.error_handler.write("Clipping feedrate to maximum allowed value for the machine.", ALARM_LEVEL_LOW)
        # TODO - do we need the explicit G94 here?
        g94_command = "G94 F%.4f" % (feed_per_min)
        self.issue_mdi(g94_command)
        # unmask DROs
        widget.masked = False
        self.window.set_focus(None)


    # Manual Control Group
    def on_key_press_or_release(self, widget, event, data=None):
        kv = event.keyval

        #print 'event.statekeyval: %d 0x%04x' % (kv, kv)
        #print 'event.statestate:  %d 0x%04x' % (event.state, event.state)

        # Utilities
        if event.type == gtk.gdk.KEY_PRESS:
            if kv == gtk.keysyms.F1:
            # If we're not on the status page, save the current page and switch
            # to the status page
            # The logic is a little convoluted because auto-repeat of keys ends up
            # sending us a lot of KEY_PRESS events, but only one KEY_RELEASE.
            # F1_page_toggled gives us enough info so that if you're on the MILL_STATUS_PAGE
            # and hold down F1, then upon its release, we don't switch back to whatever
            # happens to be laying around in prev_page.  Effectively F1 hold is
            # ignored when you're on the MILL_STATUS_PAGE page entirey.
                if self.current_notebook_page_id != 'alarms_fixed':
                    self.F1_page_toggled = True
                    self.prev_notebook_page_id = self.current_notebook_page_id
                    set_current_notebook_page_by_id(self.notebook, 'alarms_fixed')
            elif kv == gtk.keysyms.Print:
                self.screen_grab()
            else:
                tooltipmgr.TTMgr().temporary_activate(kv)

        if event.type == gtk.gdk.KEY_RELEASE:
            if kv == gtk.keysyms.F1:
                if self.F1_page_toggled:
                    self.F1_page_toggled = False
                    set_current_notebook_page_by_id(self.notebook, self.prev_notebook_page_id)

                    # gtk2 bug where is we are restoring to notebook_main_fixed and the MDI entry box formerly had
                    # focus when F1 was pushed, it regains focus, but does NOT signal the on_mdi_line_gets_focus.
                    if self.prev_notebook_page_id == 'notebook_main_fixed' and self.mdi_line.has_focus():
                        self.on_mdi_line_gets_focus(self.mdi_line, None)
            else:
                tooltipmgr.TTMgr().temporary_deactivate(kv)
        #FIXME should this return here? Not sure if anything else needs "Print" key

        # open new terminal window
        # MOD1_MASK indicates the left Alt key pressed
        # CONTROL_MASK indicates either Ctrl key is pressed
        if event.state & gtk.gdk.MOD1_MASK and event.state & gtk.gdk.CONTROL_MASK:
            if kv in [gtk.keysyms.x, gtk.keysyms.X] and event.type == gtk.gdk.KEY_PRESS:
                # start a terminal window in $HOME directory
                subprocess.Popen(args=["gnome-terminal", "--working-directory=" + os.getenv('HOME')]).pid
                return True

        # Keyboard functions
        # Return True on TAB to prevent tabbing focus changes
        if kv == gtk.keysyms.Tab:
            return True


        if self.window.get_focus() in (self.tool_search_entry, self.workoffset_search_entry) and kv in set([gtk.keysyms.Left,
                                                          gtk.keysyms.Right,
                                                          gtk.keysyms.Up,
                                                          gtk.keysyms.Down,
                                                          gtk.keysyms.period,
                                                          gtk.keysyms.comma,
                                                          gtk.keysyms.Escape]):
            return False

        # Disable jogging and pass through depending on focus
        # Only pass through if the user is not currently jogging though (or unintended motion could result)
        if kv in self.jogging_keys and True not in self.jogging_key_pressed.values():

            #First, handle specific cases that don't behave by type rules

            # no jogging while mdi line has focus
            if self.mdi_line_masked:
                # Make sure to pass through key presses to navigate MDI
                return False if kv in self.mdi_mask_keys else True

            # Next, check the type of the current focused item and pass through
            # keys if needed.
            focused_item = type(self.window.get_focus())
            if focused_item in self.key_mask:
                return False if kv in self.key_mask[focused_item] else True

            # Have to disregard jogging when the scanner is running since it
            # executes moves via MDI mode (jogging will mess this up if it is
            # not disabled)
            if self.scanner and self.scanner.moving():
                return True

        # grab the keystroke if tool_descript_entry is active
        if self.tool_descript_entry.active() and kv in self.tool_descript_keys: return False
        # Preconditions checked -  Jogging handled below
        # check to see if we're releasing the key

        # Force jogging to stop whenever shift keys are pressed or released
        # (Mach3 Style)
        if kv in [gtk.keysyms.Shift_L, gtk.keysyms.Shift_R] and not self.program_running() and not self.mdi_running() and self.moving():
            self.stop_all_jogging()
            return True

        if event.type == gtk.gdk.KEY_RELEASE and kv in self.jogging_keys:
            self.jogging_key_pressed[kv] = False
            # right or left - x axis
            if kv ==  gtk.keysyms.Left or kv == gtk.keysyms.Right:
                jog_axis = 0
            # up or down - y axis
            elif kv == gtk.keysyms.Up or kv == gtk.keysyms.Down:
                jog_axis = 1
            # page up or page down - z axis
            elif kv == gtk.keysyms.Prior or kv == gtk.keysyms.Next:
                jog_axis = 2
            elif kv == gtk.keysyms.comma or kv == gtk.keysyms.period:
                jog_axis = 3
            else:
                return False

            if (self.jog_mode == linuxcnc.JOG_CONTINUOUS) and not self.program_running():
                self.stop_jog(jog_axis)
            return True

        elif event.type == gtk.gdk.KEY_PRESS and kv in self.jogging_keys:
            if kv == gtk.keysyms.Right:
                # right arrow - X positive
                jog_axis = 0
                jog_direction = 1
            elif kv == gtk.keysyms.Left:
                jog_axis = 0
                jog_direction = -1
            elif kv == gtk.keysyms.Up:
                jog_axis = 1
                jog_direction = 1
            elif kv == gtk.keysyms.Down:
                jog_axis = 1
                jog_direction = -1
            elif kv == gtk.keysyms.Prior:
                jog_axis = 2
                jog_direction = 1
            elif kv == gtk.keysyms.Next:
                jog_axis = 2
                jog_direction = -1
            elif kv == gtk.keysyms.period:
                jog_axis = 3
                jog_direction = 1
            elif kv == gtk.keysyms.comma:
                jog_axis = 3
                jog_direction = -1
            # After determining the axis and direction, run the jog iff the key
            # is not already depressed

            jogging_rapid = event.state & gtk.gdk.SHIFT_MASK

            if not self.jogging_key_pressed[kv]:
                self.set_jog_mode(self.keyboard_jog_mode)
                self.jog(jog_axis, jog_direction, self.jog_speeds[jog_axis], not jogging_rapid)
            # Update the state of the pressed key
            self.jogging_key_pressed[kv] = True
            return True

        if event.type == gtk.gdk.KEY_PRESS:
            # Handle feed hold
            if kv == gtk.keysyms.space and self.moving():
                self.error_handler.log("Spacebar key - queueing feedhold event")
                self.enqueue_button_press_release(self.button_list['feedhold'])
                return True

            # Escape key for stop
            if kv == gtk.keysyms.Escape:
                self.error_handler.log("ESC key - queueing stop button event")
                self.enqueue_button_press_release(self.button_list['stop'])
                self.tool_descript_entry.shutdown_view()
                tooltipmgr.TTMgr().on_esc_key()
                return True


        # alt key shortcuts
        # MOD1_MASK indicates the left alt key pressed
        # MOD5_MASK indicates the right alt key pressed
        if event.state & (gtk.gdk.MOD1_MASK | gtk.gdk.MOD5_MASK) and event.type == gtk.gdk.KEY_RELEASE:

            # alt-e, edit current gcode program
            if kv in [gtk.keysyms.e, gtk.keysyms.E]:
                # cannot enqueue edit_gcode button press - it only works after File tab has been opened
                path = self.current_gcode_file_path
                if not self.moving():
                    if path != '':
                        # Shift-Alt-E means edit conversationally (if possible)
                        convedit = False
                        if event.state & gtk.gdk.SHIFT_MASK:
                            gc = conversational.ConvDecompiler(self.conversational, path, self.error_handler)
                            if any(gc.segments):
                                job_assignment.JAObj().set_gc()
                                job_assignment.JAObj().set_gc(gc)
                                job_assignment.JAObj().job_assignment_conv_edit()
                                convedit = True
                        if not convedit:
                            self.edit_gcode_file(path)
                    else:
                        # open gedit with empty file
                        self.edit_new_gcode_file()

            #smart cool releases -  when alt key comes up cancel actions
            if self.smart_overriding:
                self.hal['smart-cool-up'] = self.hal['smart-cool-down'] = self.smart_overriding = False

            if kv in [gtk.keysyms.c, gtk.keysyms.C]:  # cancel manual smart cool control mode
                self.hal['smart-cool-man-auto'] = False
                self.error_handler.log("SmartCool restored to automatic mode due to keyboard action")

            if kv in [gtk.keysyms.m, gtk.keysyms.M] :  #mist on/off toggle
                self.hal['mist'] = not self.hal['mist']
                self.error_handler.log("Mist set to {} due to keyboard action".format(str(self.hal['mist'])))

            # alt-enter to set focus to MDI line
            # must only work when the Main tab or Status tab is showing
            if self.current_notebook_page_id in ('notebook_main_fixed', 'alarms_fixed') and kv in (gtk.keysyms.Return, gtk.keysyms.KP_Enter) and not self.program_running():
                if self.current_notebook_page_id != 'notebook_main_fixed':
                    set_current_notebook_page_by_id(self.notebook, 'notebook_main_fixed')
                # make sure that the notebook on the main tab has the mdi page visible
                if get_current_notebook_page_id(self.gcode_options_notebook) != 'gcode_page_fixed':
                    set_current_notebook_page_by_id(self.gcode_options_notebook, 'gcode_page_fixed')
                self.on_mdi_line_gets_focus(self.mdi_line, None)
                self.mdi_line.grab_focus()

            for (k_val, k_widget) in self.alt_keyboard_shortcuts:
                if kv == k_val:
                    self.enqueue_button_press_release(k_widget)

        if not (event.state & gtk.gdk.CONTROL_MASK) and (event.state & (gtk.gdk.MOD1_MASK | gtk.gdk.MOD5_MASK)) and event.type == gtk.gdk.KEY_PRESS:
            #smart cool presses
            if kv in [gtk.keysyms.u, gtk.keysyms.U]:  # nozzle up
                self.hal['smart-cool-up'] = self.smart_overriding = self.hal['smart-cool-man-auto'] = True
                self.error_handler.log("SmartCool UP in manual override due to keyboard action")

            if kv in [gtk.keysyms.d, gtk.keysyms.D] :  # nozzle down
                self.hal['smart-cool-down'] = self.smart_overriding = self.hal['smart-cool-man-auto'] = True
                self.error_handler.log("SmartCool DOWN in manual override due to keyboard action")

        if (event.state & gtk.gdk.CONTROL_MASK) and (event.state & gtk.gdk.MOD1_MASK) and event.type == gtk.gdk.KEY_PRESS:
            if kv in [gtk.keysyms.d, gtk.keysyms.D]:
                # ctrl-alt-d
                self.error_handler.log("Enabling debug notebook page")
                self.add_debug_page()

        # ctrl key shortcuts
        # CONTROL_MASK indicates the left ctrl key pressed
        if event.state & gtk.gdk.CONTROL_MASK and event.type == gtk.gdk.KEY_RELEASE:
            for (k_val, k_widget) in self.ctrl_keyboard_shortcuts:
                if kv == k_val:
                    self.enqueue_button_press_release(k_widget)

        return False


    def on_jogging_scale_gets_focus(self, widget, data=None):
        self.set_keyboard_jog_mode(linuxcnc.JOG_CONTINUOUS)


    def on_jog_speed_adjustment_value_changed(self, adjustment):
        self.jog_speed_label.set_text(str(int(adjustment.value))+"%")
        self.set_keyboard_jog_mode(linuxcnc.JOG_CONTINUOUS)
        self.jog_override_pct = (adjustment.value) / 100.0
        self.redis.hset('machine_prefs', 'jog_override_percentage', self.jog_override_pct)
        tooltipmgr.TTMgr().on_adjustment_value_changed(adjustment)


    def on_jog_inc_cont_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.error_handler.write("jog mode was: %s" % str(self.jog_mode), ALARM_LEVEL_DEBUG)
        if self.jog_mode == linuxcnc.JOG_INCREMENT:
            self.set_keyboard_jog_mode(linuxcnc.JOG_CONTINUOUS)
        else:
            self.set_keyboard_jog_mode(linuxcnc.JOG_INCREMENT)

    def jog_button_release_handler(self, widget, jog_index):
        if not self.is_button_permitted(widget): return False
        if not self.set_keyboard_jog_mode(linuxcnc.JOG_INCREMENT): return False
        self.clear_jog_LEDs()
        if self.g21:
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g21()[jog_index]
            self.set_image(self.jog_image_names[jog_index], self.jog_step_images_g21_green[jog_index])
        else:
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g20()[jog_index]
            self.set_image(self.jog_image_names[jog_index], self.jog_step_images_g20_green[jog_index])
        self.hal['jog-gui-step-index'] = jog_index
        self.error_handler.write('jog increment: %3.4F' % self.jog_increment_scaled, ALARM_LEVEL_DEBUG)
        return True


    def on_jog_zero_button_release_event(self, widget, data=None):
        self.jog_button_release_handler(widget, 0)


    def on_jog_one_button_release_event(self, widget, data=None):
        self.jog_button_release_handler(widget, 1)


    def on_jog_two_button_release_event(self, widget, data=None):
        self.jog_button_release_handler(widget, 2)


    def on_jog_three_button_release_event(self, widget, data=None):
        self.jog_button_release_handler(widget, 3)


    def on_ccw_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if self.current_notebook_page_id != 'notebook_main_fixed':
            self.error_handler.write("Cannot start spindle while not on Main screen", ALARM_LEVEL_LOW)
            return

        # user might have a door switch installed and enabled. and if its triggered,
        # and OPENDOORMAXRPM is 0, it can be pretty confusing why nothing is happening.
        # proactively check for that here and warn them.
        if self.settings.door_sw_enabled and self.enc_open_door_max_rpm == 0 and self.door_open_status:
            # the spindle will not start in this condition.
            # tell them why
            self.error_handler.write("Door switch is enabled and tripped, therefore spindle limited to {:d} RPM. Close door or use MDI command ADMIN OPENDOORMAXRPM to adjust.".format(self.enc_open_door_max_rpm), ALARM_LEVEL_LOW)

        # Per conversation with JohnM, better to do this with command.spindle_fwd
        # quick look at touchy/axis makes me think that there's no way to set
        # spindle speed in MODE_MANUAL.
        # don't issue MDI command if speed is zero
        if self.s_word != 0.0:
            self.issue_mdi("m4")

    def on_spindle_stop_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # do not use command.spindle(0) because it steps on status.settings[2]
        self.issue_mdi("m5")

    def on_cw_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if self.current_notebook_page_id != 'notebook_main_fixed':
            self.error_handler.write("Cannot start spindle while not on Main screen", ALARM_LEVEL_LOW)
            return

        # user might have a door switch installed and enabled. and if its triggered,
        # and OPENDOORMAXRPM is 0, it can be pretty confusing why nothing is happening.
        # proactively check for that here and warn them.
        if self.settings.door_sw_enabled and self.enc_open_door_max_rpm == 0 and self.door_open_status:
            # the spindle will not start in this condition.
            # tell them why
            self.error_handler.write("Door switch is enabled and tripped, therefore spindle limited to {:d} RPM. Close door or use MDI command ADMIN OPENDOORMAXRPM to adjust.".format(self.enc_open_door_max_rpm), ALARM_LEVEL_LOW)

        # don't issue MDI command if speed is zero
        if self.s_word != 0.0:
            self.issue_mdi("m3")

    def on_spindle_range_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        # we know we're already in a permitted state.  but only one that can't be captured there
        # is if the spindle is actually spinning right now.
        if self.hal['spindle-on']:
            self.error_handler.write("Cannot change spindle range while spindle is on", ALARM_LEVEL_MEDIUM)
            return

        if self.hal['spindle-range']:
            # we're in high gear, so make it lo
            self.hal['spindle-range'] = 0
            self.set_image('spindle_range_image', 'Spindle_Range_LO_Highlight.png')
            self.redis.hset('machine_prefs', 'spindle_range', 'lo')
            self.mach_data['motor_curve'] = self.mach_data_lo
        else:
            self.hal['spindle-range'] = 1
            self.set_image('spindle_range_image', 'Spindle_Range_HI_Highlight.png')
            self.redis.hset('machine_prefs', 'spindle_range', 'hi')
            self.mach_data['motor_curve'] = self.mach_data_hi
        FSBase.update_spindle_range()

    def on_tool_dro_gets_focus(self, widget, data=None):
        if self.moving():
            return
        self.set_image('m6_g43_image', 'M6_G43_Highlight.png')
        widget.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color(HIGHLIGHT))
        widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('black'))
        widget.masked = True
        widget.select_region(0, -1)
        if self.settings.touchscreen_enabled:
            keypad = numpad.numpad_popup(self.window, widget)
            keypad.run()
            widget.masked = 0
            widget.select_region(0, 0)
            self.window.set_focus(None)


    def on_tool_dro_loses_focus(self, widget, data=None):
        self.set_image('m6_g43_image', 'M6_G43.png')
        if widget_in_alarm_state(widget): return
        widget.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color('white'))
        widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('black'))
        if not self.settings.touchscreen_enabled:
            widget.masked = False
            widget.select_region(0, 0)


    def on_tool_dro_activate(self, widget, data=None):
        # get DRO value
        valid, tool_num, error_msg = self.conversational.validate_tool_number(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            widget.masked = 0
            return
        self.dro_list['tool_dro'].set_text("%1d" % tool_num)
        widget.masked = 0

        # we drive the same signals that a button click would have for ease of maintenance.
        self.button_list['m6_g43'].emit('button-press-event', None)
        self.button_list['m6_g43'].emit('button-release-event', None)

        self.tt_scroll_adjust(tool_num)


    def on_m6_g43_focus_in_event(self, widget, data=None):
        # keep tool dro from getting overwritten by periodic function until M6 is  called.
        self.dro_list['tool_dro'].masked = 1

    def on_m6_g43_focus_out_event(self, widget, data=None):
        self.dro_list['tool_dro'].masked = 0
        self.set_image('m6_g43_image', 'M6_G43.png')

    def on_m6_g43_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        current_tool = self.status.tool_in_spindle

        # TODO - better validation here
        valid, tool_num, error_msg = self.conversational.validate_tool_number(self.dro_list['tool_dro'])
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return

        if tool_num == current_tool:
            # still might want to apply the offset
            # TODO - check to see if offset is already correctly applied
            self.issue_mdi('G43')
            return

        # if we've got an ATC, and the user enters a number in the new tool dro that is a tray tool
        # ask if they want to fetch the tool from the tray or just M61 to make it active
        old_tool_in_tray = new_tool_in_tray = False  #default until we know better
        if self.atc.operational:
            self.status.poll()
            if self.atc.lookup_slot(self.status.tool_in_spindle) >= 0:
                old_tool_in_tray = True
            if self.atc.lookup_slot(tool_num) >= 0:
                new_tool_in_tray = True

            if old_tool_in_tray and new_tool_in_tray:
                message = 'Use ATC to change tools?'
            elif old_tool_in_tray and not new_tool_in_tray:
                message = 'Use ATC to store tool {:d}?'.format(self.status.tool_in_spindle)
            elif not old_tool_in_tray and new_tool_in_tray:
                message = 'Use ATC to fetch tool {:d}?'.format(tool_num)

            if old_tool_in_tray or new_tool_in_tray:
                dialog = popupdlg.yes_no_cancel_popup(self.window, message)
                dialog.run()
                dialog.destroy()
                if dialog.response == gtk.RESPONSE_YES:
                    self.dro_list['atc_auto_dro'].set_text(str(tool_num))
                    self.dro_list['atc_auto_dro'].queue_draw()
                    self.atc.fetch(self.dro_list['atc_auto_dro'])
                    return

                elif dialog.response == gtk.RESPONSE_NO:
                    if old_tool_in_tray and not new_tool_in_tray:
                        self.atc.delete_tray_assignment(self.status.tool_in_spindle)

                elif dialog.response == gtk.RESPONSE_CANCEL:
                    return

        # Rest has nothing to do with ATC -  Just make the requested tool active with offset
        tool_change_command = 'M61 Q%d G43 H%d' % (tool_num, tool_num)
        self.issue_mdi(tool_change_command)
        self.issue_mdi(tool_change_command)   # do it twice due to bug in Q0


        self.set_image('m6_g43_image', 'M6_G43.png')
        self.window.set_focus(None)

    def on_m6_g43_key_press_event(self, widget, event):
        if event.keyval == gtk.keysyms.Return or event.keyval == 65421:
            self.on_m6_g43_button_release_event(self, widget)
        elif event.keyval == gtk.keysyms.Escape:
            self.set_image('m6_g43_image', 'M6_G43.png')
            self.window.set_focus(None)
        return True

    def stop_jog(self, jog_axis):
        # unconditionally stop jog - do not check mode here!!!
        self.jogging_stopped = False
        self.command.jog(linuxcnc.JOG_STOP, jog_axis)

    def get_jog_increment(self, axis_ind):
        """Return a jog increment based on the specified axis index"""
        return self.jog_increment_scaled

    def jog(self, jog_axis, jog_direction, jog_speed, apply_pct_override=True, jog_mode = None):
        if self.program_running(True):
            return

        if self.status.task_state in (linuxcnc.STATE_ESTOP, linuxcnc.STATE_ESTOP_RESET, linuxcnc.STATE_OFF):
            self.error_handler.write("Must take machine out of estop before jogging")
            return

        # If an explicit jog mode is specified, use that, otherwise assume the
        # current GUI mode
        if jog_mode is None:
            jog_mode = self.jog_mode

        self.ensure_mode(linuxcnc.MODE_MANUAL)

        # Compute actual jog speed from direction, absolute speed, and percent
        # override
        speed = jog_direction * jog_speed

        # Encourage referencing and try to avoid axis jamming by slowing jog speed while
        # unreferenced.
        referenced = (self.x_referenced and self.y_referenced and self.z_referenced)
        if self.machineconfig.has_hard_stop_homing() and not referenced:
            #clamp bi-directional speed to +/-5%, but use even less if speed value was already <5%
            # apply_pct_override is _always_ ignored on purpose if servos (M+ or MX) and not homed
            if speed >= 0 and speed > self.axis_unhomed_clamp_vel[jog_axis]:
                speed = self.axis_unhomed_clamp_vel[jog_axis]
            elif speed < 0 and speed < (-1.0 * self.axis_unhomed_clamp_vel[jog_axis]):
                speed = -1.0 * self.axis_unhomed_clamp_vel[jog_axis]
        elif apply_pct_override:
            speed *= self.jog_override_pct

        if jog_mode == linuxcnc.JOG_CONTINUOUS:
            #Continous jogging
            self.command.jog(jog_mode, jog_axis, speed)
            self.jogging_stopped = True

        elif jog_mode == linuxcnc.JOG_INCREMENT:
            # Step jogging
            if self.moving(): return
            # Scale distance for the current axis
            displacement = self.get_jog_increment(jog_axis) / self.get_axis_scale(jog_axis)
            self.command.jog(jog_mode, jog_axis, speed, displacement)


    # ---------------------------------------------------------------------
    # File tab
    # ---------------------------------------------------------------------

    def on_exit_button_release_event(self, widget, data=None):
        btn.ImageButton.unshift_button(widget)
        self.stop_motion_safely()
        self.hide_m1_image()
        conf_dialog = popupdlg.shutdown_confirmation_popup(self.window)
        self.window.set_sensitive(False)
        conf_dialog.run()
        conf_dialog.destroy()
        if conf_dialog.response == gtk.RESPONSE_CANCEL:
            self.window.set_sensitive(True)
            if self.vlcwidget:
                self.vlcwidget.player.play()
        else:
            self.quit()


    def quit(self):
        self.axis_motor_command(2, MOTOR_CMD_DISABLE)
        self.axis_motor_command(1, MOTOR_CMD_DISABLE)
        self.axis_motor_command(0, MOTOR_CMD_DISABLE)

        self.atc.terminate()
        if self.notify_at_cycle_start:  # is anyone waiting on us
            self.notify_at_cycle_start = False
            try:
                self.redis.hset("TormachAnswers",self.notify_answer_key,"!")  #start pressed message
                self.hal['prompt-reply'] = 2
                self.error_handler.write('prompt output pin set to 2 by exit', ALARM_LEVEL_DEBUG)
            except Exception as e:
                traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))
                self.error_handler.write("Whooops! - Tormach message reply not set.  Exception: %s" % traceback_txt, ALARM_LEVEL_DEBUG)
        self._quit()
        gtk.main_quit()
        self.watcher.stop()

    def on_probe_sim_button_press(self, widget, data=None):
        if 'lo' in widget.get_label():
            self.hal['probe-sim'] = 1
            widget.set_label("Probe - hi")
        else:
            self.hal['probe-sim'] = 0
            widget.set_label("Probe - lo")


    # ---------------------------------------------------------------------
    # ATC tab
    #----------------------------------------------------------------------


    # Bob - all callbacks for the buttons on the atc tab are defined on the following lines.  You can ignore the button press events - its
    # just the release events that you're going to be concerned with.

    def on_atc_manual_insert_dro_activate(self, widget, data=None):
        if self.program_running(): return

        valid, value, error_msg = self.conversational.validate_tool_number(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text("%1d" % value)
        self.set_image('atc_insert_image', 'ATC_Insert_Highlighted.png')
        self.button_list['atc_insert'].grab_focus()

    def on_atc_insert_key_press_event(self, widget, event):
        if self.program_running(): return
        if event.keyval == gtk.keysyms.Return or event.keyval == 65421:
            self.on_atc_insert_button_release_event(self.button_list['atc_insert'])
        elif event.keyval == gtk.keysyms.Escape:
            self.set_image('atc_insert_image', 'ATC_Insert.png')
            self.window.set_focus(None)
        return True

    def on_atc_insert_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.set_image('atc_insert_image', 'ATC_Insert.png')
        self.atc.insert(self.dro_list['atc_manual_insert_dro'])

    def on_atc_delete_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.delete(self.dro_list['atc_manual_insert_dro'])

    def on_atc_delete_all_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if self.program_running(): return
        self.atc.delete_all()

    def on_atc_tray_forward_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # Force necessary window repainting
        ui_misc.force_window_painting()
        self.atc.tray_fwd()

    def on_atc_tray_reverse_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # Force necessary window repainting
        ui_misc.force_window_painting()
        self.atc.tray_rev()

    def on_atc_goto_tray_load_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.go_to_tray_load_position()

    def on_atc_retract_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # Force necessary window repainting
        ui_misc.force_window_painting()
        self.atc.retract()

    def on_atc_drawbar_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # Force necessary window repainting
        ui_misc.force_window_painting()
        if  self.atc.get_drawbar_state():
            self.atc.set_drawbar_up()
            self.set_image('atc_drawbar_image', 'Drawbar-Down-Green.png')
        else:
            self.atc.set_drawbar_down()
            self.set_image('atc_drawbar_image', 'Drawbar-Up-Green.png')

    def on_atc_blast_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # Force necessary window repainting
        ui_misc.force_window_painting()
        self.atc.blast()

    def on_atc_ref_tray_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.home_tray ()

    def on_atc_minus_minus_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.offset_tray_neg ()

    def on_atc_plus_plus_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.offset_tray_pos()

    def on_atc_set_tc_z_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        if self.z_referenced:
            message = 'Set tool change position to Z %.4f?' % (self.status.actual_position[2] * self.get_axis_scale(2))
            dialog = popupdlg.ok_cancel_popup(self.window, message)
            dialog.run()
            ok_cancel_response = dialog.response
            dialog.destroy()
            if ok_cancel_response == gtk.RESPONSE_OK:
                if self.atc.set_tc_z():
                    self.set_image('set_tool_change_z_image', 'Set-TC-POS-Green.png')
        else:
            self.error_handler.write("Must reference Z axis before setting tool change position.", ALARM_LEVEL_MEDIUM)

    def on_atc_set_tc_m19_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return  #TODO is there anything else to be done here???

        # the ATC tray must be referenced before setting the M19 orient position
        if self.hal["atc-trayref-status"]:
            self.on_bt30_button_release_event(widget, data)
            if self.hal['spindle-bt30-offset'] == BT30_OFFSET_INVALID:
                self.set_image('set_tool_change_m19_image', 'Set-TC-M19-Black.png')
            else:
                self.set_image('set_tool_change_m19_image', 'Set-TC-M19-Green.png')
        else:
            message = "You must reference the ATC tool tray before you set the BT30 spindle alignment position.\n\nNotice!  The tool tray rotates when it's referenced, which could cause a collision with the spindle or any items on the machine table.\n\n1. After selecting OK, retract the tray away from the spindle and remove any items from the machine table.\n\n2. Select Ref Tool Tray to start the referencing procedure.\n\n3. Once the reference procedure is complete, select Set TC M19 again."
            with popupdlg.ok_cancel_popup(self.window, message, cancel=False) as dlg:
                pass

    def on_atc_auto_dro_activate(self, widget, data=None):
        if self.program_running(): return
        valid, value, error_msg = self.conversational.validate_tool_number(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text("%1d" % value)
        self.set_image('atc_remove_image', 'ATC_Remove_Highlighted.png')
        self.button_list['atc_remove'].grab_focus()

    def on_atc_remove_key_press_event(self, widget, event):
        if self.program_running(): return
        if event.keyval == gtk.keysyms.Return or event.keyval == 65421:
            self.on_atc_remove_button_release_event(self.button_list['atc_remove'])
        elif event.keyval == gtk.keysyms.Escape:
            self.set_image('atc_remove_image', 'ATC_Remove.png')
            self.window.set_focus(None)
        return True

    def on_atc_remove_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.remove(self.dro_list['atc_auto_dro'])
        self.set_image('atc_remove_image', 'ATC_Remove.png')

    def on_atc_rev_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.atc_rev()

    def on_atc_fw_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.atc_fwd()

    def on_atc_store_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.store()

    def on_atc_touch_entire_tray_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.atc.touch_entire_tray()


    # ---------------------------------------------------------------------
    # Injection molder tab
    #----------------------------------------------------------------------

    def on_inject_dwell_dro_activate(self, widget, data=None):
        valid, value, error_msg = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.injector_dwell = value
        self.redis.hset('machine_prefs', 'injector_dwell', str(self.injector_dwell))
        widget.set_text(self.dro_medium_format % value)
        self.window.set_focus(None)

    def on_inject_button_release_event(self, widget, data=None):
        btn.ImageButton.unshift_button(widget)
        limit = self.status.axis[2]['min_position_limit']
        self.issue_mdi('o<inject> call [%f] [%f] [%f]' % (self.f_word, self.injector_dwell, limit))

    def on_notebook_switch_page(self, notebook, page, page_num):
        """Called from GTK signal when the main UI notebook changes page

        Args:
            notebook (gtk.Notebook): the notebook that received the signal
            page (gtk.Fixed): the new current page (note that this is a
                              GPointer and not directly usable)
            page_num (int): the index of the new current page
        """
        TormachUIBase.on_notebook_switch_page(self,notebook, page, page_num)

        page = notebook.get_nth_page(page_num)
        page_id = gtk.Buildable.get_name(page)

        if self.current_notebook_page_id == 'conversational_fixed':
            self.dxf_panel.ready = False


        if page_id == 'alarms_fixed':
            if self.atc.operational:
                self.show_atc_diagnostics()
            else:
                self.hide_atc_diagnostics()


        if page_id == 'notebook_offsets_fixed':
            if self.pn_data is None: self.pn_data = mill_fs.MillPnData(self)
            self.refresh_tool_liststore()
            self.highlight_offsets_treeview_row()
            # this also should be handled in init, but when these are called from init the gtk widgets haven't yet been realized
            # and the widget visibility isn't set appropriately.  This is another bandaid on this problem
            if self.atc.operational:
                self.show_atc_diagnostics()
            else:
                self.hide_atc_diagnostics()

            # tell the height gauge HAL comp to wake up
            self.hal['hg-enable'] = True
            self.zero_height_gauge_show_or_hide()

            # Be sure the work offsets are updated when switching to
            # the notebook
            self.refresh_work_offset_liststore()
        else:
            # tell the height gauge HAL comp to go to sleep
            self.hal['hg-enable'] = False

        if page_id == 'atc_fixed':

            if self.moving(): return
            self.atc.display_tray()

        if page_id == 'conversational_fixed':
            self.load_title_dro()
            self.test_valid_tool(None,actions=('allow_empty','validate_fs',))
            self.thread_custom_file_reload_if_changed()

            if self.g21:
                unit_string = 'mm'
                self.thread_chart_combobox.set_model(self.thread_chart_g21_liststore)
            else:
                unit_string = 'in'
                self.thread_chart_combobox.set_model(self.thread_chart_g20_liststore)

            html_fmt = '<span weight="light" font_desc="Bebas 12" font_stretch="ultracondensed" foreground="white" >%s:</span>'
            self.tap_labels['tpu'].set_markup(html_fmt % 'Threads/%s      ' % unit_string)
            self.tap_labels['pitch'].set_markup(html_fmt % 'Pitch    (%s)    ' % unit_string)
            self.thread_mill_tpu_label.set_markup(html_fmt %'Threads/%s    ' % unit_string)
            self.thread_mill_pitch_label.set_markup(html_fmt %'Pitch    (%s)    ' % unit_string)
            page_id = get_current_notebook_page_id(self.conv_notebook)

            page_id = self.get_current_conv_notebook_page_id()
            glib.idle_add(self._update_stepover_hints)
            glib.idle_add(self.update_chip_load_hint, page_id)


            if self.current_conv_notebook_page_id_is('conv_dxf_fixed'):
                self.dxf_panel.ready = True

    # startup actions for each conversational page, such as graying out DROs
    # that don't apply
    # These need to match the focus passing order in the
    # 'on_conv_???_dro_activate' modules
    def _conversational_notebook_switch_page(self, conv_page_num ):
        # TODO - save off values in common dros in redis, keyed to the page that the user was on.
        # restore these values when the user switches to the new page.
        tap_z_feed = self.calc_tap_z_feed_rate()
        if tap_z_feed != self.current_normal_z_feed_rate:
            self.conv_dro_list['conv_z_feed_dro'].set_text(self.current_normal_z_feed_rate)
        page_id = get_notebook_page_id(self.conv_notebook, conv_page_num)
        self.save_title_dro()
        self.load_title_dro(page_id)
        self.fs_mgr.clr_calced_dros()

        if 'conv_dxf_fixed' != page_id:
            self.dxf_panel.ready = False

        if 'conv_face_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
            self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)
            self.on_conversational_face_switch_page()

        elif 'conv_profile_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
            self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)

        elif 'conv_pocket_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            if self.conv_pocket_rect_circ == 'rect':
                self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
                self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
                self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            else:  # self.conv_pocket_rect_circ == 'circ':
                self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
                self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
                self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)

        elif 'conv_drill_tap_fixed' == page_id:  # Drill/Tap button should also set these
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.update_drill_through_hole_hint()
            if self.conv_drill_tap == 'drill':
                self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
                self.conv_dro_list['conv_feed_dro'].set_sensitive(False)
                self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            else:   # self.conv_drill_tap == 'tap':
                tap_z_feed = self.calc_tap_z_feed_rate()
                self.conv_dro_list['conv_z_feed_dro'].set_text(tap_z_feed)
                self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
                self.conv_dro_list['conv_feed_dro'].set_sensitive(False)
                self.conv_dro_list['conv_z_feed_dro'].set_sensitive(False)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)

        elif 'conv_thread_mill_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
            self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(False)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)
            self.thread_mill_int_minimal_retract_check.set_visible(self.conv_thread_mill_ext_int == 'internal')

        elif 'conv_engrave_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
            self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(False)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)
            self.conv_engrave_switch_page()

        elif 'conv_dxf_fixed' == page_id:
            self.conv_dro_list['conv_work_offset_dro'].set_sensitive(True)
            self.conv_dro_list['conv_tool_number_dro'].set_sensitive(True)
            self.conv_dro_list['conv_rpm_dro'].set_sensitive(True)
            self.conv_dro_list['conv_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            self.conv_dro_list['conv_z_clear_dro'].set_sensitive(True)
            self.dxf_panel.ready = True
        glib.idle_add(self.update_chip_load_hint, page_id)
        glib.idle_add(self._update_stepover_hints)
        self.test_valid_tool(None, actions=('report_error',))


    def on_conversational_notebook_switch_page(self, notebook, page, conv_page_num ):
        self._conversational_notebook_switch_page(conv_page_num)

    def on_touch_z_dro_activate(self, widget, data=None):

        valid, dro_val, error_msg = self.conversational.validate_z_point(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.dro_list['touch_z_dro'].set_text(self.dro_long_format % dro_val)
        self.set_image('touch_z_image', 'touch_z_highlight.png')
        # next line not working as it should.
        self.button_list['touch_z'].grab_focus()

    def on_touch_z_button_release_event(self, widget, data=None):
        btn.ImageButton.unshift_button(widget)

        valid, dro_val, error_msg = self.conversational.validate_z_touch_val(self.dro_list['touch_z_dro'])
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        ind = 2
        # the G10 command wants values in mm if G21, but actual_postion and g5x_offsets are in machine units (in.)
        # so we take the sup value and turn it into machine units, then send the offset command in g20/21 units
        supplemental_offset = dro_val / self.get_axis_scale(ind)
        tool_number = self.status.tool_in_spindle
        # g10 doesn't like tool number = zero, and tool number will be -1 in some cases on startup
        if tool_number < 1:
            self.error_handler.write('Cannot set tool offset for tool zero.  Please enter a valid tool number in the tool DRO before using Touch Z button', ALARM_LEVEL_MEDIUM)
            return

        z_offset = self.status.actual_position[ind] - self.status.g5x_offset[ind] - supplemental_offset
        z_offset = z_offset * self.get_axis_scale(ind)

        # can't use self.issue_tool_offset_command() here as this takes L10, other calls take L1
        g10_command = "G10 L10 P%d Z%f" %(tool_number, dro_val)
        self.issue_mdi(g10_command)
        self.command.wait_complete()
        self.issue_mdi("G43")
        self.dro_list['touch_z_dro'].set_text(self.dro_long_format % dro_val)
        self.set_image('touch_z_image', 'touch_z_green_led.png')
        self.window.set_focus(None)
        # kludge for asyncronous refresh of tool table, handled in periodic
        self.tool_liststore_stale = 2


    def on_touch_z_key_press_event(self, widget, event):
        # Return or Enter key valid.  couldn't find keysyms constant for Enter key.
        if event.keyval == gtk.keysyms.Return or event.keyval == 65421:
            self.on_touch_z_button_release_event(self, self.button_list['touch_z'])
            self.window.set_focus(None)
        elif event.keyval == gtk.keysyms.Escape:
            self.set_image('touch_z_image', 'touch_z_black_led.png')
            self.window.set_focus(None)
        return True

    def on_move_and_set_tool_length_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if self.status.tool_in_spindle < 1:
            self.error_handler.write("Cannot set tool length with tool 0 in spindle.  Please change the active tool to a valid tool number before proceeding.", ALARM_LEVEL_MEDIUM)
            return
        self.mill_probe.probe_move_and_set_tool_length()
        # set flag used by periodic to refresh tool treeview
        self.tool_liststore_stale = 2

    def on_move_and_set_work_offset_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        if self.mill_probe.ets_height < 0:
            self.error_handler.write('Set tool setter (Probe/ETS Setup, Step 2) before tool length', ALARM_LEVEL_LOW)
            return
        self.work_probe_in_progress = True
        self.mill_probe.probe_find_work_z_with_ets()


    def on_export_tool_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.export_tooltable()


    def on_import_tool_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.import_tooltable()

    # ~~~~~~~~~
    # tool table callbacks
    # ~~~~~~~~~

    # ~~~~~~~~~  tool_description_column handlers

    def tool_table_rows(self):
        return MAX_NUM_MILL_TOOL_NUM

    def on_tool_description_column_edited(self, cell, row, tool_description, model, data=None ):
        # the tool number is NOT necessarily the row number + 1 because the tool tree view may be filtered
        # to just be showing tools used by the current program.
        target_iter = model.get_iter(row)
        pocket = model.get(target_iter, 0)[0]
        tool_number = self.status.tool_table[pocket].id
        if tool_number == MILL_PROBE_TOOL_NUM:
            self.error_handler.write("Tool %s description reserved for Probe." % (MILL_PROBE_TOOL_NUM), ALARM_LEVEL_MEDIUM)
            if 'proc' in data:
                data['proc'](MILL_PROBE_TOOL_DESCRIPTION)
            return
        s = tool_description
        s1 = s.replace('(','[')
        s2 = s1.replace(')',']')
        model[row][1] = s2
        self.set_tool_description(tool_number, s2)
        if data is not None and 'proc' in data:
            data['proc'](tool_description)

    # ~~~~~~~~~  tool_diameter_column handlers
    def on_tool_diameter_column_editing_started(self, diam_renderer, editable, path):
        # upon entering this cell, capture the context and setup what to do and where to go next
        if path == '':
            row = 0
        else:
            row = int(path)
        # capture key press to determine next cell to edit
        editable.connect("key-press-event",self.on_tool_diameter_column_keypress,row)

    def on_tool_diameter_column_keypress(self,widget,ev,row):
        if ev.keyval in (gtk.keysyms.Return, gtk.keysyms.KP_Enter):
            glib.idle_add(self.tool_table_update_focus, row, self.tool_length_column, True)
        return False

    def on_tool_diameter_column_edited(self, cell, row, value, model ):
        # support for user deleteing old value, not entering 0.0
        if value is '': value = '0.0'
        valid, value, error_msg = self.conversational.validate_tool_offset(value)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        self.set_tool_diameter(row, value, model)
        model[row][2] = "%0.4f" % value
        glib.idle_add(self.tool_table_update_observer, row)

    def __tool_diameter_in_limits(self, tool_number, value, data):
        # if the 'type' is an endmill style then DON'T set if it's within .010 of the
        # current value as the current value may be an 'adjustment' made by the user...
        # returning 'True' will NOT set the tool diameter column - return 'False' will
        if not data: return False
        if not isinstance(data,dict): return False
        # Note: 'data' is valid if this is called from <ui_common.TormachUiBase._parse_pn_text.__parse_tool_description_text'
        # this is the case where the user has changed the 'dia:' field in the tool description and now
        # the tool diameter held in the 'Diameter' column in the tool table needs to be updated.
        if 'type' not in data: return False
        if data['type'].lower() not in ('endmill', 'bullnose','ball','indexable','flat','lollypop'): return False
        curr_tool_val = self.get_tool_diameter(tool_number)*self.get_linear_scale()
        if curr_tool_val == 0.0: return False
        fval = float(value)
        _limit = .005*self.get_linear_scale()
        fv_lo,fv_hi = (fval-_limit,fval+_limit)
        if fv_lo<curr_tool_val<fv_hi: return True
        msg = tooltipmgr.TTMgr().get_local_string('user_query_pathpilot_to_change_tool_diameter')
        msg = msg.format(self.dro_long_format%curr_tool_val,self.dro_long_format%fval)
        with popupdlg.ok_cancel_popup(self.window, msg) as user_query:
            if user_query.response == gtk.RESPONSE_OK: return False
        return True

    def set_tool_diameter(self, row, value, model, data=None):
        # the tool number is NOT necessarily the row number + 1 because the tool tree view may be filtered
        # to just be showing tools used by the current program.
        target_iter = model.get_iter(row)
        pocket = model.get(target_iter, 0)[0]
        tool_number = self.status.tool_table[pocket].id
        if not value: value = '0.0'
        if self.__tool_diameter_in_limits(tool_number, value, data): return
        if not isinstance(data,dict) or 'cmd' not in data or 'g10' in data['cmd']:
            # this is being set from a tool description...
            self.issue_tool_offset_command('R', tool_number, (float(value)/2.))
        model[row][2] = "%0.4f" % float(value)

    def set_tool_table_data(self,model,row, data):
        if 'diameter' in data:
            self.set_tool_diameter(row, data['diameter'],model,data)
            return True
        return False

    # ~~~~~~~~~  tool_length_column handlers
    def on_tool_length_column_editing_started(self, length_renderer, editable, path):
        # upon entering this cell, capture the context and setup what to do and where to go next
        #editable.modify_font(drill_font)  # reassert any previous font change to this next editing context
        if path == '':
            row = 0
        else:
            row = int(path)
        # capture key press to determine next cell to edit
        editable.connect("key-press-event",self.on_tool_length_column_keypress,row)

    def on_tool_length_column_keypress(self,widget,ev,row):
        if ev.keyval in (gtk.keysyms.Return, gtk.keysyms.KP_Enter):
            glib.idle_add(self.tool_table_update_focus, row + 1, self.tool_description_column, False)
        return False

    def on_tool_length_column_edited(self, cell, row, value, model ):
        # support for user deleteing old value, not entering 0.0
        if value is '': value = '0.0'
        valid, value, error_msg = self.conversational.validate_tool_offset(value)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return

        # the tool number is NOT necessarily the row number + 1 because the tool tree view may be filtered
        # to just be showing tools used by the current program.
        target_iter = model.get_iter(row)
        pocket = model.get(target_iter, 0)[0]
        tool_number = self.status.tool_table[pocket].id
        self.issue_tool_offset_command('Z', tool_number, value)
        model[row][3] = "%0.4f" % value
        if tool_number == self.status.tool_in_spindle:
            # wer're changing the length offset, so we want to reapply it as well
            self.command.wait_complete()
            self.issue_mdi("G43")
        glib.idle_add(self.tool_table_update_observer,row)

    # -------------------------------------------------------------------------------------------------
    # end of tool touch-off callbacks
    # -------------------------------------------------------------------------------------------------

    # ---------------------------------------------------------------------
    # work offset tab callbacks
    # ---------------------------------------------------------------------

    def on_work_column_editing_started(self, renderer, editable, path,
                                       next_col, row_incr):
        if path == '':
            row = 0
        else:
            row = int(path)
        editable.modify_font(self.work_font)

        # capture key press to determine next cell to edit
        editable.connect("key-press-event",self.on_work_column_keypress,row,
                         next_col, row_incr)

    def on_work_column_keypress(self, widget, ev, row, next_col, row_incr):
        if ev.keyval in (gtk.keysyms.Return, gtk.keysyms.KP_Enter):
            glib.idle_add(self.work_treeview.set_cursor,
                          row+row_incr, next_col, True)
        return False

    def on_work_column_edited(self, cell, row, value, model, columnname):
        row = 0 if row == '' else int(row)

        # because we can filter the table of work offsets, we can't depend on the row number
        # to figure out which offset they edited.  The element in the model is the offset index.
        offset_index = model[row][8]

        if columnname == 'description':
            model[row][1] = value    # change the UI using the row number
            keyname = 'G54.1 P{:d} desc'.format(offset_index)
            self.redis.hset('machine_prefs', keyname, value)
            self.error_handler.log('Changed {} to {}'.format(keyname, value))

        else:
            if value == '':  value = '0.0'
            axis = columnname
            valid, value, error_msg = self.conversational.validate_offset(
                value, axis.upper())
            if not valid:
                self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
                return

            col = dict(x=2,y=3,z=4,a=5)[axis]
            model[row][col] = ("%0.4f" % value) if isinstance(value,float) else value

            # check for reference first
            lcnc_axis = col - 2
            if not self.status.homed[lcnc_axis]:
                self.error_handler.write("Must reference {} axis before setting work offset.".format(axis.upper()), ALARM_LEVEL_MEDIUM)
                return

            # log the change to the status screen in case the operator forgot they're in the wrong work coordinate system
            # and just zero'd out a valuable number.
            work_offset_name = self.get_work_offset_name_from_index(offset_index)  # e.g. G55 or G59.1
            format_without_percent = self.dro_long_format[1:]
            msg_template = "{:s} {:s} axis work offset changed from {:" + format_without_percent + "} to {:" + format_without_percent + "}."
            old_value = self.status.g5x_offsets[offset_index][lcnc_axis] * self.get_linear_scale()

            g10_command = "G10 L2 P%s %s%s" % (offset_index, axis.upper(), value)
            self.issue_mdi(g10_command)
            self.command.wait_complete()

            self.status.poll()  # get fresh numbers

            new_value = self.status.g5x_offsets[offset_index][lcnc_axis] * self.get_linear_scale()
            msg = msg_template.format(work_offset_name, axis.upper(), old_value, new_value)
            self.error_handler.write(msg, ALARM_LEVEL_QUIET)


    # ---------------------------------------------------------------------
    # end of work offset tab callbacks
    # ---------------------------------------------------------------------



    # -------------------------------------------------------------------------------------------------
    # conversational tab callbacks
    # -------------------------------------------------------------------------------------------------

    def on_thread_tab(self):
        return self.current_conv_notebook_page_id_is('conv_thread_mill_fixed')

    def generate_gcode(self, page_id=None):
        try:
            # NOTE!  The actual child object id="" attribute from the glade file is used to
            # uniquely identify each notebook page and to figure out which is the current page.
            # Do NOT add any text label comparisons.
            # NOTE! param: 'page_id' if not None will be the correct id from the current
            # step in 'Conv-Edit' requesting a re-generation.
            active_child_id = page_id if page_id else self.get_current_conv_notebook_page_id()

            valid = False

            if 'conv_face_fixed' == active_child_id:
                (valid, gcode_output_list) = self.conversational.generate_face_gcode(self.conv_dro_list, self.face_dro_list, self.conv_face_spiral_rect)
                self.save_conv_parameters(self.face_dro_list)

            elif 'conv_profile_fixed' == active_child_id:
                (valid, gcode_output_list) = self.conversational.generate_profile_gcode(self.conv_dro_list, self.profile_dro_list, self.conv_profile_rect_circ)
                self.save_conv_parameters(self.profile_dro_list)

            elif 'conv_pocket_fixed' == active_child_id:
                if self.conv_pocket_rect_circ == 'rect':
                    (valid, gcode_output_list) = self.conversational.generate_pocket_rect_gcode(self.conv_dro_list, self.pocket_rect_dro_list)
                    self.save_conv_parameters(self.pocket_rect_dro_list)
                else: # Pocket, Circular
                    # X Y locations are from the drill table, so check table
                    # find last row
                    last_row = 0
                    row_id = 0
                    for row in self.drill_liststore:
                        if (row[1] != '') or (row[2] != ''):  # something is in this row
                            last_row = row_id
                        row_id += 1

                    # check for valid table entries
                    # TODO - This is called a number of times near here, so maybe make a function and call it?
                    # TODO - The error text is the only difference
                    id_cnt = 0
                    for row in self.drill_liststore:
                        if id_cnt <= last_row:
                            if (row[1] == '') and (row[2] == ''):  # empty row
                                # highlight X and Y
                                row[1] = '??'
                                row[2] = '??'
                            elif row[1] == '':  # something is in Y
                                # highlight X
                                row[1] = '??'
                            elif row[2] == '':  # something is in X
                                # highlight Y
                                row[2] = '??'
                        id_cnt += 1

                    for row in self.drill_liststore:
                        if (row[1] == '??') or (row[2] == '??'):  # errors exist in table
                            self.error_handler.write('Pocket, Circular - Please fill in X Y locations in the Drill table, then return to Pocket, Circular and Post')
                            self.set_conv_page_from_id('conv_drill_tap_fixed')
                            return False, ''

                    (valid, gcode_output_list) = self.conversational.generate_pocket_circ_gcode(self.conv_dro_list, self.pocket_circ_dro_list, self.drill_liststore)
                    self.save_conv_parameters(self.pocket_circ_dro_list)

            elif 'conv_drill_tap_fixed' == active_child_id:
                if self.drill_pattern_notebook_page == 'pattern':
                    # find last row
                    last_row = 0
                    row_id = 0
                    for row in self.drill_liststore:
                        if (row[1] != '') or (row[2] != ''):  # something is in this row
                            last_row = row_id
                        row_id += 1
                     # check for valid table entries
                    id_cnt = 0
                    for row in self.drill_liststore:
                        if id_cnt <= last_row:
                            if (row[1] == '') and (row[2] == ''):  # empty row
                                # highlight X and Y
                                row[1] = '??'
                                row[2] = '??'
                            elif row[1] == '':  # something is in Y
                                # highlight X
                                row[1] = '??'
                            elif row[2] == '':  # something is in X
                                # highlight Y
                                row[2] = '??'
                        id_cnt += 1

                    for row in self.drill_liststore:
                        if (row[1] == '??') or (row[2] == '??'):  # errors exist in table
                            return False, ''

                if self.conv_drill_tap == "drill":
                    (valid, gcode_output_list) = self.conversational.generate_drill_gcode(self.conv_dro_list, self.drill_dro_list, self.drill_circular_dro_list, self.drill_pattern_notebook_page, self.drill_liststore)
                    self.save_conv_parameters(self.drill_dro_list)
                    self.save_conv_parameters(self.drill_circular_dro_list)
                else:  # == tap
                    (valid, gcode_output_list) = self.conversational.generate_tap_gcode(self.conv_dro_list, self.tap_dro_list, self.drill_circular_dro_list, self.drill_pattern_notebook_page, self.drill_liststore, self.tap_2x_enabled)
                    self.save_conv_parameters(self.tap_dro_list)
                    self.save_conv_parameters(self.drill_circular_dro_list)

            elif 'conv_thread_mill_fixed' == active_child_id:
                # find last row
                last_row = 0
                row_id = 0
                for row in self.drill_liststore:
                    if (row[1] != '') or (row[2] != ''):  # something is in this row
                        last_row = row_id
                    row_id += 1

                # check for valid table entries
                id_cnt = 0
                for row in self.drill_liststore:
                    if id_cnt <= last_row:
                        if (row[1] == '') and (row[2] == ''):  # empty row
                            # highlight X and Y
                            row[1] = '??'
                            row[2] = '??'
                        elif row[1] == '':  # something is in Y
                            # highlight X
                            row[1] = '??'
                        elif row[2] == '':  # something is in X
                            # highlight Y
                            row[2] = '??'
                    id_cnt += 1

                for row in self.drill_liststore:
                    if (row[1] == '??') or (row[2] == '??'):  # errors exist in table
                        self.error_handler.write('Thread Mill - Please fill in X Y locations in the Drill table, then return to Thread Mill and Post')
                        self.set_conv_page_from_id('conv_drill_tap_fixed')
                        return False, ''

                if self.conv_thread_mill_ext_int == 'external':
                    (valid, gcode_output_list) = self.conversational.generate_thread_mill_ext_gcode(self.conv_dro_list, self.thread_mill_ext_dro_list, self.drill_liststore, self.thread_mill_rhlh)
                    self.save_conv_parameters(self.thread_mill_ext_dro_list)
                else:
                    (valid, gcode_output_list) = self.conversational.generate_thread_mill_int_gcode(self.conv_dro_list, self.thread_mill_int_dro_list, self.drill_liststore, self.thread_mill_rhlh)
                    self.save_conv_parameters(self.thread_mill_int_dro_list)

            elif 'conv_engrave_fixed' == active_child_id:
                if self.engrave_font_pf == '':  # TODO: this may have been done elsewhere?
                    self.error_handler.write('Engrave error - Please select a font')
                    gcode_output_list = ''
                else:
                    (valid, gcode_output_list) = self.conversational.generate_engrave_gcode(self.conv_dro_list, self.engrave_dro_list, self.engrave_font_pf, self.engrave_just)
                    self.save_conv_parameters(self.engrave_dro_list)

            elif 'conv_dxf_fixed' == active_child_id:
                (valid, gcode_output_list) = self.conversational.generate_dxf_gcode(self.conv_dro_list, self.dxf_panel.dro_list, self.dxf_panel)
                self.save_conv_parameters(self.dxf_panel.dro_list)

            active_main_child = self.notebook.get_nth_page(self.notebook.get_current_page())
            active_main_page_id = get_current_notebook_page_id(self.notebook)
            active_camera_child = self.camera_notebook.get_nth_page(self.camera_notebook.get_current_page())
            active_camera_page_id = get_current_notebook_page_id(self.camera_notebook)

            if active_main_page_id == 'scanner_fixed' and active_camera_page_id == 'scanner_scope_fixed':
                (valid, gcode_output_list) = self.conversational.generate_scope_gcode(self.scope_liststore, self.conv_dro_list)
                self.save_conv_parameters(self.face_dro_list)

            return valid, gcode_output_list

        except Exception:
            ex = sys.exc_info()
            # wrap this just in case something dies trying to log it.
            try:
                self.error_handler.write(ex[1].message, ALARM_LEVEL_HIGH)
            except:
                pass
            # Re-raising the exception this way preserves the original call stack so things are logged perfectly
            # with the root cause of the exception easily logged vs. the line number of this raise.
            raise ex[0], ex[1], ex[2]

    def on_post_to_file_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        # generate the code
        valid, gcode_output_list = self.generate_gcode()
        if valid:
            self.save_title_dro()
            self.post_to_file(self.window, self.conv_dro_list['conv_title_dro'].get_text(), gcode_output_list,
                              query=True, load_file=True, closewithoutsavebutton=False)

    def on_append_to_file_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        # generate the code:
        valid, gcode_output_list = self.generate_gcode()
        if not valid or not any(gcode_output_list):
            return

        path = self.last_used_save_as_path + os.path.sep
        with tormach_file_util.append_to_file_popup(self.window, path) as dialog:
            #Get information from dialog, then destroy automatically
            response = dialog.response
            self.last_used_save_as_path = dialog.current_directory
            path = dialog.get_path()

        if response == gtk.RESPONSE_OK:
            self._update_append_file(path, gcode_output_list)

    #def on_conv_g20_g21_dro_activate(self, widget, data=None):
    #    self.dro_list['conv_work_offset_dro'].grab_focus()

    ####  Common DROs, get text and focus passing
    # DRO gray-outs are done in on_conversational_notebook_switch_page
    def on_conv_title_dro_activate(self, widget, data=None):
        self.conv_title = widget.get_text()
        self.conv_dro_list['conv_work_offset_dro'].grab_focus()

    def on_conv_work_offset_dro_activate(self, widget, data=None):
        (valid, work_offset, error_msg) = self.conversational.validate_param(widget)
        if valid:
            widget.set_text(work_offset)
            self.conv_dro_list['conv_tool_number_dro'].grab_focus()
        else:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)

    def _update_stepover_hints(self, tn=None, page_id=None):
        dros = self.get_current_dro_info(page_id)
        if dros is None: return
        if 'stepover' not in dros: return
        if 'stepover_hint' not in dros: return
        update_err = ''
        # test tool number ....
        if tn is None:
            str_num = self.conv_dro_list['conv_tool_number_dro'].get_text()
            try:
                tn = int(str_num)
                if tn <= 0: update_err = 'tool <= 0'
            except:
                update_err = 'tool not a number'
        if update_err:
            self.error_handler.log('mill._update_stepover_hints: '+update_err)
        else:
            # test stepover number...
            valid, stepover = cparse.is_number_or_expression(dros['stepover'])
            valid = valid and stepover >= 0.0
            if not valid: update_err = 'could not validate stepover'
            if update_err: self.error_handler.log('mill._update_stepover_hints: '+update_err)
        stepover_pct = 0.0
        tool_dia = 0.0
        if not update_err:
            cparse.clr_alarm(dros['stepover'])
            tool_dia = self.status.tool_table[tn].diameter * self.ttable_conv
        tool_dia_str = self.dro_long_format%tool_dia if tool_dia>=0.0 else 'N/A'
        # if the tool diameter is zero .. wrap this red color...
        if tool_dia == 0.0: tool_dia_str = '<span foreground="red">{}</span>'.format(tool_dia_str)
        stepover_pct = stepover/tool_dia*100.0 if tool_dia>0.0 else 0.0
        if stepover_pct>0.0:
            stepover_pct_str =  "%.1f"%stepover_pct
            col = 'red' if stepover_pct>100.0 else 'white'
            markup = '<span weight="light" font_desc="Roboto 9" font_stretch="condensed" foreground="white">(Stepover = </span><span foreground="{0:s}">{1:s}</span><span foreground="white">% of\ntool dia. = {2:s})</span>'.format(col,stepover_pct_str,tool_dia_str)
        else:
            markup = '<span weight="light" font_desc="Roboto 9" font_stretch="condensed" foreground="white">(Stepover = N/A \ntool dia. = {})</span>'.format(tool_dia_str)
        self.face_stepover_hint_label.set_markup(markup)
        self.profile_stepover_hint_label.set_markup(markup)
        self.pocket_rect_stepover_hint_label.set_markup(markup)


    def _get_min_max_tool_numbers(self):
        return (self.__class__._min_tool_number, self.__class__._max_tool_number)

    def _get_current_tool_dro(self):
        return self.conv_dro_list['conv_tool_number_dro']

    def get_current_dro_info(self, page_id=None):
        try:
            if not page_id: page_id = get_notebook_page_id(self.conv_notebook, self.conv_notebook.get_current_page())
            if page_id not in self.conv_page_dros: return None
            page = self.conv_page_dros[page_id]
            if 'dros' not in page: return None
            rv = page['dros']
            if page_id == 'conv_profile_fixed' and self.conv_profile_rect_circ != 'rect':             rv = page['profile_circ_dros']
            elif  page_id == 'conv_pocket_fixed' and self.conv_pocket_rect_circ != 'rect':            rv = page['pocket_circ_dros']
            elif page_id == 'conv_drill_tap_fixed'and self.conv_drill_tap != 'drill':                 rv = page['tap_dros']
            elif page_id == 'conv_thread_mill_fixed' and self.conv_thread_mill_ext_int != 'external': rv = page['thread_internal_dros']
        except AttributeError:
            self.error_handler.log('mill.get_current_dro_info: Attribute Exception for page: {}'.format(page_id))
            # this may be called because the page_id and the 'sub' page dictated
            # by vars such as 'self.conv_profile_rect_circ' may be out of sync.
            # this routine will get called again when they are in sync
        except KeyError as e:
            self.error_handler.log('mill.get_current_dro_info: KeyError Exception for page: {}'.format(page_id))
            return None
        return rv

    def on_conv_tool_number_dro_activate(self, widget, data=None):
        tool_number,err = self.test_valid_tool(widget, ('report_error',))
        if not tool_number: return
        glib.idle_add(self.exec_modify_callback,widget)
        widget.set_text(self.dro_short_format % tool_number)
        self.conv_dro_list['conv_rpm_dro'].grab_focus()


    def on_conv_rpm_dro_activate(self, widget, data=None):
        (valid, rpm, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget,self.dro_short_format % rpm)

        self.update_chip_load_hint()
        # NOTE!  The actual child object id="" attribute from the glade file is used to
        # uniquely identify each notebook page and to figure out which is the current page.
        # Do NOT add any text label comparisons.
        if self.current_conv_notebook_page_id_is("conv_drill_tap_fixed"):
            if self.conv_drill_tap == 'tap':
                try:  # calculate related dwell travel label
                    dwell = float(self.tap_dro_list['tap_dwell_dro'].get_text())
                    pitch = float(self.tap_dro_list['tap_pitch_dro'].get_text())
                    # half_dwell_travel = dwell * rpm * min/60s * pitch * 1/2
                    half_dwell_travel = (dwell * rpm * pitch) / 120
                    self.tap_labels['dwell_travel_calc'].modify_font(self.drill_calc_font)
                    self.tap_labels['dwell_travel_calc'].set_markup('<span foreground="white">%s</span>' % self.dro_dwell_format % half_dwell_travel)
                except:
                    self.tap_labels['dwell_travel_calc'].set_text('')

                self.conv_dro_list['conv_z_feed_dro'].set_text(self.calc_tap_z_feed_rate())
                self.conv_dro_list['conv_z_clear_dro'].grab_focus()
            else: # back to drill
                tap_z_feed = self.calc_tap_z_feed_rate()
                if tap_z_feed != self.current_normal_z_feed_rate:
                    self.conv_dro_list['conv_z_feed_dro'].set_text(self.current_normal_z_feed_rate)
                self.update_chip_load_hint('conv_drill_tap_fixed')
                self.conv_dro_list['conv_z_feed_dro'].grab_focus()
        else:
            self.conv_dro_list['conv_feed_dro'].grab_focus()


    def on_conv_feed_dro_activate(self, widget, data=None):
        (valid, feed, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_medium_format % feed)

        # NOTE!  The actual child object id="" attribute from the glade file is used to
        # uniquely identify each notebook page and to figure out which is the current page.
        # Do NOT add any text label comparisons.
        active_child_id = self.get_current_conv_notebook_page_id()

        if 'conv_drill_tap_fixed' == active_child_id:
            if self.conv_drill_tap == 'tap':
                # calculate related RPM DRO based on pitch
                # feed is okay so, check if either pitch or tpu are valid, if so calculate the rest of the DROs
                (valid, pitch, error_msg) = self.conversational.validate_param(self.tap_dro_list['tap_pitch_dro'])
                if not valid:  # no pitch, so check for tpu
                    (valid, tpu, error_msg) = self.conversational.validate_param(self.tap_dro_list['tap_tpu_dro'])
                    if not valid:
                        self.tap_dro_list['tap_pitch_dro'].grab_focus()
                    else:  # tpu okay
                        pitch = 1 / tpu
                        self.tap_dro_list["tap_pitch_dro"].set_text(self.dro_long_format % pitch)
                        (valid, pitch, error_msg) = self.conversational.validate_param(self.tap_dro_list['tap_pitch_dro'])
                        rpm = feed / pitch
                        self.conv_dro_list['conv_rpm_dro'].set_text(self.dro_short_format % rpm)

                else:  # pitch is okay
                    tpu = 1 / pitch
                    self.tap_dro_list["tap_tpu_dro"].set_text(self.dro_medium_format % tpu)
                    (valid, tpu, error_msg) = self.conversational.validate_param(self.tap_dro_list['tap_tpu_dro'])
                    rpm = feed / pitch
                    self.conv_dro_list['conv_rpm_dro'].set_text(self.dro_short_format % rpm)
                    self.conv_dro_list['conv_z_clear_dro'].grab_focus()

                dwell = float(self.tap_dro_list['tap_dwell_dro'].get_text())
                pitch = float(self.tap_dro_list['tap_pitch_dro'].get_text())
                # half_dwell_travel = dwell * rpm * min/60s * pitch * 1/2
                half_dwell_travel = (dwell * rpm * pitch) / 120
                self.tap_labels['dwell_travel_calc'].modify_font(self.drill_calc_font)
                self.tap_labels['dwell_travel_calc'].set_markup('<span foreground="white">%s</span>' % self.dro_dwell_format % half_dwell_travel)
            else: #'drill'
                try:  # calculate related Z feed DRO
                    pitch = float(self.tap_dro_list['tap_pitch_dro'].get_text())
                    rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
                    z_feed = pitch * rpm
                    tap_z_feed = self.dro_medium_format % z_feed
                    if tap_z_feed != self.current_normal_z_feed_rate:
                        self.conv_dro_list['conv_z_feed_dro'].set_text(self.current_normal_z_feed_rate)
                    self.update_chip_load_hint('conv_drill_tap_fixed')
                except:
                    pass

        elif 'conv_thread_mill_fixed' == active_child_id or 'conv_engrave_fixed' == active_child_id:
            self.conv_dro_list['conv_z_clear_dro'].grab_focus()
        else:
            self.update_chip_load_hint()
            self.conv_dro_list['conv_z_feed_dro'].grab_focus()


    def on_conv_z_feed_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_medium_format % value)
        self.update_chip_load_hint('conv_drill_tap_fixed')
        self.conv_dro_list['conv_z_clear_dro'].grab_focus()
        self.current_normal_z_feed_rate = self.conv_dro_list['conv_z_feed_dro'].get_text()


    def on_conv_z_clear_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)

        # NOTE!  The actual child object id="" attribute from the glade file is used to
        # uniquely identify each notebook page and to figure out which is the current page.
        # Do NOT add any text label comparisons.
        active_child_id = self.get_current_conv_notebook_page_id()

        if 'conv_face_fixed' == active_child_id:
            self.face_dro_list['face_x_start_dro'].grab_focus()
        elif 'conv_profile_fixed' == active_child_id:
            if self.conv_profile_rect_circ == 'rect':
                self.profile_dro_list['profile_x_prfl_start_dro'].grab_focus()
            else:
                self.profile_dro_list['profile_circ_x_start_dro'].grab_focus()
        elif 'conv_pocket_fixed' == active_child_id:
            if self.conv_pocket_rect_circ == 'rect':
                self.pocket_rect_dro_list['pocket_rect_x_start_dro'].grab_focus()
            else:  # self.conv_pocket_rect_circ == 'circ':
                self.pocket_circ_dro_list['pocket_circ_diameter_dro'].grab_focus()
        elif 'conv_drill_tap_fixed' == active_child_id:
            if self.conv_drill_tap == 'drill':
                self.drill_dro_list['drill_z_start_dro'].grab_focus()
            else:  # self.conv_drill_tap == 'tap'
                self.tap_dro_list['tap_z_end_dro'].grab_focus()
        elif 'conv_thread_mill_fixed' == active_child_id:
            if self.conv_thread_mill_ext_int == 'internal':
                self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'].grab_focus()
            else:  # self.conv_thread_mill_ext_int == 'external'
                self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'].grab_focus()
        elif 'conv_engrave_fixed' == active_child_id:
            self.engrave_dro_list['engrave_text_dro'].grab_focus()
        elif 'conv_dxf_fixed' == active_child_id:
            self.dxf_panel.dro_list['dxf_z_start_mill_depth_dro'].grab_focus()


    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Face DRO handlers
    # -------------------------------------------------------------------------------------------------

    def on_conversational_face_switch_page(self):
        return

    def face_spirial_rect_to_str(self):
        return 'Rectangular' if self.conv_face_spiral_rect == 'rect' else 'Spiral'

    def on_face_spiral_rect_set_state(self):
        # in this case nothing chnages accept style of cutting
        if not self.in_JA_edit_mode:
            self.save_title_dro()
        if self.conv_face_spiral_rect == 'spiral':
            self.set_image('face_spiral_rect_btn_image', 'face_spiral_rect_rect_highlight.png')
            self.set_image('conv_face_main_image', 'mill_conv_face_rect_main.svg')
        else:
            self.set_image('face_spiral_rect_btn_image', 'face_spiral_rect_spiral_highlight.png')
            self.set_image('conv_face_main_image', 'mill_conv_face_main.svg')

        self.face_dro_list['face_x_start_dro'].grab_focus()
        self.conv_face_spiral_rect = 'spiral' if self.conv_face_spiral_rect == 'rect' else 'rect'
        if not self.in_JA_edit_mode:
            self.load_title_dro()

    def on_face_spiral_rect_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.on_face_spiral_rect_set_state()


    def on_face_x_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_x_end_dro'].grab_focus()


    def on_face_x_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_y_start_dro'].grab_focus()


    def on_face_y_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_y_end_dro'].grab_focus()


    def on_face_y_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_z_start_dro'].grab_focus()


    def on_face_z_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_z_end_dro'].grab_focus()


    def on_face_z_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.face_dro_list['face_z_doc_dro'].grab_focus()


    def on_face_z_doc_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.face_dro_list['face_stepover_dro'].grab_focus()


    def on_face_stepover_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.face_dro_list['face_x_start_dro'].grab_focus()


    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Profile DRO handlers
    # -------------------------------------------------------------------------------------------------
    def on_profile_rect_circ_set_state(self):
        self.save_title_dro()
        if self.conv_profile_rect_circ == 'rect':
            self.set_image('profile_rect_circ_btn_image', 'pocket_rect_circ_circ_highlight.jpg')
            self.set_image('conv_profile_main_image', 'mill_conv_profile_circ.1.svg')
            rect_state = False
            circ_state = True
            self.conv_profile_rect_circ = 'circ'
            if not len(self.profile_dro_list['profile_circ_z_doc_dro'].get_text()):
                self.profile_dro_list['profile_circ_z_doc_dro'].set_text(self.profile_dro_list['profile_z_doc_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_z_end_dro'].get_text()):
                self.profile_dro_list['profile_circ_z_end_dro'].set_text(self.profile_dro_list['profile_z_end_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_z_start_dro'].get_text()):
                self.profile_dro_list['profile_circ_z_start_dro'].set_text(self.profile_dro_list['profile_z_start_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_stepover_dro'].get_text()):
                self.profile_dro_list['profile_circ_stepover_dro'].set_text(self.profile_dro_list['profile_stepover_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_x_start_dro'].get_text()):
                self.profile_dro_list['profile_circ_x_start_dro'].set_text(self.profile_dro_list['profile_x_start_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_x_end_dro'].get_text()):
                self.profile_dro_list['profile_circ_x_end_dro'].set_text(self.profile_dro_list['profile_x_end_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_y_start_dro'].get_text()):
                self.profile_dro_list['profile_circ_y_start_dro'].set_text(self.profile_dro_list['profile_y_start_dro'].get_text())
            if not len(self.profile_dro_list['profile_circ_y_end_dro'].get_text()):
                self.profile_dro_list['profile_circ_y_end_dro'].set_text(self.profile_dro_list['profile_y_end_dro'].get_text())
            self.profile_dro_list['profile_circ_x_start_dro'].grab_focus()
        else:
            self.set_image('profile_rect_circ_btn_image', 'pocket_rect_circ_rect_highlight.jpg')
            self.set_image('conv_profile_main_image', 'mill_conv_profile_main.svg')
            rect_state = True
            circ_state = False
            self.conv_profile_rect_circ = 'rect'
            self.profile_dro_list['profile_x_prfl_start_dro'].grab_focus()

        # set rect DROs
        self.profile_dro_list['profile_z_doc_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_z_end_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_z_start_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_stepover_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_x_start_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_x_end_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_y_start_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_y_end_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_x_prfl_start_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_x_prfl_end_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_y_prfl_start_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_y_prfl_end_dro'].set_visible(rect_state)
        self.profile_dro_list['profile_radius_dro'].set_visible(rect_state)
        # set circ DROs
        self.profile_dro_list['profile_circ_z_doc_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_z_end_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_z_start_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_stepover_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_x_start_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_x_end_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_y_start_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_y_end_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_circ_diameter_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_x_center_dro'].set_visible(circ_state)
        self.profile_dro_list['profile_y_center_dro'].set_visible(circ_state)

        # turn rect labels(text) OFF
        self.profile_x_prfl_start_label.set_visible(rect_state)
        self.profile_x_prfl_end_label.set_visible(rect_state)
        self.profile_y_prfl_start_label.set_visible(rect_state)
        self.profile_y_prfl_end_label.set_visible(rect_state)
        self.profile_radius_label.set_visible(rect_state)

        # turn circ labels(text) ON
        self.profile_circ_diameter_label.set_visible(circ_state)
        self.profile_x_center_label.set_visible(circ_state)
        self.profile_y_center_label.set_visible(circ_state)
        self.load_title_dro()
        self._update_stepover_hints(page_id='conv_profile_fixed')

    def on_profile_rect_circ_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # toggle button state between rect and circ
        self.on_profile_rect_circ_set_state()

    def on_profile_radius_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_y_start_dro'].grab_focus()


    def on_profile_z_doc_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.profile_dro_list['profile_z_start_dro'].grab_focus()


    def on_profile_x_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_x_end_dro'].grab_focus()


    def on_profile_x_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_x_prfl_start_dro'].grab_focus()


    def on_profile_y_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_y_prfl_start_dro'].grab_focus()


    def on_profile_y_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        goto_dro = 'profile_stepover_dro' if self.conv_profile_rect_circ == 'rect' else 'profile_circ_diameter_dro'
        self.profile_dro_list[goto_dro].grab_focus()


    def on_profile_stepover_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.profile_dro_list['profile_z_doc_dro'].grab_focus()


    def on_profile_z_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_z_end_dro'].grab_focus()


    def on_profile_z_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_x_start_dro'].grab_focus()


    def on_profile_x_prfl_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_x_prfl_end_dro'].grab_focus()


    def on_profile_x_prfl_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_radius_dro'].grab_focus()


    def on_profile_y_prfl_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_y_prfl_end_dro'].grab_focus()


    def on_profile_y_prfl_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_y_end_dro'].grab_focus()


    # .. circ ...........
    def on_profile_circ_stepover_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.profile_dro_list['profile_circ_z_doc_dro'].grab_focus()


    def on_profile_circ_z_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_z_end_dro'].grab_focus()


    def on_profile_circ_z_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_x_start_dro'].grab_focus()


    def on_profile_circ_z_doc_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.profile_dro_list['profile_circ_z_start_dro'].grab_focus()


    def on_profile_circ_x_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_x_end_dro'].grab_focus()


    def on_profile_circ_x_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_y_start_dro'].grab_focus()


    def on_profile_circ_y_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_y_end_dro'].grab_focus()


    def on_profile_circ_y_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_diameter_dro'].grab_focus()


    def on_profile_circ_diameter_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_x_center_dro'].grab_focus()


    def on_profile_x_center_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_y_center_dro'].grab_focus()


    def on_profile_y_center_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.profile_dro_list['profile_circ_stepover_dro'].grab_focus()

    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Pocket DRO handlers
    # -------------------------------------------------------------------------------------------------
    def on_pocket_rect_circ_set_state(self):
        self.save_title_dro()
        if self.conv_pocket_rect_circ == 'rect':
            self.set_image('pocket_rect_circ_btn_image', 'pocket_rect_circ_circ_highlight.jpg')
            self.set_image('conv_pocket_main_image', 'mill_conv_pocket_circ_main.svg')
            rect_state = False
            circ_state = True
            self.conv_pocket_rect_circ = 'circ'
        else:
            self.set_image('pocket_rect_circ_btn_image', 'pocket_rect_circ_rect_highlight.jpg')
            self.set_image('conv_pocket_main_image', 'mill_conv_pocket_rect_main.svg')
            rect_state = True
            circ_state = False
            self.conv_pocket_rect_circ = 'rect'

        # set rect DROs
        self.pocket_rect_dro_list['pocket_rect_x_start_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_x_end_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_y_start_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_y_end_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_z_start_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_z_end_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_z_doc_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_stepover_dro'].set_visible(rect_state)
        self.pocket_rect_dro_list['pocket_rect_corner_radius_dro'].set_visible(rect_state)

        # set circ DROs
        self.pocket_circ_dro_list['pocket_circ_z_end_dro'].set_visible(circ_state)
        self.pocket_circ_dro_list['pocket_circ_z_start_dro'].set_visible(circ_state)
        self.pocket_circ_dro_list['pocket_circ_z_doc_dro'].set_visible(circ_state)
        self.pocket_circ_dro_list['pocket_circ_stepover_dro'].set_visible(circ_state)
        self.pocket_circ_dro_list['pocket_circ_diameter_dro'].set_visible(circ_state)

        # turn rect labels(text) OFF
        self.pocket_rect_x_start_label.set_visible(rect_state)
        self.pocket_rect_x_end_label.set_visible(rect_state)
        self.pocket_rect_y_start_label.set_visible(rect_state)
        self.pocket_rect_y_end_label.set_visible(rect_state)
        self.pocket_rect_corner_radius_label.set_visible(rect_state)

        # turn circ labels(text) ON
        self.pocket_circ_x_center_label.set_visible(circ_state)
        self.pocket_circ_y_center_label.set_visible(circ_state)
        self.pocket_circ_diameter_label.set_visible(circ_state)

        if self.conv_pocket_rect_circ == 'rect':
            self.pocket_rect_dro_list['pocket_rect_x_start_dro'].grab_focus()
        else:
            self.pocket_circ_dro_list['pocket_circ_diameter_dro'].grab_focus()
        self.load_title_dro()
        self._update_stepover_hints(page_id='conv_pocket_fixed')

        ## Some conv_DROs may also be set with on_conversational_notebook_switch_page

    def on_pocket_rect_circ_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.on_pocket_rect_circ_set_state()


    # *****  Rectangular DRO handlers  *****
    def on_pocket_rect_x_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_x_end_dro'].grab_focus()


    def on_pocket_rect_x_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_corner_radius_dro'].grab_focus()


    def on_pocket_rect_corner_radius_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_y_start_dro'].grab_focus()


    def on_pocket_rect_y_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_y_end_dro'].grab_focus()


    def on_pocket_rect_y_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_z_start_dro'].grab_focus()


    def on_pocket_rect_z_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_z_end_dro'].grab_focus()


    def on_pocket_rect_z_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_rect_dro_list['pocket_rect_z_doc_dro'].grab_focus()


    def on_pocket_rect_z_doc_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.pocket_rect_dro_list['pocket_rect_stepover_dro'].grab_focus()


    def on_pocket_rect_stepover_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.pocket_rect_dro_list['pocket_rect_x_start_dro'].grab_focus()


    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Pocket-Circular DRO handlers
    # -------------------------------------------------------------------------------------------------

    def on_pocket_circ_diameter_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_circ_dro_list['pocket_circ_z_start_dro'].grab_focus()


    def on_pocket_circ_z_start_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_circ_dro_list['pocket_circ_z_end_dro'].grab_focus()


    def on_pocket_circ_z_end_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text(self.dro_long_format % value)
        self.pocket_circ_dro_list['pocket_circ_z_doc_dro'].grab_focus()


    def on_pocket_circ_z_doc_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.pocket_circ_dro_list['pocket_circ_stepover_dro'].grab_focus()


    def on_pocket_circ_stepover_dro_activate(self, widget, data=None):
        (valid, value, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % value)
        self.exec_modify_callback(widget)
        self.pocket_circ_dro_list['pocket_circ_diameter_dro'].grab_focus()


    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Drill-Tap DRO handlers
    # -------------------------------------------------------------------------------------------------

    def calc_tap_z_feed_rate(self):
        z_tap_feed_str = self.current_normal_z_feed_rate
        try:  # calculate related Z feed DRO
            pitch = float(self.tap_dro_list['tap_pitch_dro'].get_text())
            rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
            z_feed = pitch * rpm
            z_tap_feed_str = self.dro_medium_format % z_feed
        except:
            z_tap_feed_str = self.current_normal_z_feed_rate
        return z_tap_feed_str


    def update_drill_through_hole_hint(self):
        self._update_drill_through_hole_hint_label(self.conv_dro_list['conv_tool_number_dro'].get_text(),
                                                   self.drill_dro_list['drill_z_end_dro'].get_text(),
                                                   self.drill_through_hole_hint_label)

    def _get_current_dro(self, dro_key, page_id=None):
        if not page_id: page_id = self.get_current_conv_notebook_page_id()
        dros = self.get_current_dro_info(page_id)
        if dros is None: return None
        return dros[dro_key] if dro_key in dros else None if page_id != 'conv_drill_tap_fixed' else 'drill'

    def update_chip_load_hint(self, typ=None):
        if isinstance(typ,str) or typ is None: typ = self._get_current_dro('stepover', typ)
        # Note: 'current_chipload' bases returns values on whatever values are in the feed DROs
        # if metric the return values will be metric.
        flutes, cl, scl = self.fs_mgr.current_chipload(typ)
        metric,m_vals = self.conversational.is_metric('as_dictionary')
        self.stepover_chip_load.set_visible(scl is not None)
        markup_str = '<span font_desc="Roboto Condensed 9" foreground="white">(Flutes: {0:s}   Chip load per tooth: {1:s})</span>'
        if isinstance(cl,float): cl = (self.dro_long_format)%cl
        self.chip_load_hint.set_markup(markup_str.format(str(flutes),cl))
        if scl is not None:
            col = 'white'
            try:
                _scl_limit = float(scl)/m_vals['ttable_conv']
                if _scl_limit<0.0006: col = 'yellow'
                if _scl_limit<0.00045: col = 'red'
            except:
                pass
            markup_str = '<span font_desc="Roboto Condensed 9" foreground="white">(Stepover adjusted chip load: <span foreground="{0:s}">{1:s}</span>)</span>'
            if isinstance(scl,float): scl = (self.dro_long_format) % (scl)
            self.stepover_chip_load.set_markup(markup_str.format(col,scl))
        self.__update_sfm_mrr_hint(flutes, scl if scl and scl != FSBase.NA else cl)

    def __update_sfm_mrr_hint(self, flutes, cl):
        # JIT init 'self.sfm_mrr_hint'
        if not self.sfm_mrr_hint: self.sfm_mrr_hint = self.builder.get_object('sfm_mrr_hint')
        sfm = mrr = FSBase.NA
        metric,m_vals = self.conversational.is_metric('as_dictionary')
        surface_speed_str = 'SMM' if metric else 'SFM'
        markup_str = '<span font_desc="Roboto Condensed 9" foreground="white" >({}: {}    --     MRR: {} {})</span>'
        valid, tool_number = cparse.is_number_or_expression(self.conv_dro_list['conv_tool_number_dro'])
        # get the SFM data together...
        if not valid: tool_number = None
        valid, rpm = cparse.is_number_or_expression(self.conv_dro_list['conv_rpm_dro'])
        if not valid: rpm = None
        if tool_number and rpm:
            #Note: diam returns in 'inch' values from lcnc
            diam = self.get_tool_diameter(int(tool_number))
            diam *= m_vals['ttable_conv']
            tool_radius = diam/2.0
            surface_speed = rpm*diam*math.pi
            surface_speed = round(surface_speed/1000.0,1) if metric else int(round(surface_speed/12.0,0))
            sfm = str(surface_speed)
            feed = float(cl)*flutes*rpm if cl != FSBase.NA else 0.0
            typ = self._get_current_dro('stepover')
            stepover = diam
            if isinstance(typ,gtk.Entry):
                valid, stepover = cparse.is_number_or_expression(typ)
                if not valid: stepover = 0.0
            doc = 1.0
            typ = self._get_current_dro('r_doc')
            if isinstance(typ,gtk.Entry):
                valid, doc = cparse.is_number_or_expression(typ)
                if not valid: doc = 0.0
            tool_type = self.get_tool_type(int(tool_number))
            _mrr = feed*math.pi*tool_radius**2 if typ == 'drill' else feed*stepover*math.fabs(doc)
            tool_type = self.get_tool_type(int(tool_number))
            if tool_type in ('spot','chamfer','engraver'): _mrr /= 2.0
            # NOTE: cl (which determines 'feed') will be in mm/min. so _mrr needs to be
            # divided by 10**3 to get to standard cu-cm/min.
            _mrr *= .001 if metric else 1.0
            if stepover and doc and diam>0.0: mrr = '{:.2f}'.format(_mrr)
        mrr_units = '' if mrr == FSBase.NA else m_vals['mrr_units']
        self.sfm_mrr_hint.set_markup(markup_str.format(surface_speed_str,sfm,mrr,mrr_units))

    def show_hide_dros(self, show=True):
        for dro in self.drill_dro_list.values():
            dro.set_visible(show)
        for label in self.drill_labels.values():
            label.set_visible(show)
        for item in self.drill_tap_extras.values():
            item.set_visible(show)

    def on_conv_drill_tap_pattern_notebook_switch_page(self, notebook, page, page_num):
        if page_num == 0: #pattern
            self.drill_pattern_notebook_page = 'pattern'
        elif page_num == 1: #circular
            self.drill_pattern_notebook_page = 'circular'
        return

        # toggle button state between drill and tap
    def on_drill_tap_set_state(self):
        z_tap_feed_str = self.calc_tap_z_feed_rate()
        self.save_title_dro()
        if self.conv_drill_tap == 'drill':
            self.set_image('drill_tap_btn_image', 'drill_tap_tap_highlight.jpg')
            self.set_image('drill_tap_main_image', 'mill_drill_tap_main.png')
            self.set_image('drill_tap_detail_image', 'mill_tap_detail.png')
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(False)
            self.checkbutton_list['tap_2x_checkbutton'].set_visible(True)
            self.tap_hsep.set_visible(True)
            self.drill_through_hole_hint_label.set_visible(False)
            show_drill = False
            show_tap = True
            self.conv_dro_list['conv_z_feed_dro'].set_text(z_tap_feed_str)
            self.conv_drill_tap = 'tap'

        else:
            self.set_image('drill_tap_btn_image', 'drill_tap_drill_highlight.jpg')
            self.set_image('drill_tap_main_image', 'mill_drill_main.png')
            self.set_image('drill_tap_detail_image', 'mill_drill_peck_detail.png')
            self.conv_dro_list['conv_z_feed_dro'].set_sensitive(True)
            self.checkbutton_list['tap_2x_checkbutton'].set_visible(False)
            self.tap_hsep.set_visible(False)
            self.drill_through_hole_hint_label.set_visible(True)
            show_drill = True
            show_tap = False
            if z_tap_feed_str != self.current_normal_z_feed_rate:
                self.conv_dro_list['conv_z_feed_dro'].set_text(self.current_normal_z_feed_rate)
            self.conv_drill_tap = 'drill'

        # Update visibility of drill labels / DRO's
        for label in self.drill_dro_list.values():
            label.set_visible(show_drill)
        for label in self.drill_labels.values():
            label.set_visible(show_drill)
        # Update visibility of tap labels / DRO's
        for label in self.tap_labels.values():
            label.set_visible(show_tap)
        for label in self.tap_dro_list.values():
            label.set_visible(show_tap)
        if self.conv_drill_tap == 'drill':
            self.drill_dro_list['drill_peck_dro'].grab_focus()
        else:
            self.tap_dro_list['tap_pitch_dro'].grab_focus()
        self.load_title_dro()


    def on_drill_tap_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        # toggle button state between drill and tap
        self.on_drill_tap_set_state()

    def on_drill_z_start_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.drill_dro_list['drill_z_end_dro'].grab_focus()


    def on_drill_peck_dro_activate(self, widget, data=None):
        (valid, peck, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return

        try:
            dwell = float(self.drill_dro_list['drill_dwell_dro'].get_text())
            if dwell > 0 and peck > 0:
                dwell = 0.0
                self.drill_dro_list['drill_dwell_dro'].set_text('%s' % self.dro_dwell_format % dwell)
                try:  # if RPM and Dwell are okay, do calc
                    rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
                    #dwell_revs = rpm * min/sec * dwell
                    dwell_revs = rpm * dwell / 60
                    self.drill_labels['dwell_revs_calc'].modify_font(self.drill_calc_font)
                    self.drill_labels['dwell_revs_calc'].set_markup('<span foreground="white">%s</span>' % self.dro_medium_format % dwell_revs)
                except:  # clear any value in Dwell Revs label
                    self.drill_labels['dwell_revs_calc'].set_text('')

        except:
            pass

        FSBase.dro_on_activate(widget, self.dro_long_format % peck)
        self.drill_dro_list['drill_z_start_dro'].grab_focus()


    def on_drill_z_end_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.update_drill_through_hole_hint()
        if self.drill_pattern_notebook_page == 'pattern':
            self.drill_dro_list['drill_spot_tool_number_dro'].grab_focus()
        else:
            self.drill_circular_dro_list['drill_tap_pattern_circular_holes_dro'].grab_focus()


    def on_drill_dwell_dro_activate(self, widget, data=None):
        (valid, dwell, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return

        try:
            peck = float(self.drill_dro_list['drill_peck_dro'].get_text())
            if dwell > 0 and peck > 0:
                peck = 0.0
                self.drill_dro_list['drill_peck_dro'].set_text('%s' % self.dro_long_format % peck)
        except:
            pass

        widget.set_text('%s' % self.dro_dwell_format % dwell)

        try:  # if RPM and Dwell are okay, do calc
            rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
            #dwell_revs = rpm * min/sec * dwell
            dwell_revs = rpm * dwell / 60
            self.drill_labels['dwell_revs_calc'].modify_font(self.drill_calc_font)
            self.drill_labels['dwell_revs_calc'].set_markup('<span foreground="white">%s</span>' % self.dro_medium_format % dwell_revs)
        except:  # clear any value in Dwell Revs label
            self.drill_labels['dwell_revs_calc'].set_text('')

        self.drill_dro_list['drill_peck_dro'].grab_focus()


    def on_drill_spot_tool_number_dro_activate(self, widget, data=None):
        # empty dro is valid here...
        text = widget.get_text()
        if len(text) > 0:
            (valid, number, error_msg) = self.conversational.validate_param(widget)
            if not valid:
                self.error_handler.write('Conversational Drilling entry error - ' + error_msg, ALARM_LEVEL_LOW)
                return
            text = str(number) if number is not None else ''
            widget.set_text(text)
        else:
            cparse.clr_alarm(self.drill_dro_list['drill_spot_tool_doc_dro'])
        self.drill_dro_list['drill_spot_tool_doc_dro'].grab_focus()


    def on_drill_spot_tool_doc_dro_activate(self, widget, data=None):
        spot_dro = self.drill_dro_list['drill_spot_tool_number_dro']
        text = widget.get_text()
        spot_text = spot_dro.get_text()
        if len(spot_text) == 0 and len(text) == 0:
            cparse.clr_alarm(widget)
            self.drill_dro_list['drill_peck_dro'].grab_focus()
            return
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        if number is None:
            widget.set_text('')
        else:
            FSBase.dro_on_activate(widget, self.dro_long_format % number)
        self.drill_dro_list['drill_peck_dro'].grab_focus()


    def on_drill_tap_pattern_circular_holes_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        text = str(number) if number is not None else ''
        widget.set_text(text)
        self.on_complete_circle_data()
        self.drill_circular_dro_list['drill_tap_pattern_circular_start_angle_dro'].grab_focus()


    def on_drill_tap_pattern_circular_start_angle_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.on_complete_circle_data()
        self.drill_circular_dro_list['drill_tap_pattern_circular_diameter_dro'].grab_focus()


    def on_drill_tap_pattern_circular_diameter_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.on_complete_circle_data()
        self.drill_circular_dro_list['drill_tap_pattern_circular_center_x_dro'].grab_focus()


    def on_drill_tap_pattern_circular_center_x_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.on_complete_circle_data()
        self.drill_circular_dro_list['drill_tap_pattern_circular_center_y_dro'].grab_focus()


    def on_drill_tap_pattern_circular_center_y_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.on_complete_circle_data()
#       self.drill_circular_dro_list['drill_tap_pattern_circular_holes_dro'].grab_focus()
        self.drill_dro_list['drill_spot_tool_number_dro'].grab_focus()


    def on_complete_circle_data(self):
        (valid, holes) = cparse.is_number_or_expression(self.drill_circular_dro_list['drill_tap_pattern_circular_holes_dro'])
        if valid == False or holes <= 0:
            return

        (valid, angle) = cparse.is_number_or_expression(self.drill_circular_dro_list['drill_tap_pattern_circular_start_angle_dro'])
        if valid == False or -90 > angle > 90:
            return

        (valid, diameter) = cparse.is_number_or_expression(self.drill_circular_dro_list['drill_tap_pattern_circular_diameter_dro'])
        if valid == False or diameter <= 0:
            return

        (valid, center_x) = cparse.is_number_or_expression(self.drill_circular_dro_list['drill_tap_pattern_circular_center_x_dro'])
        if valid == False:
            return

        (valid, center_y) = cparse.is_number_or_expression(self.drill_circular_dro_list['drill_tap_pattern_circular_center_y_dro'])
        if valid == False:
            return

        old_drill_limit = self.DRILL_TABLE_ROWS
        self.DRILL_TABLE_ROWS = DRILL_TABLE_BASIC_SIZE if int(holes) <= DRILL_TABLE_BASIC_SIZE else int(holes)

        # generate the 'new drill liststore'
        radius = float(diameter / float(2))
        hole_degrees = float(360 / float(holes))
        hole_number = 1
        for row in range(self.DRILL_TABLE_ROWS):
            if hole_number <= int(holes):
                x_value = center_x + (radius * math.cos(math.radians(angle)))
                y_value = center_y + (radius * math.sin(math.radians(angle)))
                if row < old_drill_limit:
                    self.drill_liststore[row][1] = '%.4f' % x_value
                    self.drill_liststore[row][2] = '%.4f' % y_value
                else:
                    self.drill_liststore.append([hole_number, '%.4f' % x_value, '%.4f' % y_value])
                angle += hole_degrees
            else:
                self.drill_liststore[row][0] = (hole_number)
                self.drill_liststore[row][1] = ''
                self.drill_liststore[row][2] = ''
            hole_number += 1

        # reduce the size of liststore back to the basic size if larger size no longer needed
        if old_drill_limit > self.DRILL_TABLE_ROWS:
            new_upper_limit = DRILL_TABLE_BASIC_SIZE if int(holes) <= DRILL_TABLE_BASIC_SIZE else int(holes)
            self.error_handler.write('old_limit: %d new_limit: %d' % (old_drill_limit, new_upper_limit), ALARM_LEVEL_DEBUG)
            for row in range(new_upper_limit, old_drill_limit):
                iter_index = self.drill_liststore.iter_n_children(None)
                iter = self.drill_liststore.iter_nth_child(None, iter_index - 1)
                self.drill_liststore.remove(iter)


    # *****  Drill Table Handlers  *****
    def drill_liststore_to_list(self):
        out_list = []
        for row in self.drill_liststore:
            out_list.append((row[0],row[1],row[2]))
        return out_list

    def list_to_drill_liststore(self, in_list):
        if in_list is None:
            return
        self.drill_liststore.clear()
        for item in in_list:
            self.drill_liststore.append([item[0],item[1],item[2]])

    def drill_table_update_focus(self,row,column,start_editing):
        self.error_handler.write('drill_table_update_focus - row: %d, column: %s, start editing %s' % (row,column.get_title(),'%s') % 'True' if start_editing else 'False', ALARM_LEVEL_DEBUG)
        self.drill_treeview.set_cursor(row, column, start_editing)
        if start_editing:
            self.dt_scroll_adjust(row)

    def on_drill_x_column_keypress(self,widget,ev,row):
        self.error_handler.write('in on_drill_x_column_keypress.  keypress = %s' % gtk.gdk.keyval_name(ev.keyval), ALARM_LEVEL_DEBUG)
        if ev.keyval in (gtk.keysyms.Return, gtk.keysyms.KP_Enter):
            glib.idle_add(self.drill_table_update_focus,row, self.drill_y_column,True)
            return False
        if ev.keyval == gtk.keysyms.Escape:
            self.error_handler.write("escape hit", ALARM_LEVEL_DEBUG)
            glib.idle_add(self.drill_table_update_focus,row, self.drill_x_column,False)
            return True

    def on_drill_y_column_keypress(self,widget,ev,row):
        self.error_handler.write('in on_drill_y_column_keypress.  keypress = %s' % gtk.gdk.keyval_name(ev.keyval), ALARM_LEVEL_DEBUG)
        if ev.keyval in (gtk.keysyms.Return, gtk.keysyms.KP_Enter):
            glib.idle_add(self.drill_table_update_focus,row, self.drill_x_column,True)
            return False
        if ev.keyval == gtk.keysyms.Escape:
            self.error_handler.write("escape hit", ALARM_LEVEL_DEBUG)
            target_row = 0 if row == 0 else row - 1
            glib.idle_add(self.drill_table_update_focus,target_row, self.drill_y_column,False)
            return True

    def on_drill_cell_edit_x_focus(self, widget, direction, target_row):
        self.error_handler.write('in on_drill_cell_edit_x_focus', ALARM_LEVEL_DEBUG)
        if self.settings.touchscreen_enabled:
            np = numpad.numpad_popup(self.window, widget, False, -324, -119)
            np.run()
            widget.masked = 0
            widget.select_region(0, 0)
            self.window.set_focus(None)


    def on_drill_cell_edit_y_focus(self, widget, direction, target_row):
        self.error_handler.write('in on_drill_cell_edit_y_focus', ALARM_LEVEL_DEBUG)
        if self.settings.touchscreen_enabled:
            np = numpad.numpad_popup(self.window, widget, False, -324, -119)
            np.run()
            widget.masked = 0
            widget.select_region(0, 0)
            self.window.set_focus(None)


    def on_drill_x_column_editing_started(self, xrenderer, editable, path, drill_font):
        self.error_handler.write("Editing *started* X column : on_drill_x_column_editing_started", ALARM_LEVEL_DEBUG)
        editable.modify_font(drill_font)
        target_row = 0 if path == '' else int(path)
        if self.settings.touchscreen_enabled:
            editable.connect("focus-in-event", self.on_drill_cell_edit_x_focus, target_row)
        editable.connect("key-press-event", self.on_drill_x_column_keypress, target_row)


    def on_drill_y_column_editing_started(self, yrenderer, editable, path, drill_font):
        self.error_handler.write("Editing *started* Y column : on_drill_y_column_editing_started", ALARM_LEVEL_DEBUG)
        editable.modify_font(drill_font)
        row = 0 if path == '' else int(path)
        target_row = None
        if row >= (self.DRILL_TABLE_ROWS - 1):
            target_row = (self.DRILL_TABLE_ROWS - 1)
        else:
            target_row = row + 1
        if self.settings.touchscreen_enabled:
            editable.connect("focus-in-event", self.on_drill_cell_edit_y_focus, target_row)
        editable.connect("key-press-event", self.on_drill_y_column_keypress, target_row)


    def on_drill_x_column_edited(self, cell, row, value, model):

        if value == '' or value == '??':
            model[row][1] = ""
            return
        try:
            valid, value = cparse.is_number_or_expression(value)
            if not valid: raise ValueError('validation failed')
        except ValueError:
            self.error_handler.write("Invalid position specified for drill table", ALARM_LEVEL_LOW)
            value = ''

        row = 0 if row == '' else int(row)
        model[row][1] = "%0.4f" % value if isinstance(value,float) else value


    def on_drill_y_column_edited(self, cell, row, value, model):
        # TODO - connect to mill_conversational.validate_param
        #valid, value, error_msg = mill_conversational.validate_param(value)
        #if not valid:
        #    self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
        #    return

        if value == '' or value == '??':
            model[row][2] = ""
            return
        try:
            valid, value = cparse.is_number_or_expression(value)
            if not valid: raise ValueError('validation failed')
        except ValueError:
            self.error_handler.write("Invalid position specified for drill table", ALARM_LEVEL_LOW)
            value = ''

        row = 0 if row == '' else int(row)

        model[row][2] = "%0.4f" % value if isinstance(value,float) else value


    def on_drill_tap_clear_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        self.drill_liststore.clear()

        for id_cnt  in range(1, self.DRILL_TABLE_ROWS + 1):
            self.drill_liststore.append([id_cnt, '', ''])

        adj = self.scrolled_window_drill_table.get_vadjustment()
        adj.set_value(0)

        self.drill_treeview.set_cursor(0, focus_column=self.drill_x_column, start_editing=True)


    def on_drill_tap_raise_in_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        selection = self.drill_treeview.get_selection()
        model, selected_iter = selection.get_selected()
        if selected_iter: #result could be None
            selected_row = model.get_path(selected_iter)[0]
            if selected_row > 0:
                target_iter = model.get_iter(selected_row - 1)
                model.move_before(selected_iter, target_iter)

                for i in range(self.DRILL_TABLE_ROWS):  # reset ID column numbers
                    model[i][0] = i + 1
            self.dt_scroll_adjust(selected_row - 1)


    def on_drill_tap_lower_in_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        selection = self.drill_treeview.get_selection()
        model, selected_iter = selection.get_selected()
        if selected_iter: #result could be None
            selected_row = model.get_path(selected_iter)[0]
            if selected_row < (self.DRILL_TABLE_ROWS - 1):
                target_iter = model.get_iter(selected_row + 1)
                model.move_after(selected_iter, target_iter)

                for i in range(self.DRILL_TABLE_ROWS):  # reset ID column numbers
                    model[i][0] = i + 1
            self.dt_scroll_adjust(selected_row + 1)


    def on_drill_tap_insert_row_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        selection = self.drill_treeview.get_selection()
        model, selected_iter = selection.get_selected()
        if selected_iter: #result could be None
            selected_row = model.get_path(selected_iter)[0]
            new_iter = model.insert_before(selected_iter,['','',''])
            last_iter = None
            while selected_iter:
                last_iter = selected_iter
                selected_iter = model.iter_next(selected_iter)
            if last_iter:
                model.remove(last_iter)

            for i in range(self.DRILL_TABLE_ROWS):  # reset ID column numbers
                model[i][0] = i + 1
            self.dt_scroll_adjust(selected_row)
            selection.select_iter(new_iter)


    def on_drill_tap_delete_row_table_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return

        selection = self.drill_treeview.get_selection()
        model, selected_iter = selection.get_selected()
        if selected_iter: #result could be None
            selected_row = model.get_path(selected_iter)[0]
            model.remove( selected_iter )
            # add an empty row at the end
            model.append(['', '', ''])

            for i in range(self.DRILL_TABLE_ROWS):  # reset ID column numbers
                model[i][0] = i + 1
            self.dt_scroll_adjust(selected_row)


    def dt_scroll_adjust(self, row):
        self.drill_treeview.scroll_to_cell(row)


    # *****  Tap DRO Handlers  *****
    def on_tap_z_start_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.tap_dro_list['tap_z_end_dro'].grab_focus()
        return

    def on_tap_z_end_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.tap_dro_list['tap_dwell_dro'].grab_focus()
        return

    def on_tap_dwell_dro_map(self, widget, data=None):
        text = widget.get_text()
        if text == '':
            widget.set_text('0.00')
        try:
            if float(text) == 0:
                self.tap_labels['dwell_travel_calc'].modify_font(self.drill_calc_font)
                self.tap_labels['dwell_travel_calc'].set_markup('<span foreground="white">0.00</span>')
        except:
            pass


    def on_tap_dwell_dro_activate(self, widget, data=None):
        (valid, dwell, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_dwell_format % dwell)

        try:  # if RPM and Dwell are okay, do calc
            rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
            pitch = float(self.tap_dro_list['tap_pitch_dro'].get_text())
            # half_dwell_travel = dwell * rpm * min/60s * pitch * 1/2
            half_dwell_travel = (dwell * rpm * pitch) / 120
            self.tap_labels['dwell_travel_calc'].modify_font(self.drill_calc_font)
            self.tap_labels['dwell_travel_calc'].set_markup('<span foreground="white">%s</span>' % self.dro_dwell_format % half_dwell_travel)
        except:  # clear any value in Dwell Revs label
            self.tap_labels['dwell_travel_calc'].set_text('')

        self.tap_dro_list['tap_pitch_dro'].grab_focus()


    def on_tap_pitch_dro_activate(self, widget, data=None):
        (valid, pitch, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % pitch)

        tpu = 1 / pitch
        self.tap_dro_list["tap_tpu_dro"].set_text(self.dro_medium_format % tpu)

        try:
            rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
            feed = pitch * rpm
            self.conv_dro_list['conv_z_feed_dro'].set_text(self.dro_medium_format % feed)

        except:
            self.conv_dro_list['conv_z_feed_dro'].set_text('')

        self.tap_dro_list['tap_tpu_dro'].grab_focus()


    def on_tap_tpu_dro_activate(self, widget, data=None):
        (valid, tpu, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_medium_format % tpu)

        pitch = 1 / tpu
        self.tap_dro_list["tap_pitch_dro"].set_text(self.dro_long_format % pitch)

        try:
            rpm = float(self.conv_dro_list['conv_rpm_dro'].get_text())
            feed = pitch * rpm
            self.conv_dro_list['conv_z_feed_dro'].set_text(self.dro_medium_format % feed)

        except:
            self.conv_dro_list['conv_z_feed_dro'].set_text('')

        self.tap_dro_list['tap_z_end_dro'].grab_focus()


    def on_tap_2x_checkbutton_toggled(self, widget, data=None):
        self.tap_2x_enabled = widget.get_active()

    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Thread Mill DRO handlers
    # -------------------------------------------------------------------------------------------------

    def on_thread_mill_ext_int_set_state(self):
        self.save_title_dro()
        if self.conv_thread_mill_ext_int == 'external':
            self.set_image('thread_mill_ext_int_btn_image', 'thread_int_button.jpg')
            self.image_list['thread_mill_main_image'].set_from_file(os.path.join(GLADE_DIR, 'mill_thread_mill_int_main.svg'))
            self.image_list['thread_mill_detail_image'].set_from_file(os.path.join(GLADE_DIR, 'mill_thread_mill_int_detail.svg'))

            # turn External DROs OFF
            ##self.thread_mill_ext_dro_list['thread_mill_ext_x_dro'].set_visible(False)
            ##self.thread_mill_ext_dro_list['thread_mill_ext_y_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_z_end_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_passes_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_pitch_dro'].set_visible(False)
            self.thread_mill_ext_dro_list['thread_mill_ext_tpu_dro'].set_visible(False)

            # turn Internal DROs ON
            ##self.thread_mill_int_dro_list['thread_mill_int_x_dro'].set_visible(True)
            ##self.thread_mill_int_dro_list['thread_mill_int_y_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_z_end_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_doc_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_passes_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_pitch_dro'].set_visible(True)
            self.thread_mill_int_dro_list['thread_mill_int_tpu_dro'].set_visible(True)
            self.thread_mill_int_minimal_retract_check.set_visible(True)

            ## these conv_DROs are also changed in on_conversational_notebook_switch_page
            #self.conv_dro_list['conv_rough_sfm_dro'].set_sensitive(False)

            self.conv_thread_mill_ext_int = 'internal'
            self.update_chip_load_hint()

        else:  #self.conv_thread_mill_ext_int == 'internal':
            self.set_image('thread_mill_ext_int_btn_image', 'thread_ext_button.jpg')
            self.image_list['thread_mill_main_image'].set_from_file(os.path.join(GLADE_DIR, 'mill_thread_mill_ext_main.svg'))
            self.image_list['thread_mill_detail_image'].set_from_file(os.path.join(GLADE_DIR, 'mill_thread_mill_ext_detail.svg'))

            # turn Internal DROs OFF
            ##self.thread_mill_int_dro_list['thread_mill_int_x_dro'].set_visible(False)
            ##self.thread_mill_int_dro_list['thread_mill_int_y_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_z_end_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_doc_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_passes_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_pitch_dro'].set_visible(False)
            self.thread_mill_int_dro_list['thread_mill_int_tpu_dro'].set_visible(False)
            self.thread_mill_int_minimal_retract_check.set_visible(False)

            # turn External DROs ON
            ##self.thread_mill_ext_dro_list['thread_mill_ext_x_dro'].set_visible(True)
            ##self.thread_mill_ext_dro_list['thread_mill_ext_y_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_z_end_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_passes_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_pitch_dro'].set_visible(True)
            self.thread_mill_ext_dro_list['thread_mill_ext_tpu_dro'].set_visible(True)

            ## these conv_DROs are also changed in on_conversational_notebook_switch_page
            #self.conv_dro_list['conv_rough_sfm_dro'].set_sensitive(False)

            self.conv_thread_mill_ext_int = 'external'
        self.load_title_dro()
        # stuff dros with new values for int or ext
        if self.conv_thread_mill_ext_int == 'external':
            self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'].grab_focus()
        else:
            self.thread_mill_int_dro_list['thread_mill_int_doc_dro'].grab_focus()
        self.on_thread_chart_changed(self.builder.get_object('thread_combobox'))


    def on_thread_mill_ext_int_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.on_thread_mill_ext_int_set_state()

    def thread_combo_spec(self, text=None):
        return TormachUIBase.get_set_combo_literal(self.builder.get_object('thread_combobox'), text)

    def thread_internal_retract(self, text=None):
        if text is None:
            return self.conv_thread_mill_retract
        elif not any(text):
            self.conv_thread_mill_retract = 'center'
        elif text == 'minimal':
            self.conv_thread_mill_retract = 'minimal'
        else:
            self.conv_thread_mill_retract = 'center'
        self.thread_mill_int_minimal_retract_check.set_active(self.conv_thread_mill_retract == 'minimal')
        return None

    def on_thread_mill_minimal_retract_checkbutton_toggled(self, widget, data=None):
        self.conv_thread_mill_retract = 'minimal' if widget.get_active() else 'center'

    def on_thread_chart_changed(self, widget, data=None):
        # get active entry, populate DROs
        model = widget.get_model()
        active_text = widget.get_active()
        if active_text == -1:  # catch when the default empty cell is active
            return
        thread_str = model[active_text][1].strip()
        if len(thread_str) == 0 or thread_str == THREAD_CUSTOM_DELIMITER or thread_str == THREAD_TORMACH_DELIMITER:
            # empty or delimiter string selected, do nothing
            return
        # parse space delimited string in text
        tpu, ext_major, ext_minor, int_major, int_minor = [x.strip() for x in thread_str.split(',') if x.strip()]

        tpu = float(tpu)
        pitch = 1 / tpu

        # use external or internal diameters as required to set DROs
        if self.conv_thread_mill_ext_int == 'external':
            major_diameter = float(ext_major)
            minor_diameter = float(ext_minor)
            self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].set_text(self.dro_long_format % major_diameter)
            self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].set_text(self.dro_long_format % minor_diameter)
            self.thread_mill_ext_dro_list['thread_mill_ext_tpu_dro'].set_text(self.dro_medium_format % tpu)
            self.thread_mill_ext_dro_list['thread_mill_ext_pitch_dro'].set_text(self.dro_long_format % pitch)
        else:
            major_diameter = float(int_major)
            minor_diameter = float(int_minor)
            self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].set_text(self.dro_long_format % major_diameter)
            self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].set_text(self.dro_long_format % minor_diameter)
            self.thread_mill_int_dro_list['thread_mill_int_tpu_dro'].set_text(self.dro_medium_format % tpu)
            self.thread_mill_int_dro_list['thread_mill_int_pitch_dro'].set_text(self.dro_long_format % pitch)


    # External
    def on_thread_mill_ext_x_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_y_dro'].grab_focus()


    def on_thread_mill_ext_y_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'].grab_focus()


    def on_thread_mill_ext_z_start_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_z_end_dro'].grab_focus()


    def on_thread_mill_ext_z_end_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].grab_focus()


    def on_thread_mill_ext_major_dia_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].grab_focus()


    def on_thread_mill_ext_minor_dia_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_ext_dro_list['thread_mill_ext_passes_dro'].grab_focus()


    def thread_mill_doc(self, thread_depth, num_passes):
        area_range = (thread_depth ** 2) / math.sqrt(3)
        area_doc = area_range / num_passes
        return math.sqrt(area_doc * math.sqrt(3))


    def on_thread_mill_ext_passes_dro_activate(self, widget, data=None):
        (valid, num_passes, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, '%d' % num_passes)

        major_radius = minor_radius = 0.
        # passes is valid, so check major and minor, then calculate doc
        # this results in calculations that are dependent on several DROs
        # if one is vacant or has a bad value this simply returns.
        # 'Dependencies' will get worked out at 'Post' time
        (valid, major_dia, error_msg) = self.conversational.validate_param(self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'])
        if not valid:
            self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].grab_focus()
            return
        major_radius = major_dia / 2

        (valid, minor_dia, error_msg) = self.conversational.validate_param(self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'])
        if not valid:
            self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].grab_focus()
            return
        minor_radius = minor_dia / 2

        doc = self.thread_mill_doc(math.fabs(major_radius - minor_radius), num_passes)

        self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'].set_text(self.dro_long_format % doc)

        self.thread_mill_ext_dro_list['thread_mill_ext_doc_dro'].grab_focus()


    def on_thread_mill_ext_doc_dro_activate(self, widget, data=None):
        (valid, doc_requested, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % doc_requested)
        # doc is valid, so check major and minor, then calculate passes
        # this results in calculations that are dependent on several DROs
        # if one is vacant or has a bad value this simply returns.
        # 'Dependencies' will get worked out at 'Post' time
        (valid, major_dia, error_msg) = self.conversational.validate_param(self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'])
        if not valid:
            self.thread_mill_ext_dro_list['thread_mill_ext_major_dia_dro'].grab_focus()
            return
        major_radius = major_dia / 2

        (valid, minor_dia, error_msg) = self.conversational.validate_param(self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'])
        if not valid:
            self.thread_mill_ext_dro_list['thread_mill_ext_minor_dia_dro'].grab_focus()
            return
        minor_radius = minor_dia / 2

        area_doc_requested = (doc_requested ** 2) / math.sqrt(3)
        thread_range = math.fabs(major_radius - minor_radius)
        area_range = (thread_range ** 2) / math.sqrt(3)
        num_passes = int(round(area_range / area_doc_requested))
        if num_passes > 0:
            area_adjusted = area_range / num_passes
            doc_adjusted = math.sqrt(area_adjusted * math.sqrt(3))

            self.thread_mill_ext_dro_list['thread_mill_ext_passes_dro'].set_text(self.dro_short_format % num_passes)
            (valid, number, error_msg) = self.conversational.validate_param(self.thread_mill_ext_dro_list['thread_mill_ext_passes_dro'])

            FSBase.dro_on_activate(widget, self.dro_long_format % doc_adjusted)

            self.thread_mill_ext_dro_list['thread_mill_ext_pitch_dro'].grab_focus()
        else:  # error, num passes <= 1
            error_msg = 'This depth of cut produces less than one pass, please set to %s or less' % self.dro_long_format % thread_range
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            cparse.raise_alarm(widget, error_msg)


    def on_thread_mill_ext_pitch_dro_activate(self, widget, data=None):
        (valid, pitch, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % pitch)

        if pitch > 0:
            tpu = 1 / pitch
        else:
            tpu = 0
        self.thread_mill_ext_dro_list["thread_mill_ext_tpu_dro"].set_text(self.dro_medium_format % tpu)

        self.thread_mill_ext_dro_list['thread_mill_ext_tpu_dro'].grab_focus()


    def on_thread_mill_ext_tpu_dro_activate(self, widget, data=None):
        (valid, tpu, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_medium_format % tpu)

        pitch = 1 / tpu
        self.thread_mill_ext_dro_list["thread_mill_ext_pitch_dro"].set_text(self.dro_long_format % pitch)

        self.thread_mill_ext_dro_list['thread_mill_ext_z_start_dro'].grab_focus()


    # Internal
    def on_thread_mill_int_x_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_y_dro'].grab_focus()


    def on_thread_mill_int_y_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'].grab_focus()


    def on_thread_mill_int_z_start_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_z_end_dro'].grab_focus()


    def on_thread_mill_int_z_end_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].grab_focus()


    def on_thread_mill_int_major_dia_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].grab_focus()


    def on_thread_mill_int_minor_dia_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.thread_mill_int_dro_list['thread_mill_int_passes_dro'].grab_focus()


    def on_thread_mill_int_passes_dro_activate(self, widget, data=None):
        (valid, num_passes, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, '%d' % num_passes)

        major_radius = minor_radius = 0.
        # passes is valid, so check major and minor, then calculate doc
        # this results in calculations that are dependent on several DROs
        # if one is vacant or has a bad value this simply returns.
        # 'Dependencies' will get worked out at 'Post' time
        (valid, major_dia, error_msg) = self.conversational.validate_param(self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'])
        if not valid:
            self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].grab_focus()
            return
        major_radius = major_dia / 2

        (valid, minor_dia, error_msg) = self.conversational.validate_param(self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'])
        if not valid:
            self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].grab_focus()
            return
        minor_radius = minor_dia / 2

        doc = self.thread_mill_doc(math.fabs(major_radius - minor_radius), num_passes)

        self.thread_mill_int_dro_list['thread_mill_int_doc_dro'].set_text(self.dro_long_format % doc)

        self.thread_mill_int_dro_list['thread_mill_int_doc_dro'].grab_focus()


    def on_thread_mill_int_doc_dro_activate(self, widget, data=None):
        (valid, doc_requested, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % doc_requested)

        major_radius = minor_radius = 0.
        (valid, major_dia, error_msg) = self.conversational.validate_param(self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'])
        if not valid:
            self.thread_mill_int_dro_list['thread_mill_int_major_dia_dro'].grab_focus()
            return
        major_radius = major_dia / 2

        (valid, minor_dia, error_msg) = self.conversational.validate_param(self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'])
        if not valid:
            self.thread_mill_int_dro_list['thread_mill_int_minor_dia_dro'].grab_focus()
            return
        minor_radius = minor_dia / 2

        area_doc_requested = (doc_requested ** 2) / math.sqrt(3)
        thread_range = math.fabs(major_radius - minor_radius)
        area_range = (thread_range ** 2) / math.sqrt(3)
        num_passes = int(round(area_range / area_doc_requested))
        area_adjusted = area_range / num_passes
        doc_adjusted = math.sqrt(area_adjusted * math.sqrt(3))

        self.thread_mill_int_dro_list['thread_mill_int_passes_dro'].set_text(self.dro_short_format % num_passes)
        (valid, number, error_msg) = self.conversational.validate_param(self.thread_mill_int_dro_list['thread_mill_int_passes_dro'])

        widget.set_text('%s' % self.dro_long_format % doc_adjusted)

        self.thread_mill_int_dro_list['thread_mill_int_pitch_dro'].grab_focus()


    def on_thread_mill_int_pitch_dro_activate(self, widget, data=None):
        (valid, pitch, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % pitch)
        if pitch > 0:
            tpu = 1 / pitch
        else:
            tpu = 0
        self.thread_mill_int_dro_list["thread_mill_int_tpu_dro"].set_text(self.dro_medium_format % tpu)

        self.thread_mill_int_dro_list['thread_mill_int_tpu_dro'].grab_focus()


    def on_thread_mill_int_tpu_dro_activate(self, widget, data=None):
        (valid, tpu, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_medium_format % tpu)

        pitch = 1 / tpu
        self.thread_mill_int_dro_list["thread_mill_int_pitch_dro"].set_text(self.dro_long_format % pitch)

        self.thread_mill_int_dro_list['thread_mill_int_z_start_dro'].grab_focus()


    # Internal and External

    # these two radio buttons are a group
    def on_thread_mill_right_radiobutton_toggled(self, widget, data=None):
        if widget.get_active():
            self.thread_mill_rhlh = "right"
            self.window.set_focus(None)

    def on_thread_mill_left_radiobutton_toggled(self, widget, data=None):
        if widget.get_active():
            self.thread_mill_rhlh = "left"
            self.window.set_focus(None)


    # -------------------------------------------------------------------------------------------------
    # Conversational
    # Engrave DRO handlers
    # -------------------------------------------------------------------------------------------------
    def conv_engrave_switch_page(self):
        self.engrave_dro_list['engrave_sn_start_dro'].set_text('')
        return

    def on_engrave_sn_start_button_release(self, widget, data=None):
        current_sn = ''
        try:
            current_sn = self.redis.hget('machine_prefs', 'current_engraving_sn')
        except:
            pass
        self.engrave_dro_list['engrave_sn_start_dro'].set_text(current_sn)
        self.engrave_dro_list['engrave_sn_start_dro'].select_region(0,-1)


    def on_engrave_text_dro_activate(self, widget, data=None):
        # the 'normal' validate allows for empty text...
        (valid, engrave_text, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return

        # an empty engrave text is ok, if empty check the serial number
        # if that is also empty - not ok. On the second test 'validate_text'
        # is called which won't allow empty text.
        sn_text = self.engrave_dro_list['engrave_sn_start_dro'].get_text()
        if len(sn_text) == 0:
            (valid, engrave_text, error_msg) = self.conversational.validate_text(widget)
            if not valid:
                self.error_handler.write('Enter either Text and/or a Serial Number', ALARM_LEVEL_LOW)
                return
        cparse.clr_alarm(widget)
        cparse.clr_alarm(self.engrave_dro_list['engrave_sn_start_dro'])

        self.engrave_sample_update()
        self.engrave_dro_list['engrave_height_dro'].grab_focus()


    def on_engrave_set_font(self, font_file):
        (family, name) = self.get_ttfont_name(font_file)
        for row in self.engrave_font_liststore:
            font_info = row[0]
            if name in font_info:
                try:
                    iter_item = getattr(row,'iter')
                    selection = self.engrave_font_treeview.get_selection()
                    selection.select_iter(iter_item)
                    path = getattr(row,'path')
                    self.engrave_sample_update()
                    self.engrave_font_pf = font_file
                except:
                    self.error_handler.write('Exception ocurred in on_engrave_set_font', ALARM_LEVEL_DEBUG)
                break


    def on_engrave_font_tview_cursor_changed(self, treeview):
        cursor_actv_list, tvcolumnobj = treeview.get_cursor()
        row = cursor_actv_list[0]  # get first and only selected row

        # remember the font row for configuring the font selector next time
        self.engrave_font_row = row
        self.engrave_font_pf = os.path.join(ENGRAVING_FONTS_DIR, self.font_file_list[row])

        self.engrave_sample_update()


    def engrave_sample_update(self):
        # update font of the engraving text dro
        (ef_name, ef_family) = self.get_ttfont_name(self.engrave_font_pf)

        if self.engrave_just == 'right':
            self.engrave_text_dro.set_alignment(1)
        elif self.engrave_just == 'center':
            self.engrave_text_dro.set_alignment(0.5)
        else:  # left
            self.engrave_text_dro.set_alignment(0.0)

        fd = pango.FontDescription('%s 24' % (ef_name))
        self.engrave_text_dro.modify_font(fd)


    def on_engrave_x_base_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.engrave_dro_list['engrave_y_base_dro'].grab_focus()


    def on_engrave_y_base_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.engrave_dro_list['engrave_z_start_dro'].grab_focus()


    def on_engrave_z_start_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.engrave_dro_list['engrave_z_doc_dro'].grab_focus()


    def on_engrave_height_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        widget.set_text('%s' % self.dro_long_format % number)
        self.engrave_dro_list['engrave_x_base_dro'].grab_focus()


    def on_engrave_z_doc_dro_activate(self, widget, data=None):
        (valid, number, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        FSBase.dro_on_activate(widget, self.dro_long_format % number)
        self.engrave_dro_list['engrave_text_dro'].grab_focus()


    def on_engrave_sn_start_dro_focus_in_event(self, widget, data=None):
        current_number = widget.get_text()
        if len(current_number) > 0:
            return
        try:
            current_sn = self.redis.hget('machine_prefs', 'current_engraving_sn')
            current_text = widget.get_text()
            current_text_length = len(current_text)
            current_sn_length = len(current_sn)
            while current_sn_length < current_text_length:
                current_sn = "0%s" % current_sn
                current_sn_length += 1
            widget.set_text(current_sn)
        except:
            pass


    def on_engrave_sn_start_dro_activate(self, widget, data=None):
        (valid, number_as_text, error_msg) = self.conversational.validate_param(widget)
        if not valid:
            self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
            return
        text = number_as_text if number_as_text is not None else ''
        try:
            if len(text) > 0:
                self.redis.hset('machine_prefs', 'current_engraving_sn', text)
        except:
            pass
        widget.set_text(text)

        # if the serial number is empty that's ok. Test for on empty text in engrave text
        # if both are empty an error is thrown through 'validate_text'
        if len(text) > 0:
            self.conversational.validate_param(self.engrave_dro_list['engrave_text_dro'])
        else:
            text = self.engrave_dro_list['engrave_text_dro'].get_text()
            if text == '':
                valid,t,error = self.conversational.validate_text(widget)
                error = '%s: Enter either Text and/or a Serial Number' % error
                self.error_handler.write(error, ALARM_LEVEL_LOW)
                return
        cparse.clr_alarm(widget)
        cparse.clr_alarm(self.engrave_dro_list['engrave_text_dro'])
        self.engrave_dro_list['engrave_height_dro'].grab_focus()

    def set_active_engrave_justification(self, justification = None):
        if not justification: justification = self.engrave_just
        if justification == 'left': self.builder.get_object('engrave_left_radiobutton').set_active(True)
        elif justification == 'center': self.builder.get_object('engrave_center_radiobutton').set_active(True)
        elif justification == 'right': self.builder.get_object('engrave_right_radiobutton').set_active(True)
        self.engrave_just = justification

    # these three radio buttons are a group
    def on_engrave_left_radiobutton_toggled(self, widget, data=None):
        if widget.get_active():
            self.engrave_just = "left"
            self.engrave_sample_update()
            self.window.set_focus(None)

    def on_engrave_center_radiobutton_toggled(self, widget, data=None):
        if widget.get_active():
            self.engrave_just = "center"
            self.engrave_sample_update()
            self.window.set_focus(None)

    def on_engrave_right_radiobutton_toggled(self, widget, data=None):
        if widget.get_active():
            self.engrave_just = "right"
            self.engrave_sample_update()
            self.window.set_focus(None)



    # -------------------------------------------------------------------------------------------------
    # end of conversational tab callbacks
    # -------------------------------------------------------------------------------------------------

    def issue_tool_offset_command(self, axis, offset_register, value):
        g10_command = "G10 L1 P%d %s%f" %(offset_register, axis, value)
        self.issue_mdi(g10_command)
        self.command.wait_complete()

    # -------------------------------------------------------------------------------------------------
    # conversational helpers
    # -------------------------------------------------------------------------------------------------

    def save_conv_title(self, key):
        if self.redis.hexists('machine_prefs',key):
            value = self.conv_dro_list['conv_title_dro'].get_text()
            self.redis.hset('machine_prefs',key,value)
        else:
            self.error_handler.write('save_conv_title - could not find %s' % key, ALARM_LEVEL_DEBUG)

    def save_conv_parameters(self, dro_list):
        # loop through conv dro list and save values to redis
        for name, dro in self.conv_dro_list.iteritems():
            val = dro.get_text()
            self.redis.hset('conversational', name, val)
        for name, dro in dro_list.iteritems():
            val = dro.get_text()
            self.redis.hset('conversational', name, val)


    def restore_conv_parameters(self):
        """
        Restore conversational parameters to all "old-style" conversational panes.

        Note that DXF is not present here, because its initialiation routine takes care of this

        """
        conv_dict = self.redis.hgetall('conversational')
        for dro_name , val in conv_dict.iteritems():
            try:
                if 'conv' in dro_name:
                    self.conv_dro_list[dro_name].set_text(val)
                    self.current_normal_z_feed_rate = self.conv_dro_list['conv_z_feed_dro'].get_text()
                if 'face' in dro_name:
                    self.face_dro_list[dro_name].set_text(val)
                if 'profile' in dro_name:
                    self.profile_dro_list[dro_name].set_text(val)
                if 'pocket_rect' in dro_name:
                    self.pocket_rect_dro_list[dro_name].set_text(val)
                if 'pocket_circ' in dro_name:
                    self.pocket_circ_dro_list[dro_name].set_text(val)
                if 'pattern_circular' in dro_name:
                    self.drill_circular_dro_list[dro_name].set_text(val)
                if 'drill' in dro_name:
                    self.drill_dro_list[dro_name].set_text(val)
                if 'tap' in dro_name:
                    self.tap_dro_list[dro_name].set_text(val)
                if 'thread_mill_ext' in dro_name:
                    self.thread_mill_ext_dro_list[dro_name].set_text(val)
                if 'thread_mill_int' in dro_name:
                    self.thread_mill_int_dro_list[dro_name].set_text(val)
                if 'engrave' in dro_name:
                    self.engrave_dro_list[dro_name].set_text(val)
                if 'scan' in dro_name:
                    self.scanner_scan_dro_list[dro_name].set_text(val)
            except:
                pass


    def set_home_switches(self):
        self.hal["home-switch-enable"] = self.settings.home_switches_enabled
        self.redis.hset('machine_prefs', 'home_switches_enabled', self.settings.home_switches_enabled)
        self.enable_home_switch(0, self.settings.home_switches_enabled)
        self.enable_home_switch(1, self.settings.home_switches_enabled)
        self.enable_home_switch(2, self.settings.home_switches_enabled)
        self.settings.show_or_hide_limit_leds()


    def set_4th_axis_homing_parameters(self, enable_flag):
        axis_N = 'AXIS_3'
        home = self.ini_float(axis_N, "HOME", 0.0)
        if (enable_flag == True):
            # TODO: put these values in INI as HOME_*_HOMING_KIT
            home_offset = self.ini_float(axis_N, "HOME_OFFSET_HOMING_KIT", 0.0)
            home_search_vel = self.ini_float(axis_N, "HOME_SEARCH_VEL_HOMING_KIT", 5.0)
            home_latch_vel = self.ini_float(axis_N, "HOME_LATCH_VEL_HOMING_KIT", 0.5)
        else:
            # these set to zero means 'set home where it is now' - no motion
            home_offset = 0.0
            home_search_vel = 0.0
            home_latch_vel = 0.0
        home_final_vel = self.ini_float(axis_N, "HOME_FINAL_VEL", -1)
        home_use_index = self.ini_flag(axis_N, "HOME_USE_INDEX", False)
        home_ignore_limits = self.ini_flag(axis_N, "HOME_IGNORE_LIMITS", False)
        home_home_is_shared = self.ini_flag(axis_N, "HOME_IS_SHARED", 0)
        home_sequence = self.ini_flag(axis_N, "HOME_SEQUENCE", 0)
        volatile_home = self.ini_flag(axis_N, "VOLATILE_HOME", 0)
        locking_indexer = self.ini_flag(axis_N, "LOCKING_INDEXER", 0)

        self.command.set_homing_params(3, home, home_offset, home_final_vel, home_search_vel,
                                       home_latch_vel, home_use_index, home_ignore_limits,
                                       home_home_is_shared, home_sequence, volatile_home,
                                       locking_indexer)

    # -------------------------------------------------------------------------------------------------
    # Alarms page
    # -------------------------------------------------------------------------------------------------

    def on_zero_height_gauge_button_release_event(self, widget, data=None):
        if not self.is_button_permitted(widget): return
        self.hal['hg-set-zero-offset'] = True
        #self.dro_list['height_gauge_dro'].set_text(self.dro_long_format % 0.0)

    def fetch_bt30_offset(self):
        self.hal['spindle-set-bt30'] = 1
        time.sleep(.01)
        loopIt = 3
        while loopIt > 0 and self.hal['spindle-set-bt30'] == 1:
            loopIt -= 1
            time.sleep(.01)
        if self.hal['spindle-set-bt30'] == 0 and self.hal['spindle-orient-fault'] == 0:
            return self.hal['spindle-bt30-offset']

        return BT30_OFFSET_INVALID #something went wrong


    def on_bt30_button_release_event(self, widget, data=None):
        if self.hal['spindle-zindex-state'] != ( ISTATE_DONE | ISTATE_PAST ):
            msg = "The spindle must be rotated one full turn to initialize the encoder.\n\n1. Disengage the spindle drive dogs by jogging the Z-axis up (Z+).\n\n2. Rotate the spindle at least one revolution by hand in either direction.\n\n3. Jog the Z-axis down (Z-) to re-engage the spindle drive dogs.\n\n4. Select Set TC M19 again."
            conf_dialog = popupdlg.ok_cancel_popup(self.window, msg, cancel=False, checkbox=False)
            conf_dialog.run()
            conf_dialog.destroy()
            return

        the_bt30_offset = self.hal['spindle-bt30-offset']

        #TODO: Note we have "cancel" checking code here for dialogs but we've removed the button.  Left it in for now so we can change back easy.

        if the_bt30_offset != BT30_OFFSET_INVALID:
            conf_dialog = popupdlg.ok_cancel_popup(self.window, "Are you sure you want to change the current BT30 spindle alignment position?", cancel=True, checkbox=False)
            conf_dialog.run()
            conf_dialog.destroy()
            response = conf_dialog.response
            if response == gtk.RESPONSE_CANCEL:
                return

        old_bt30_offset = the_bt30_offset
        bt30_msg = 'setting bt30 offset: original offset = %d' % old_bt30_offset
        self.error_handler.write(bt30_msg, ALARM_LEVEL_DEBUG)

        conf_dialog = popupdlg.ok_cancel_popup(self.window, "Rotate the tool clockwise in the tray fork by hand, hold it in place, and select OK.", cancel=False, checkbox=False)
        conf_dialog.run()
        conf_dialog.destroy()
        response = conf_dialog.response
        if response == gtk.RESPONSE_CANCEL:
            return

        offset_cw = self.fetch_bt30_offset()
        bt30_msg = 'setting bt30 offset: cw_offset = %d' % offset_cw
        self.error_handler.write(bt30_msg, ALARM_LEVEL_DEBUG)

        if offset_cw != BT30_OFFSET_INVALID:
            conf_dialog = popupdlg.ok_cancel_popup(self.window, "Rotate the tool counterclockwise in the tray fork by hand, hold it in place, and select OK.", cancel=False, checkbox=False)
            conf_dialog.run()
            conf_dialog.destroy()
            response = conf_dialog.response
            if response == gtk.RESPONSE_CANCEL:
                self.hal['spindle-bt30-offset'] = old_bt30_offset
                bt30_msg = 'setting bt30 offset: user abort'
                self.error_handler.write(bt30_msg, ALARM_LEVEL_DEBUG)
                return

        offset_ccw = self.fetch_bt30_offset()
        bt30_msg = 'setting bt30 offset: ccw_offset = %d' % offset_ccw
        self.error_handler.write(bt30_msg, ALARM_LEVEL_DEBUG)

        if offset_ccw != BT30_OFFSET_INVALID and offset_cw != BT30_OFFSET_INVALID and offset_cw != offset_ccw and abs(offset_ccw - offset_cw) < 60:  #10 degrees/ 360 * CPR of 2048 = ~60 counts
            new_offset = (offset_ccw + offset_cw) / 2
            self.hal['spindle-bt30-offset'] = new_offset
            bt30_offset = self.hal['spindle-bt30-offset']
            bt30_msg = "setting bt30 offset: new offset = %d" % new_offset
            usr_msg = "BT30 spindle alignment position set successfully."
            self.redis.hset("machine_prefs", "bt30_offset", bt30_offset)
            # storing the window we saw for easy telemetry later in case it is lost from log rotation or clearing of logs
            self.redis.hset("machine_prefs", "bt30_offset_window", "{:d} {:d}".format(offset_ccw, offset_cw))
        else:
            bt30_msg = usr_msg = "Failed to set the BT30 spindle alignment position.\n\nRepeat the procedure to set the spindle alignment position.  If the issue continues, contact Tormach Technical Support."
            self.hal['spindle-bt30-offset'] = old_bt30_offset

        self.error_handler.write(bt30_msg, ALARM_LEVEL_DEBUG)
        conf_dialog = popupdlg.ok_cancel_popup(self.window, usr_msg, cancel=False, checkbox=False)
        conf_dialog.run()
        conf_dialog.destroy()


    # ------------------------------------------------------------------------
    # dynamic tooltip methods
    # ------------------------------------------------------------------------

    def __get_tool_offset(self, tool_number):
        return self.status.tool_table[int(tool_number)].zoffset

    def _get_tool_tip_tool_description(self, tool_number, description):
        # this is called with a qualified tool number, i.e., on that is: 1)
        # and integer, and 2) in the range of tool number for the machine the
        # description will not be blank as that is caught by the calling
        # method
        if self.zero_tool_diameter(tool_number):
            zero_dia_msg = tooltipmgr.TTMgr().get_local_string('msg_zero_diameter_tool').format(str(tool_number))
            description += ' '+zero_dia_msg
        return self._get_tool_tip_axial_tool_description(tool_number, description, self.__get_tool_offset(tool_number))

    def get_current_serial_number(self, param):
        current_sn = self.redis.hget('machine_prefs', 'current_engraving_sn')
        if current_sn is None:
            current_sn = ''
        return current_sn

    def get_panel_tip_tool_description(self, param):
        # this is wrapper method for now, which may have some
        # extra formatting in the future...
        valid, tool_number, error_msg = self.conversational.validate_tool_number(self.dro_list['tool_dro'])
        if not valid: self.dro_list['tool_dro'].masked = 0
        return self._test_tooltip_description(self.dro_list['tool_dro'].get_text())

    def get_current_gcode_states(self, param):
        if self.status.task_state == linuxcnc.STATE_ESTOP or \
           self.status.task_state == linuxcnc.STATE_ESTOP_RESET or \
           self.status.task_state == linuxcnc.STATE_OFF:
            return '\n'+tooltipmgr.TTMgr().get_local_string('pre_RESET_gcode_status')
        outstr = '\n<span color="#003aff">'
        g20 = 'inches'
        active_gcodes = self.active_gcodes()
        for gc in active_gcodes:
            if gc in 'G54G55G56G57G58G59': outstr += '<b>'+gc+'</b>'+' - current work offset\n'; continue
            if gc == 'G20'               : outstr += '<b>'+gc+'</b>'+' - machine in <b>inch</b> units\n'; continue
            if gc == 'G21'               : outstr += '<b>'+gc+'</b>'+' - machine in <b>metric</b> units\n'; g20 = 'mm'; continue
            if gc == 'G90'               : outstr += '<b>'+gc+'</b>'+' - distance mode <b>absolute</b>\n'; continue
            if gc == 'G91'               : outstr += '<b>'+gc+'</b>'+' - distance mode <b>incremental</b>\n'; continue
            if gc == 'G80'               : outstr += '<b>'+gc+'</b>'+' - drill cycle <b>off</b>\n'; continue
            if gc in 'G81G82G83G85G88G89': outstr += '<b>'+gc+'</b>'+' - drill cycle <b>on</b>\n'; continue
            if gc == 'G40'               : outstr += '<b>'+gc+'</b>'+' - cutter radius compensation <b>off</b>\n'; continue
            if gc in 'G41G42'            : outstr += '<b>'+gc+'</b>'+' - cutter radius compensation <b>on</b>\n'; continue
            if gc == 'G93'               : outstr += '<b>'+gc+'</b>'+' - inverse time mode\n'; continue
            if gc == 'G94'               : outstr += '<b>'+gc+'</b>'+' - %s per minute mode\n'%g20; continue
            if gc == 'G95'               : outstr += '<b>'+gc+'</b>'+' - %s per revolution mode\n'%g20; continue
            if gc == 'G96'               : outstr += '<b>'+gc+'</b>'+' - constant surface speed <b>on</b>\n'; continue
            if gc == 'G97'               : outstr += '<b>'+gc+'</b>'+' - rpm mode <b>on</b>\n'; continue
            if gc == 'G98'               : outstr += '<b>'+gc+'</b>'+' - retract to start position\n'; continue
            if gc == 'G99'               : outstr += '<b>'+gc+'</b>'+' - retract to R word\n'; continue
            if gc == 'G91.1'             : outstr += '<b>'+gc+'</b>'+' - I,J,K mode <b>incremental</b>\n'; continue
            if gc == 'G90.1'             : outstr += '<b>'+gc+'</b>'+' - I,J,K mode <b>absolute</b>\n'; continue
        outstr = outstr[:-1]
        return outstr+'</span>'

    def get_chip_load_type(self, param):
        table = tooltipmgr.TTMgr().get_local_string('msg_table_str')
        return 'Z' if self.current_conv_notebook_page_id_is('conv_drill_tap_fixed') else table

    def _get_current_spindle_range_image(self, param):
        param['images'] = ['TT.Mill-hi-pulley.svg'] if self.hal['spindle-range'] else ['TT.Mill-lo-pulley.svg']

    def get_G0_tooltip(self, param):
        param['images'] = ['TT.G0-mill.png','TT.v-space-3.png']
        return tooltipmgr.TTMgr().get_local_string('G0_mill_tooltip')

    def get_G1_tooltip(self, param):
        param['images'] = ['TT.G1-mill.png','TT.v-space-3.png']
        return tooltipmgr.TTMgr().get_local_string('G1_mill_tooltip')

    def get_G2_tooltip(self, param):
        param['images'] = ['TT.G2-mill.png','TT.v-space-3.png']
        return tooltipmgr.TTMgr().get_local_string('G2_mill_tooltip')

    def get_G3_tooltip(self, param):
        param['images'] = ['TT.G3-mill.png','TT.v-space-3.png']
        return tooltipmgr.TTMgr().get_local_string('G3_mill_tooltip')

    def get_G41_tooltip(self, param):
        param['images'] = ['TT.G41-mill.png',"TT.v-space-3.png"]
        return tooltipmgr.TTMgr().get_local_string('G41_mill_tooltip')

    def get_G41_1_tooltip(self, param):
        param['images'] = ['TT.G41-mill.png','TT.v-space-3.png']
        return ''

    def get_G42_tooltip(self, param):
        param['images'] = ['TT.G42-mill.png',"TT.v-space-3.png"]
        return tooltipmgr.TTMgr().get_local_string('G42_mill_tooltip')

    def get_G42_1_tooltip(self, param):
        param['images'] = ['TT.G42-mill.png','TT.v-space-3.png']
        return ''

    def get_G54_59_tooltip(self, param):
        param['images'] = ['TT.G54-mill.png',"TT.v-space-3.png"]
        return tooltipmgr.TTMgr().get_local_string('G54_59_mill_tooltip')

    # ----------------------------------------
    # helpers
    # ----------------------------------------

    def highlight_offsets_treeview_row(self):
        tool_num = self.status.tool_in_spindle
        if tool_num > 0:
            self.treeselection.select_path(tool_num - 1)


    def hide_notebook_tabs(self):
        for i in range(0, self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            page_id = gtk.Buildable.get_name(page)
            # only hide the alarms tab if no alarms are active
            if not page_id in ("notebook_main_fixed", "alarms_fixed"):
                page.hide()

    def show_enabled_notebook_tabs(self, data=None):
        for i in range(0, self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            page_id = gtk.Buildable.get_name(page)

            # don't show the ATC page if we don't have an ATC.  Likewise with scanner
            if page_id == 'atc_fixed':
                if self.atc.operational:
                    page.show()
                else:
                    page.hide()
            elif page_id == 'injector_fixed':
                if self.settings.injector_enabled:
                    page.show()
                else:
                    page.hide()
            elif page_id == 'scanner_fixed':
                if self.settings.scanner_enabled:
                    page.show()
                else:
                    page.hide()
            else:
                page.show()

    def refresh_touch_z_led(self):
        # set touch z button LED if the current tool has a non-zero offset
        # only if the touch_z button doesn't have focus
        if self.button_list['touch_z'].has_focus(): return
        if self.status.tool_offset[2] != 0:
            self.set_image('touch_z_image', 'touch_z_green_led.png')
        else:
            self.set_image('touch_z_image', 'touch_z_black_led.png')

    def refresh_atc_diagnostics(self):
        #self.atc.hey_hal(ATC_QUERY_SENSOR, ATC_ALL_SENSORS)
        # pressure sensor true means not enough pressure

        if self.hal["atc-pressure-status"]:
            self.set_image('pressure_sensor_led', 'LED-Yellow.png')
        else:
            self.set_image('pressure_sensor_led', 'LED-Green.png')

        # tray in - true means under spindle
        self.set_indicator_led('tray_in_led',self.hal["atc-tray-status"])

        # VFD true means spindle is running
        self.set_indicator_led('vfd_running_led',self.hal["atc-vfd-status"])


    def show_atc_diagnostics(self):
        self.vfd_status_by_atc = True
        self.builder.get_object('tray_in_text').show()
        self.image_list['tray_in_led'].show()
        self.builder.get_object('vfd_running_text').show()
        self.image_list['vfd_running_led'].show()
        self.builder.get_object('pressure_sensor_text').show()
        self.image_list['pressure_sensor_led'].show()
        # m200 VFD machines can always display vfd fault and running leds
        if self.machineconfig.has_ecm1():
            self.builder.get_object('vfd_fault_text').show()
            self.image_list['vfd_fault_led'].show()


    def hide_atc_diagnostics(self):
        self.vfd_status_by_atc = False
        self.builder.get_object('tray_in_text').hide()
        self.image_list['tray_in_led'].hide()
        self.builder.get_object('pressure_sensor_text').hide()
        self.image_list['pressure_sensor_led'].hide()
        # m200 VFD machines can always display vfd fault and running leds
        if not self.machineconfig.has_ecm1():
            self.builder.get_object('vfd_running_text').hide()
            self.image_list['vfd_running_led'].hide()
            self.builder.get_object('vfd_fault_text').hide()
            self.image_list['vfd_fault_led'].hide()


    def update_tlo_label(self):
        # if the offset in the tool table doesn't match the one that's applied, then set the led
        # to red
        current_tool_offset = round(self.status.tool_table[self.status.tool_in_spindle].zoffset, 4)
        currently_applied_offset = round(self.status.tool_offset[2], 4)
        if (current_tool_offset != currently_applied_offset):
            # ignore while the ATC is changing tools or if it only happens once
            #if self.atc.in_a_thread.is_set() or self.hal["atc-ngc-running"]:
            if not self.atc.is_changing():
                self.tlo_mismatch_count += 1   # must exist fot 2 cycles to flag red
                if self.tlo_mismatch_count > 1 :
                    self.tlo_mismatch_count = 1 # lets not ever overflow
                    self.tlo_label.set_markup('<span foreground="yellow" background="red">%s</span>' % self.dro_long_format % (currently_applied_offset * self.get_linear_scale()))
        else:
            self.tlo_mismatch_count = 0    #it agrees - set white
            self.tlo_label.set_markup('<span foreground="white">%s</span>' % self.dro_long_format % (currently_applied_offset * self.get_linear_scale()))


        #else:
            #self.tlo_label.set_markup('<span foreground="white">0.000</span>' )


    def set_button_permitted_states(self):
        # default is only can press the button when the machine is out of estop and at rest (referenced or not)
        for name, eventbox in self.button_list.iteritems():
            eventbox.permitted_states = STATE_IDLE | STATE_IDLE_AND_REFERENCED

        # program control buttons
        self.button_list['cycle_start'].permitted_states = STATE_RUNNING_PROGRAM | STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED
        self.button_list['single_block'].permitted_states = STATE_RUNNING_PROGRAM | STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED | STATE_MOVING | STATE_HOMING

        self.button_list['m01_break'].permitted_states = STATE_RUNNING_PROGRAM | STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED | STATE_MOVING | STATE_HOMING
        self.button_list['feedhold'].permitted_states = STATE_RUNNING_PROGRAM | STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED | STATE_MOVING | STATE_HOMING
        self.button_list['stop'].permitted_states = STATE_ANY
        self.button_list['coolant'].permitted_states = STATE_RUNNING_PROGRAM | STATE_PAUSED_PROGRAM | STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_MOVING | STATE_HOMING
        self.button_list['reset'].permitted_states = STATE_ANY
        self.button_list['feedrate_override_100'].permitted_states = STATE_ANY
        self.button_list['rpm_override_100'].permitted_states = STATE_ANY
        self.button_list['maxvel_override_100'].permitted_states = STATE_ANY
        self.button_list['edit_gcode'].permitted_states = STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED | STATE_IDLE | STATE_ESTOP
        self.button_list['spindle_range'].permitted_states = STATE_RUNNING_PROGRAM_TOOL_CHANGE_WAITING_ON_OPERATOR | STATE_PAUSED_PROGRAM | STATE_IDLE_AND_REFERENCED | STATE_IDLE

        # ref buttons
        self.button_list['ref_x'].permitted_states = STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_HOMING
        self.button_list['ref_y'].permitted_states = STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_HOMING
        self.button_list['ref_z'].permitted_states = STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_HOMING
        self.button_list['ref_a'].permitted_states = STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_HOMING

        # update and clear errors buttons
        self.button_list['update'].permitted_states = STATE_ESTOP | STATE_IDLE | STATE_IDLE_AND_REFERENCED
        self.button_list['clear'].permitted_states = STATE_ANY

        # Not all mills support RapidTurn...
        if 'switch_to_lathe' in self.settings.button_list:
            self.settings.button_list['switch_to_lathe'].permitted_states = STATE_ESTOP | STATE_IDLE | STATE_IDLE_AND_REFERENCED

        # by popular demand of beta program, use conv. screens
        self.button_list['post_to_file'].permitted_states = STATE_ANY
        self.button_list['append_to_file'].permitted_states = STATE_ANY

        # Allow scanner camera to be toggled
        self.button_list['scanner_camera_on_off'].permitted_states = STATE_ANY

        # Allow G30 only if machine is referenced.
        self.button_list['goto_g30'].permitted_states = STATE_IDLE_AND_REFERENCED

        # Allow tool changes only if machine is referenced because it may involve Z axis moves by ATC
        self.button_list['m6_g43'].permitted_states = STATE_IDLE_AND_REFERENCED

        # Allow tool table import and export.
        self.button_list['import_tool_table'].permitted_states = STATE_ANY
        self.button_list['export_tool_table'].permitted_states = STATE_ANY

        self.button_list['internet_led_button'].permitted_states = STATE_ESTOP | STATE_IDLE | STATE_IDLE_AND_REFERENCED | STATE_MOVING | STATE_HOMING
        self.button_list['logdata_button'].permitted_states = STATE_ESTOP | STATE_IDLE | STATE_IDLE_AND_REFERENCED

    # helper function for issuing MDI commands
    def issue_mdi(self, mdi_command):
        if self.moving():
            self.error_handler.write("Machine is moving. Not issuing MDI command: " + mdi_command, ALARM_LEVEL_LOW)
            return False

        if self.ensure_mode(linuxcnc.MODE_MDI):
            self.error_handler.write("issuing MDI command: {:s}".format(mdi_command), ALARM_LEVEL_DEBUG)
            self.command.mdi(mdi_command)
            return True
        else:
            self.error_handler.log("issue_mdi ignoring command {:s} because ensure_mode failed".format(mdi_command))
            return False

    # debug only??
    def get_lcnc_mode_string(self, mode):
        tmp_str = 'unknown'
        if mode == linuxcnc.MODE_MANUAL:
            tmp_str = 'MODE_MANUAL'
        elif mode == linuxcnc.MODE_AUTO:
            tmp_str = 'MODE_AUTO'
        elif mode == linuxcnc.MODE_MDI:
            tmp_str = 'MODE_MDI'
        return tmp_str

    def get_lcnc_interp_string(self, state):
        tmp_str = 'unknown'
        if state == linuxcnc.INTERP_IDLE:
            tmp_str = 'INTERP_IDLE'
        elif state == linuxcnc.INTERP_READING:
            tmp_str = 'INTERP_READING'
        elif state == linuxcnc.INTERP_PAUSED:
            tmp_str = 'INTERP_PAUSED'
        elif state == linuxcnc.INTERP_WAITING:
            tmp_str = 'INTERP_WAITING'
        return tmp_str

    def get_lcnc_state_string(self, state):
        tmp_str = 'unknown'
        if state == linuxcnc.STATE_ESTOP:
            tmp_str = 'STATE_ESTOP'
        elif state == linuxcnc.STATE_ESTOP_RESET:
            tmp_str = 'STATE_ESTOP_RESET'
        elif state == linuxcnc.STATE_OFF:
            tmp_str = 'STATE_OFF'
        elif state == linuxcnc.STATE_ON:
            tmp_str = 'STATE_ON'
        return tmp_str


    def update_spindle_direction_display(self):
        # update spindle direction
        self.spindle_direction = self.status.spindle_direction
        if self.spindle_direction != self.prev_spindle_direction:
            self.prev_spindle_direction = self.spindle_direction
            if self.spindle_direction == -1:
                # CCW
                self.set_image('ccw_image', 'REV_Green.jpg')
                self.set_image('cw_image', 'FWD_Black.jpg')
            elif self.spindle_direction == 0:
                # Off
                self.set_image('ccw_image', 'REV_Black.jpg')
                self.set_image( 'cw_image',  'FWD_Black.jpg')
            elif self.spindle_direction == 1:
                # CW
                self.set_image('ccw_image', 'REV_Black.jpg')
                self.set_image('cw_image',  'FWD_Green.jpg')

    def update_jog_leds(self):
        """ Handle updating of jog axis LED's to match HAL state"""

        jog_enabled = [self.hal['jog-axis-%s-enabled' % l] for l in self.axes.letters]

        for n,l in enumerate(self.axes.jog_active_leds):
            # Check if our local state doesn't match the HAL state.
            if jog_enabled[n] != self.axes.jog_enabled_local[n]:
                # HAL has changed, need to update the indicator to match the
                # new state
                self.set_indicator_led(l,jog_enabled[n])

        #Store the HAL state in the axes class:
        self.axes.jog_enabled_local = jog_enabled


    def zero_height_gauge_show_or_hide(self):
        if self.hal['hg-present'] == False:
            # hide the height gauge zero button if visible and gauge not present
            if self.zero_height_gauge_visible:
                self.button_list['zero_height_gauge'].hide()
                self.zero_height_gauge_visible = False
        else:
            # show if present and the old style, but not currently visible
            if not self.zero_height_gauge_visible and not self.hal['hg-has-zero-button']:
                self.button_list['zero_height_gauge'].show()
                self.zero_height_gauge_visible = True

    # called every 500 milliseconds to update various slower changing DROs and button images
    def status_periodic_500ms(self):
        if 'launch_test' in self.configdict["pathpilot"] and self.configdict["pathpilot"]["launch_test"]:
            self.quit()

        TormachUIBase.status_periodic_500ms(self)

        if self.pc_ok_LED_status == 0:
            self.hal['pc-ok-LED'] = 1
            self.pc_ok_LED_status = 1
        else:
            self.hal['pc-ok-LED'] = 0
            self.pc_ok_LED_status = 0

        # get machine state
        machine_executing_gcode = self.program_running()
        if machine_executing_gcode:
            machine_busy = True
        else:
            # moving under MDI, probing, ATC ops, jogging, etc
            machine_busy = self.moving()

        if self.hal['mesa-watchdog-has-bit']:
            # problem! the Mesa card watchdog has bitten
            # high priority warning
            if not self.mesa_watchdog_has_bit_seen:
                # set state to ESTOP
                self.mesa_watchdog_has_bit_seen = True
                self.command.state(linuxcnc.STATE_ESTOP)
                self.error_handler.write("Machine interface error. Check cabling and power to machine and then press RESET.", ALARM_LEVEL_MEDIUM)

                # unreference X, Y, and Z
                if self.status.homed[0]:
                    self.command.unhome(0)
                    self.command.wait_complete()
                if self.status.homed[1]:
                    self.command.unhome(1)
                    self.command.wait_complete()
                if self.status.homed[2]:
                    self.command.unhome(2)
                    self.command.wait_complete()


        # redis-based messaging from asynchrnonous threads - DO NOT USE THIS FACILITY FROM THE MAIN GUI THREAD!!!!!!

        # This is here to allow popups from threads, and NGC prompts - which run asynchronously with GUI thread.
        # Messages requiring user tool change confirmation during a part program
        # go to the gremlin message line.  During non-part program they get a pop-up.
        # Font spacing in Gremlin and in popups is very different, so are the reply instructions
        # Mesaage strings contain '*' for spaces, and '$$REPLY_TEXT$$' for requested actions
        # at prompt time these are substituted with the appropriate number of spaces and phrases
        # respectively.

        try:
            request = self.redis.lpop("TormachMessage")  #pop one off the queue
        except Exception as e:
            self.error_handler.write("Error in TormachRequest  %s" % str(e), ALARM_LEVEL_DEBUG)

        if request:
            self.error_handler.log("500ms periodic got request off TormachMessage msgq = %s" % request)

            self.hal['prompt-reply'] = 0      #set hal signal to waiting

            parsed_request = request.split(':')
            if "AnswerKey" in parsed_request[0]:   #break down "AnswerKey:key:message" structure
                self.notify_answer_key = parsed_request [1]
                message =  parsed_request[2]
            else:
                message = parsed_request[0]   #it's all just a message

            if self.program_running():
                if message:
                    message = message.replace('*', ' ')
                    message = message.replace('$$REPLY_TEXT$$', 'Press cycle start')
                    self.set_message_line_text(message)
                if self.notify_answer_key and message:
                    self.notify_at_cycle_start = True

                # user now presses cycle start, stop or cancel - see those callbacks for setting prompt channel hal

                # usually we're waiting for a manual tool change request so unlock the door
                # so they could actually accomplish that.
                self.unlock_enclosure_door()

            else:
                message = message.replace('*', ' ')
                message = message.replace('$$REPLY_TEXT$$', 'Click OK to continue')
                dialog = popupdlg.ok_cancel_popup(self.window, message)
                dialog.run()
                ok_cancel_response = dialog.response
                dialog.destroy()

                # Force necessary window repainting to make sure message dialog is fully removed from screen
                ui_misc.force_window_painting()

                if ok_cancel_response == gtk.RESPONSE_OK:
                    self.redis.hset("TormachAnswers", self.notify_answer_key,"Y")
                    self.ensure_mode(linuxcnc.MODE_MDI)
                    self.hal['prompt-reply'] = 1        #set hal to OK - need this pin incase a MDI M6 line was issued
                else:
                    self.redis.hset("TormachAnswers", self.notify_answer_key,"!")
                    self.ensure_mode(linuxcnc.MODE_MDI)
                    self.hal['prompt-reply']= 2          #set hal to CANCEL - need this pin incase a MDI M6 line was issued


        '''
        # if the ATC does not come up while system is not in RESET notify user and switch to manual
        if self.atc.operational and self.hal['atc-device-status'] == False and self.status.task_state == linuxcnc.STATE_ON:
            if self.atc_hardware_check_stopwatch.get_elapsed_seconds() >= 15:    # give 15 full second to stay broken.Hal startup o recovery may need some time here
                self.error_handler.write('Check ATC USB cabling, or fuses. Switching mill to manual toolchange. Repair problem. To re-enable, click ATC in Settings tab.')

                #switch to manual
                self.atc.disable()                                      #now panic! we need human help to reconnect
                self.hide_atc_diagnostics()
                self.checkbutton_list['use_manual_toolchange_checkbutton'].set_active(True)
        else:
            self.atc_hardware_check_stopwatch.restart()  # we're in the clear now
        '''

        # if the ATC does not come up while system is not in RESET notify user and switch to manual
        if self.atc.operational:
            if self.hal['atc-device-status'] == False and self.status.task_state == linuxcnc.STATE_ON:
                if self.atc_hardware_check_stopwatch.get_elapsed_seconds() >= 20:    # give 20 full second to stay broken.Hal startup o recovery may need some time here
                    self.error_handler.write('Check ATC USB cabling, or fuses. Switching mill to manual toolchange. Repair problem. To re-enable, click ATC in Settings tab.')

                    #switch to manual
                    self.atc.disable()                                      #now panic! we need human help to reconnect
                    self.hide_atc_diagnostics()
                    self.settings.checkbutton_list['use_manual_toolchange_checkbutton'].set_active(True)
            else:
                self.atc_hardware_check_stopwatch.restart()  # we're in the clear now

            # see if the ATC needs a firmware update
            if not machine_busy:
                if self.atc.does_atc_firmware_need_update():
                    # tell pathpilotmanager to run the atc firmware update utility after all of lcnc is torn down
                    self.program_exit_code = EXITCODE_UPDATE_ATC_FIRMWARE
                    self.quit()
                    return

        #---------------------------------------------------------------------------------
        # When the atc board is not communicating with the draw bar - both vfd and drawbar
        #    hal pins assert
        #----------------------------------------------------------------------------------
        if self.atc.operational and self.status.task_state == linuxcnc.STATE_ON \
           and self.hal['atc-vfd-status'] and self.hal['atc-draw-status'] \
           and self.only_one_cable_warning == False:
            if self.atc_cable_check_stopwatch.get_elapsed_seconds() >= 15:  # it's been steadily broken for 15 seconds, ok to alert

                self.only_one_cable_warning = True
                self.error_handler.write('Check ATC to Drawbar cabling, or fuses. Switching mill to manual toolchange. Repair problem. To re-enable, click ATC in Settings tab.')

                #switch to manual - user can fix this and try again.
                self.atc.disable()                                      #now panic! we need human help to reconnect
                self.hide_atc_diagnostics()
                self.settings.checkbutton_list['use_manual_toolchange_checkbutton'].set_active(True)

            else:
                self.atc_cable_check_stopwatch.restart()   # reset checker timer - not broken anymore


        # active gcodes label
        if not self.suppress_active_gcode_display:
            active_gcodes = self.active_gcodes()
            self.active_gcodes_label.set_text(" ".join(active_gcodes))

        self.update_spindle_direction_display()

        # reset button
        if self.status.task_state == linuxcnc.STATE_ESTOP or \
           self.status.task_state == linuxcnc.STATE_ESTOP_RESET or \
           self.status.task_state == linuxcnc.STATE_OFF:
            self.load_reset_image('blink')    # blink
            self.hal['console-led-blue'] = not self.hal['console-led-blue']
            self.hide_m1_image()
            self.unlock_enclosure_door()
        else:
            # not in ESTOP or RESET or OFF
            # load white image
            self.load_reset_image('white')
            self.hal['console-led-blue'] = False
            self.suppress_active_gcode_display = False

        if self.hal['machine-ok'] == False:
            # machine-ok is False
            if self.estop_alarm == False and self.display_estop_msg:
                # only do this once per press press of reset
                # and don't alarm at startup
                self.display_estop_msg = False
                self.error_handler.write(ESTOP_ERROR_MESSAGE, ALARM_LEVEL_MEDIUM)

                self.call_ui_hook('estop_event')
                self.hardkill_coolant = True

                # unreference X, Y, and Z
                if self.status.homed[0]:
                    self.command.unhome(0)
                    self.command.wait_complete()
                if self.status.homed[1]:
                    self.command.unhome(1)
                    self.command.wait_complete()
                if self.status.homed[2]:
                    self.command.unhome(2)
                    self.command.wait_complete()

                self.unlock_enclosure_door()

            # set to true to prevent these messages from stacking up.
            # cleared in reset button handler
            self.estop_alarm = True
            self.limit_switches_seen = 0

        else:
            # machine-ok is True
            # check limit switches X Y Z status

            if self.limit_switches_seen != 0:

                # here is where limit switch error messages get generated after a 600 millisecond delay.
                # that insures that we've been through the 500ms periodic once before.  This is needed
                # so that machine-ok has a chance to go down in a real e-stop power cycle scenario and
                # we don't generate additional red herring limit switch error messages.

                # we don't have to check if we were homing in here because self.limit_switches_seen is only
                # set by limit switch errors reported by LinuxCNC (and it doesn't do that during homing).

                time_now = time.time()
                if self.limit_switches_seen & 1:
                    if (time_now - self.limit_switches_seen_time) >= 0.6:
                        error_msg = X_LIMIT_ERROR_MESSAGE
                        if self.status.homed[0]:
                            self.command.unhome(0)
                            self.command.wait_complete()
                            self.error_handler.log("X unhomed")

                        if self.settings.door_sw_enabled and self.machineconfig.shared_xy_limit_input():
                            # x and y limit switches are ganged together, must do both
                            error_msg = X_Y_LIMIT_ERROR_MESSAGE
                            if self.status.homed[1]:
                                self.command.unhome(1)
                                self.command.wait_complete()
                                self.error_handler.log("Y unhomed")

                        self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
                        self.limit_switches_seen &= ~1

                if self.limit_switches_seen & 2:
                    if (time_now - self.limit_switches_seen_time) >= 0.6:
                        error_msg = Y_LIMIT_ERROR_MESSAGE
                        if self.status.homed[1]:
                            self.command.unhome(1)
                            self.command.wait_complete()
                            self.error_handler.log("Y unhomed")

                        if self.settings.door_sw_enabled and self.machineconfig.shared_xy_limit_input():
                            # x and y limit switches are ganged together, must do both
                            error_msg = X_Y_LIMIT_ERROR_MESSAGE
                            if self.status.homed[0]:
                                self.command.unhome(0)
                                self.command.wait_complete()
                                self.error_handler.log("X unhomed")

                        self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
                        self.limit_switches_seen &= ~2

                if self.limit_switches_seen & 4:
                    if (time_now - self.limit_switches_seen_time) >= 0.6:
                        error_msg = Z_LIMIT_ERROR_MESSAGE
                        if self.status.homed[2]:
                            self.command.unhome(2)
                            self.command.wait_complete()
                            self.error_handler.log("Z unhomed")
                        self.error_handler.write(error_msg, ALARM_LEVEL_MEDIUM)
                        self.limit_switches_seen &= ~4

                # get new info
                self.status.poll()

        # tool DRO
        if not self.dro_list['tool_dro'].masked:
            display_tool = self.status.tool_in_spindle
            if display_tool == -1 : display_tool = 0
            self.dro_list['tool_dro'].set_text(self.dro_short_format % display_tool)

        # work dro label
        self.current_work_offset_name = self.get_work_offset_name_from_index(self.status.g5x_index)
        if self.current_work_offset_name != self.prev_work_offset_name:
            self.prev_work_offset_name = self.current_work_offset_name
            self.work_offset_label.set_markup('<span weight="bold" font_desc="Roboto Condensed 12" foreground="white">POS IN {:s}</span>'.format(self.current_work_offset_name))

        gremlin_redraw_needed = False

        # Check if rotation has changed
        if not isequal(self.prev_self_rotation_xy, self.status.rotation_xy):
            # X/Y rotation has changed so set font indicate
            self.error_handler.write("rotation_xy has changed to: %f" % self.status.rotation_xy, ALARM_LEVEL_DEBUG)
            self.prev_self_rotation_xy = self.status.rotation_xy
            if self.status.rotation_xy == 0:
                self.dro_list['x_dro'].modify_font(self.xy_dro_font_description)
                self.dro_list['y_dro'].modify_font(self.xy_dro_font_description)
            else:
                self.dro_list['x_dro'].modify_font(self.rotation_xy_dro_font_description)
                self.dro_list['y_dro'].modify_font(self.rotation_xy_dro_font_description)

            # flag a gremlin reload (only acted upon if we aren't executing a program)
            gremlin_redraw_needed = True

        # NOTE: as a workaround for slow UI refreshes, you can remove modes from this list to suppress redraw
        # due to that mode change (e.g. user change via MDI)
        change_flags = self.test_changed_active_g_codes([
            linuxcnc.G_CODE_PLANE,
            linuxcnc.G_CODE_CUTTER_SIDE,
            linuxcnc.G_CODE_UNITS,
            linuxcnc.G_CODE_DISTANCE_MODE,
            linuxcnc.G_CODE_RETRACT_MODE,
            linuxcnc.G_CODE_LATHE_DIAMETER_MODE,
            linuxcnc.G_CODE_DISTANCE_MODE_IJK,
        ])
        gremlin_redraw_needed |= max(change_flags.values())

        # metric/imperial switch
        self.update_gui_unit_state()

        #coolant button LED

        if self.hal['coolant'] != self.coolant_status:
            self.coolant_status = self.hal['coolant']

        if (self.hal['mist'] != self.mist_status):
            self.mist_status = self.hal['mist']

        if self.mist_status or self.coolant_status:
            self.set_image('coolant_image', 'Coolant-Green_11.png')
        else:
            self.set_image('coolant_image', 'Coolant-Black_11.png')


        # update self.s_word
        if self.s_word != self.status.settings[2]:
            self.s_word = self.status.settings[2]
            if not ((self.hal['spindle-min-speed'] <= self.s_word <= self.hal['spindle-max-speed']) or self.s_word == 0.0):
                self.error_handler.write('Invalid S command of %d.  RPM must be between %d and %d in the current belt position.' % (self.s_word, self.hal['spindle-min-speed'], self.hal['spindle-max-speed']), ALARM_LEVEL_LOW)

        # update elapsed time and time remaining label widgets
        self.update_gcode_time_labels()

        # the gremlin view may need a poke as it could be tracking the current tool and only showing that tool path
        self.gremlin_options.periodic_500ms()

        #TODO refactor similar to home switch code, vectorize
        if not machine_executing_gcode:
            if not is_tuple_equal(self.current_g5x_offset, self.status.g5x_offset):
                self.error_handler.log("500ms status.g5x_offset {:s} vs. current_g5x_offset {:s}".format(self.status.g5x_offset, self.current_g5x_offset))
                self.current_g5x_offset = self.status.g5x_offset
                gremlin_redraw_needed = True

            if not is_tuple_equal(self.current_g92_offset, self.status.g92_offset):
                self.error_handler.log("500ms status.g92_offset {:s} vs. current_g92_offset {:s}".format(self.status.g92_offset, self.current_g92_offset))
                self.current_g92_offset = self.status.g92_offset
                gremlin_redraw_needed = True

            # Now kick off the redraw as long as the ATC isn't busy doing something.  The ATC thread does motion with G53 block level overrides and
            # sometimes we pick that up as an 'offset change' that needs a redraw, but not really.  Either way, we're just kicking the redraw
            # down the road a little since it isn't safe to do right now.  The redraw ends up having to do some linuxcnc.command channel mode changes
            # which interrupt some ATC command channel work and things error out.
            if gremlin_redraw_needed:
                if self.atc.in_a_thread.is_set():
                    self.error_handler.log("500ms periodic skipping a gremlin redraw due to ATC thread busy.  g5x_index={:d}".format(self.status.g5x_index))
                else:
                    self.error_handler.log("500ms periodic kicking off gremlin redraw because it saw offset change.  g5x_index={:d}".format(self.status.g5x_index))
                    self.redraw_gremlin()
                gremlin_redraw_needed = False

            self.update_jog_leds()
            if self.notebook_locked:
                self.show_enabled_notebook_tabs()
                self.notebook_locked = False
                self.stats_mgr.update_gcode_cycletimes()
                self.unlock_enclosure_door()

            # spindle rpm dro
            if not self.dro_list['spindle_rpm_dro'].masked:
                if self.hal['spindle-on']:
                    # doesn't matter what the state of the door switch and max door open stuff is, just show them what is
                    # going on as the thing is spinning so they should get the most accurate feedback we have available.
                    self.dro_list['spindle_rpm_dro'].set_text(self.dro_short_format % abs(self.hal['spindle-speed-out']))
                else:
                    self.dro_list['spindle_rpm_dro'].set_text(self.dro_short_format % abs(self.s_word))

            # feed per rev and per rpm
            if not self.dro_list['feed_per_min_dro'].masked:
                if self.moving():
                    feed_per_min = self.status.current_vel * 60 * self.get_linear_scale()
                    self.dro_list['feed_per_min_dro'].set_text(self.dro_medium_format % feed_per_min)
                else:
                    self.f_word = abs(self.status.settings[1])
                    self.dro_list['feed_per_min_dro'].set_text(self.dro_medium_format % abs(self.f_word))

            # display active g code on settings screen
            if self.current_notebook_page_id == "notebook_settings_fixed":
                if not self.suppress_active_gcode_display:
                    self.gcodes_display.highlight_active_codes(self.active_gcodes())

            self.load_cs_image('dark')
            if self.current_notebook_page_id == "notebook_offsets_fixed" and not machine_busy: # don't update while probing a tool length with ETS, or CPU usage goes way up
                self.refresh_touch_z_led()
                # don't refresh liststore when user is trying to click into it!!
                if self.window.get_focus() == None:
                    self.highlight_offsets_treeview_row()
                self.zero_height_gauge_show_or_hide()
                if self.work_probe_in_progress and \
                   self.status.interp_state == linuxcnc.INTERP_IDLE:
                    # Interp idle after work probe, assume completed
                    self.refresh_work_offset_liststore()
                    self.work_probe_in_progress = False

            elif self.current_notebook_page_id == 'atc_fixed' and self.atc.operational: #update the tray, and update drawbar state LED
                self.atc.display_tray()
                if self.hal["atc-draw-status"]:
                    self.set_image('atc_drawbar_image', 'Drawbar-Up-Green.png')
                else:
                    self.set_image('atc_drawbar_image', 'Drawbar-Down-Green.png')
            elif self.current_notebook_page_id == 'probe_fixed':
                self.mill_probe.periodic_500ms()

            elif self.current_notebook_page_id == 'alarms_fixed':
                if self.settings.usbio_enabled: self.refresh_usbio_interface()
                if self.atc.operational: self.refresh_atc_diagnostics()

            # temp kludge - TODO: understand limit overrides.
            # all of the below with regard to limit switches only works if we "see" the limit switch active.
            # it could have been very briefly active, hence the handling abovew
            '''
            if not self.first_run:
                # limit switch overrides
                if (self.status.limit[0] == 3) or (self.status.limit[1] == 3) or (self.status.limit[2] == 3):
                    self.command.override_limits()
            '''

            # axis ref'ed button LEDs
            self.x_referenced = self.status.homed[0]
            self.y_referenced = self.status.homed[1]
            self.z_referenced = self.status.homed[2]
            self.a_referenced = self.status.homed[3]
            if self.x_referenced != self.prev_x_referenced:
                self.prev_x_referenced = self.x_referenced
                if self.x_referenced:
                    self.set_image('ref_x_image', 'Ref_X_Green.png')
                else:
                    self.set_image('ref_x_image', 'Ref_X_Black.png')

            if self.y_referenced != self.prev_y_referenced:
                self.prev_y_referenced = self.y_referenced
                if self.y_referenced:
                    self.set_image('ref_y_image', 'Ref_Y_Green.png')
                else:
                    self.set_image('ref_y_image', 'Ref_Y_Black.png')

            if self.z_referenced != self.prev_z_referenced:
                self.prev_z_referenced = self.z_referenced
                if self.z_referenced:
                    self.set_image('ref_z_image', 'Ref_Z_Green.png')
                else:
                    self.set_image('ref_z_image', 'Ref_Z_Black.png')

            if self.a_referenced != self.prev_a_referenced:
                # a is not a limit sw, so we never want it to come unreffed on trigger.  Need to look into this.
                if self.a_referenced:
                    self.set_image('ref_a_image', 'Ref_A_Green.png')
                else:
                    self.set_image('ref_a_image', 'Ref_A_Black.png')

        else:
            # machine is running a g code prorgram
            # lock the notebook
            if not self.notebook_locked:
                self.hide_notebook_tabs()
                self.notebook_locked = True

            # if we're running a program, use S value from HAL spindle-speed-out and F value from status.current_vel
            feed_per_min = self.status.current_vel * 60 * self.get_linear_scale()
            self.dro_list['spindle_rpm_dro'].set_text(self.dro_short_format % abs(self.hal['spindle-speed-out']))
            self.dro_list['feed_per_min_dro'].set_text(self.dro_medium_format % feed_per_min)

            # CS button
            if self.single_block_active or self.feedhold_active.is_set() or self.m01_break_active:
                if (self.status.current_vel == 0) and (self.maxvel_override_adjustment.get_value() != 0):
                    self.load_cs_image('blink')
                else:
                    self.load_cs_image('green')
            else:
                self.load_cs_image('green')

        self.update_tlo_label()

        if machine_busy:
            if not self.dros_locked:
                self.dros_locked = True
                # lock out DROs
                for name, dro in self.dro_list.iteritems():
                    dro.set_can_focus(False)
        else:
            # if gcode file is loaded and has changed on disk since loading, reload it
            if self.current_gcode_file_path != '':
                self.check_for_gcode_program_reload()

            # check custom thread files for changes, reload if necessary
            self.thread_custom_file_reload_if_changed()

            if self.dros_locked:
                self.dros_locked = False
                # unlock DROs
                for name, dro in self.dro_list.iteritems():
                    dro.set_can_focus(True)
            # catch need to refresh tool treeview from 'move and set tool length' button
            if self.tool_liststore_stale > 0:
                self.tool_liststore_stale -= 1
                if self.tool_liststore_stale == 0:
                    self.refresh_tool_liststore(forced_refresh=True)


        # debug info - observe mode/status changes
        # this is far from perfect: the mode can change and return during time elapsed between these checks
        if self.status.task_mode != self.prev_lcnc_task_mode:
            # state changed, print to console
            self.error_handler.write('LinuxCNC status.task_mode change was %s is now %s' % (self.get_lcnc_mode_string(self.prev_lcnc_task_mode), self.get_lcnc_mode_string(self.status.task_mode)), ALARM_LEVEL_DEBUG)
            self.prev_lcnc_task_mode = self.status.task_mode
            #print '  interp_state %s' % (self.get_lcnc_interp_string(self.status.interp_state))

        if self.prev_lcnc_interp_state != self.status.interp_state:
            # interpreter state changed
            self.error_handler.write('LinuxCNC interp_state change was %s is now %s' % (self.get_lcnc_interp_string(self.prev_lcnc_interp_state), self.get_lcnc_interp_string(self.status.interp_state)), ALARM_LEVEL_DEBUG)
            self.prev_lcnc_interp_state = self.status.interp_state

            # kludge to rewind program after interp goes idle (usually when program is done at M30)
            if "IDLE" in self.get_lcnc_interp_string(self.status.interp_state) and not self.first_run:
                self.gcodelisting_mark_start_line(1)

            # State changes may result from M01 and a following cycle
            # start, display/hide any image specified in a comment
            # following M01
            if self.status.interp_state == linuxcnc.INTERP_PAUSED:
                self.show_m1_image()
                self.lineno_for_last_m1_image_attempt = self.status.current_line
                self.unlock_enclosure_door()
                # prototype alert code
                #self.send_m1_alert()

        if self.status.interp_state == linuxcnc.INTERP_PAUSED:
            # we may have two M00 or M01 breaks in a row that try to show images.
            # in that situation, there isn't a state change, but the self.status.current_line will have changed
            if self.lineno_for_last_m1_image_attempt != self.status.current_line:
                self.show_m1_image()
                self.unlock_enclosure_door()
                self.lineno_for_last_m1_image_attempt = self.status.current_line

        if self.prev_task_state != self.status.task_state:
            self.error_handler.write("status.task_state was %s is now %s" % (self.get_lcnc_state_string(self.prev_task_state), self.get_lcnc_state_string(self.status.task_state)), ALARM_LEVEL_DEBUG)
            self.prev_task_state = self.status.task_state

        self.update_scanner_state()

        self.mill_probe.update_ring_gauge_diameter()

        # log abnormal changes in cpu utilization
        usage = self.proc.cpu_percent()
        usage_delta = abs(usage - self.cpu_usage)
        if usage > LOG_CPU_USAGE_THRESHOLD_NOISEFLOOR and (usage_delta > 50 or usage > LOG_CPU_USAGE_THRESHOLD_ALWAYS):
            self.error_handler.write("CPU usage was %.1f, is now %.1f" % (self.cpu_usage, usage), ALARM_LEVEL_DEBUG)
            self.cpu_usage = usage


    def update_scanner_state(self):
        if self.scanner is None:
            return
        status_label = self.get_obj('scanner_scan_status_label')
        if not self.scanner.status_queue.empty():
            s = self.scanner.status_queue.get()
            #logging.debug("At point {0}, completed {1}".format(s[0],s[1]))
            if len(s[0]):
                status_label.set_markup(self.format_dro_string('Points done: {0}'.format(s[1]),11))
            else:
                status_label.set_markup(self.format_dro_string('--',11))
        elif self.scanner.complete_event.is_set():
            status_label.set_markup(self.format_dro_string('Scan Complete',11))

    def update_gui_unit_state(self):
        is_metric = self.status.gcodes[linuxcnc.G_CODE_UNITS] == 210
        if self.g21 == is_metric:
            return

        self.g21 = is_metric

        # swap button art on jog step sizes
        self.clear_jog_LEDs()
        self.set_jog_LEDs()
        # store off in redis for startup in same mode next time.
        self.redis.hset('machine_prefs', 'g21', self.g21)
        jog_ix = self.hal['jog-gui-step-index']
        if self.g21:
            self.jog_metric_scalar = 10
            self.hal['jog-is-metric'] = True
            self.gremlin.grid_size = (10.0/25.4)
            self.ttable_conv = 25.4
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g21()[jog_ix]
        else:
            self.jog_metric_scalar = 1
            self.hal['jog-is-metric'] = False
            self.gremlin.grid_size = 0.5
            self.ttable_conv = 1.0
            self.jog_increment_scaled = self.machineconfig.jog_step_increments_g20()[jog_ix]
        self.gremlin.queue_draw()

        # refresh of Offsets tab lengths and diameters
        self.refresh_tool_liststore()

        self.gremlin_options.update_unit_state()

        #TODO update Scanner DRO's?

    # Utility functions for position translation
    #FIXME doesn't handle axis rotation
    def to_local_position(self,global_position,axis = None):
        #FIXME needs well-formatted input
        if axis is None :
            return [self.get_axis_scale(ind) * (global_position[ind] - self.status.g5x_offset[ind] - self.status.tool_offset[ind] - self.status.g92_offset[ind]) for ind in range(4)]
        else:
            return self.get_axis_scale(axis) * (global_position - self.status.g5x_offset[axis] - self.status.tool_offset[axis] - self.status.g92_offset[axis])

    def to_global_position(self,local_position,axis=None):
        #FIXME needs well-formatted input
        if axis is None:
            return [(local_position[ind] + self.status.g5x_offset[ind] + self.status.tool_offset[ind] + self.status.g92_offset[ind] / self.get_axis_scale[ind]) for ind in range(4)]
        else:
            return (local_position + self.status.g5x_offset[axis] + self.status.tool_offset[axis] + self.status.g92_offset[axis] / self.get_axis_scale(axis))

    def get_local_position(self):
        if self.status.rotation_xy == 0:
            return [self.get_axis_scale(ind) * (self.status.actual_position[ind] - self.status.g5x_offset[ind] - self.status.tool_offset[ind] - self.status.g92_offset[ind]) for ind in range(4)]
        else:
            x = self.status.actual_position[0] - self.status.g5x_offset[0] - self.status.tool_offset[0]
            y = self.status.actual_position[1] - self.status.g5x_offset[1] - self.status.tool_offset[1]
            t = math.radians(-1.0 * self.status.rotation_xy)
            xr = x * math.cos(t) - y * math.sin(t)
            yr = x * math.sin(t) + y * math.cos(t)
            # G92 offsets are not rotated - the apply post-rotation (should check with Smid)
            x = xr - self.status.g92_offset[0]
            y = yr - self.status.g92_offset[1]
            z = self.get_axis_scale(2) * (self.status.actual_position[2] - self.status.g5x_offset[2] - self.status.tool_offset[2] - self.status.g92_offset[2])
            a = self.get_axis_scale(3) * (self.status.actual_position[3] - self.status.g5x_offset[3] - self.status.tool_offset[3] - self.status.g92_offset[3])
            return [x, y, z, a]

    def redraw_gremlin(self):
        # Large files can take a long time so give some feedback with busy cursor
        # (but only if we know this file causes gremlin.load to be slow - otherwise
        # the flashing related to the plexiglass is annoying)
        if self.gremlin:
            with plexiglass.ConditionalPlexiglassInstance(self.gremlin_load_needs_plexiglass, singletons.g_Machine.window) as p:
                # redraw screen with new offset
                # be sure to switch modes to cause an interp synch, which
                # writes out the var file.
                # this mode change is CRITICAL to getting the gremlin to redraw the toolpath
                # in the correct spot.  Without it, the gremlin can be forced to redraw, but
                # it doesn't draw the toolpath in the new spot if the work coordinate or rotation has changed
                self.ensure_mode(linuxcnc.MODE_MANUAL)
                self.ensure_mode(linuxcnc.MODE_MDI)
                self.gremlin.clear_live_plotter()
                self.gremlin.load()
                self.gremlin.queue_draw()  # force a repaint
                #Note:not catching warnings here since it's assumed the user has
                #already seen them

    def check_limits(self,abs_position,axis):
        min_bound = self.status.axis[axis]['min_position_limit']
        max_bound = self.status.axis[axis]['max_position_limit']

        if abs_position < min_bound or abs_position > max_bound:
            return False
        else:
            return True

    def validate_local_position(self,local_position,axis):
        abs_pos = self.to_global_position(local_position,axis)
        if not self.check_limits(abs_pos,axis):
            err_msg = 'Position {0} on axis {1} is outside of machine limits!'.format(local_position,axis)
            return False,err_msg
        return True, ''

    def get_probe_tripped_position(self):
        return [self.get_axis_scale(ind) * (self.status.probed_position[ind] - self.status.g5x_offset[ind] - self.status.tool_offset[ind] - self.status.g92_offset[ind]) for ind in range(3)]


    def scanner_periodic(self):
        tab_title = None
        if self.scanner:
            if (self.current_notebook_page_id == 'scanner_fixed'):
                active_camera_child = self.camera_notebook.get_nth_page(self.camera_notebook.get_current_page())
                tab_title = self.camera_notebook.get_tab_label_text(active_camera_child)
                self.scanner.periodic_update(tab_title)

        return True


    def coolant_periodic(self):
        # Coolant: watch for LinuxCNC to pulse coolant pin.
        # when it does copy finalstate tormach.coolant HAL pin. It will be
        # pulsed for .1 second by linuxcnc , so we debounce and wait for it
        # to settle to avoid spurious state changes

        self.coolant_ticker += 1   #tick it up
        self.mist_ticker += 1

        if not self.hardkill_coolant:

            if (self.prev_coolant_iocontrol != self.hal["coolant-iocontrol"]) :
                self.coolant_apply_at = self.coolant_ticker + 4  #schedule after pulse settles


            if  self.coolant_ticker == self.coolant_apply_at :
                self.hal['coolant'] = self.hal["coolant-iocontrol"]
                self.coolant_ticker = self.coolant_apply_at = 0           #new game

            if (self.prev_mist_iocontrol != self.hal["mist-iocontrol"]) :
                self.mist_apply_at = self.mist_ticker + 4  #schedule after pulse settles


            if  self.mist_ticker == self.mist_apply_at :
                self.hal['mist'] = self.hal["mist-iocontrol"]
                self.mist_ticker = self.mist_apply_at = 0

        if self.hardkill_coolant:

            self.hal['mist'] = self.hal['coolant'] = False
            if self.coolant_ticker > 20:
                self.coolant_ticker = 0
                self.hardkill_coolant = False

        # current becomes previous
        self.prev_coolant_iocontrol = self.hal["coolant-iocontrol"]
        self.prev_mist_iocontrol = self.hal["mist-iocontrol"]

    def check_console_inputs(self):
        if self.hal['console-cycle-start']:
            self.enqueue_button_press_release(self.button_list['cycle_start'])
            self.hal['console-cycle-start'] = False

        if self.hal['console-feedhold']:
            self.enqueue_button_press_release(self.button_list['feedhold'])
            self.hal['console-feedhold'] = False

        #check if console is connected on USB, disable override sliders if so
        if self.hal['console-device-connected'] == True:
            self.set_feedrate_override(self.hal['console-feed-override'] * 100.0)
            self.set_spindle_override(self.hal['console-rpm-override'] * 100.0)
            self.set_maxvel_override(self.hal['console-rapid-override'] * 100.0)


    # called every 50 milliseconds to update faster changing indicators
    def status_periodic_50ms(self):
        self.check_console_inputs()

        # check button events from keyboard shortcuts
        self.check_keyboard_shortcut_fifo()

        # lazily poke the tooltip manager Real Soon Now
        glib.idle_add(tooltipmgr.TTMgr().on_periodic_timer)

        # get new info
        self.status.poll()
        self.axis_motor_poll()

        # The following updates are always performed, regardless of machine state

        # Apply the most recent value we've seen from dragging any override sliders
        # The most recent value from the UI callbacks is stored and only acted upon
        # during this 50ms periodic.
        self.apply_newest_override_slider_values()

        # Position DROs and DTG labels:
        pos_scaled = self.get_local_position()

        # Get scaled distance to go for all axes
        dtg_scaled = [self.status.dtg[ind] * self.get_axis_scale(ind) for ind in range(4)]


        #For each axis in the DRO list, check if it's masked and update the position if need be
        for n,dro in enumerate(self.axes.dros):
            if not self.dro_list[dro].masked:
                self.dro_list[dro].set_text(self.dro_long_format % pos_scaled[n])
            #Regardless, update the DTG value
            dtg_label = self.get_obj(self.axes.dtg_labels[n])
            dtg_label.set_text(self.dro_long_format % dtg_scaled[n] )

        self.coolant_periodic()

        self.usb_IO_periodic()

        self.process_halpin_callbacks()

        # door open / closed status check
        self.door_open_status = self.hal['enc-door-open-status']
        if self.machineconfig.has_door_lock() and self.settings.door_sw_enabled:
            self.door_locked_status = self.hal['enc-door-locked-status']
        if self.door_open_status != self.prev_door_open_status:
            self.prev_door_open_status = self.door_open_status
            if self.door_open_status and self.program_running(False):
                # pause program
                self.error_handler.write("Pausing program because door was opened", ALARM_LEVEL_DEBUG)
                self.program_paused_for_door_sw_open = True
                self.command.auto(linuxcnc.AUTO_PAUSE)
                self.feedhold_active.set()
                self.set_image('feedhold_image', 'Feedhold-Green.jpg')
                if self.hal['coolant']:
                    self.hal['coolant'] = False

        # poll for errors
        error = self.error.poll()
        if error:
            error_kind, error_msg = error
            # do not immediately show limit switch messages that come from LinuxCNC.  we latch
            # that we've seen them and let the 500ms periodic UI cycle decide to show them or not
            # Real Soon Now.
            #
            # this avoids timing problems of these errors appearing before machine-ok
            # goes false after an estop power down of the mill
            # sometimes machine-ok goes false long before the limits activate
            # sometimes the limits go active before machine-ok goes false
            # which leads customers to belive they have bad limit switches when they don't.
            #
            # delaying has no bad effect because LinuxCNC auto transitions to ESTOP_RESET
            # without any help from the UI.
            if 'X axis limit switch active' in error_msg:
                self.limit_switches_seen |= 1
                self.limit_switches_seen_time = time.time()
            elif 'Y axis limit switch active' in error_msg:
                self.limit_switches_seen |= 2
                self.limit_switches_seen_time = time.time()
            elif 'Z axis limit switch active' in error_msg:
                self.limit_switches_seen |= 4
                self.limit_switches_seen_time = time.time()
            else:
                if error_kind == EMC_OPERATOR_DISPLAY_TYPE:
                    self.error_handler.write(error_msg, ALARM_LEVEL_LOW)
                else:
                    # display on UI
                    self.error_handler.write(error_msg)
                    if self.atc.in_a_thread.is_set():
                        self.atc.general_error.set()   #abort the ATC unit of work due to errors here

        if self.debugpage:
            self.debugpage.refresh_page()

        self.update_gcode_display()

        self.update_jogging()

        # the following updates are performed only if the current page requires it
        if self.current_notebook_page_id == 'notebook_offsets_fixed':
            self.update_mill_acc_input_leds()
            # height gauge update upon button press
            if self.hal['hg-button-changed'] and self.hal['hg-button-pressed']:
                self.hal['hg-button-changed'] = False
                self.on_height_gauge_button_press_event()
        elif self.current_notebook_page_id == 'alarms_fixed':
            self.update_mill_status_leds()
        elif self.current_notebook_page_id in ('probe_fixed', 'injector_fixed', 'atc_fixed'):
            self.update_mill_acc_input_leds()


    def update_mill_acc_input_leds(self):
        # diagnostic LEDs
        # probe input
        if bool(self.status.probe_val) != self.probe_tripped_display:
            self.probe_tripped_display = bool(self.status.probe_val)
            self.mill_probe.set_probe_input_leds(self.probe_tripped_display)
            if self.probe_tripped_display:
                self.set_image('ets_image', 'Sensor-set-LED.png')
                self.set_image('touch_entire_tray_ets_image', 'Sensor-set-LED.png')
                self.set_image('probe_sensor_set_image', 'Sensor-set-LED.png')
                self.set_image('injection_molder_image', 'Injection Molder Lit LED.png')
            else:
                self.set_image('ets_image', 'Sensor-set-No-LED.png')
                self.set_image('touch_entire_tray_ets_image', 'Sensor-set-No-LED.png')
                self.set_image('probe_sensor_set_image', 'Sensor-set-No-LED.png')
                self.set_image('injection_molder_image', 'Injection Molder.png')

    def update_mill_status_leds(self):
        # diagnostic LEDs
        # probe input
        self.set_indicator_led('acc_input_led', bool(self.status.probe_val))

        # machine ok LED
        self.refresh_machine_ok_led()

        # door sw LED
        if self.settings.door_sw_enabled:
            self.set_indicator_led('door_sw_led', self.door_open_status)
            if self.machineconfig.has_door_lock():
                self.set_indicator_led('door_lock_led', self.door_locked_status)
        else:
            self.set_indicator_led('door_sw_led', False)
            if self.machineconfig.has_door_lock():
                self.set_indicator_led('door_lock_led', False)

        # limit switch virtual LED updates
        for n,sw in enumerate(self.axes.home_switches):
            if self.settings.door_sw_enabled and (n == 0) and self.machineconfig.shared_xy_limit_input():
                # leave X axis switch off
                self.set_warning_led(self.axes.limit_leds[n], False)
                continue
            # Change button state only on change of state
            if bool(self.hal[sw]) != self.axes.at_limit_display[n]:
                self.axes.at_limit_display[n] = self.hal[sw]
                self.set_warning_led(self.axes.limit_leds[n],self.hal[sw])

        if self.machineconfig.has_ecm1():
            #if atc not running, we updated this LED, otherwise refresh_atc_diagnostics() does
            if not self.vfd_status_by_atc:
                running = (abs(self.hal['m200-vfd-rpm-feedback']) > 2)
                self.set_indicator_led('vfd_running_led', running)

            # vfd-fault LED is unknown to refresh_atc_diagnostics(), so update
            self.set_error_led('vfd_fault_led', self.hal['vfd-fault'])

        # this uses special led button images so can't use the common methods to light it
        if self.internet_checker.internet_reachable:
            self.set_image('internet_led', 'LED_button_green.png')
        else:
            self.set_image('internet_led', 'LED_button_black.png')


    def on_entry_loses_focus(self, widget, data=None):
        # get rid of text highlight if you click out of a dro that has highlighted text
        widget.select_region(0, 0)
        return False

    def set_work_offset(self, axis, dro_text):
        axis = axis.upper()  # X, Y, Z, A
        try:
            dro_val = float(dro_text)
        except:
            self.error_handler.write("%s DRO entry is not a number '%s'" % (axis, dro_text), ALARM_LEVEL_DEBUG)
            return

        axis_dict = {'X':0, 'Y':1, 'Z':2, 'A':3}
        axis_ix = axis_dict[axis]
        if not self.status.homed[axis_ix]:
            self.error_handler.write("Must reference {} axis before setting work offset.".format(axis), ALARM_LEVEL_MEDIUM)
            return

        current_work_offset = self.status.g5x_index

        # log the change to the status screen in case the operator forgot they're in the wrong work coordinate system
        # and just zero'd out a valuable number.
        work_offset_name = self.get_work_offset_name_from_index(current_work_offset)  # e.g. G55 or G59.1
        format_without_percent = self.dro_long_format[1:]
        msg_template = "{:s} {:s} axis work offset changed from {:" + format_without_percent + "} to {:" + format_without_percent + "}."
        old_value = self.status.g5x_offsets[current_work_offset][axis_ix] * self.get_linear_scale()

        offset_command = "G10 L20 P%d %s%.12f" % (current_work_offset, axis, dro_val)
        self.issue_mdi(offset_command)

        # need wait_complete or liststore refresh will read the old value
        self.command.wait_complete()
        self.status.poll()
        self.refresh_work_offset_liststore()

        new_value = self.status.g5x_offsets[current_work_offset][axis_ix] * self.get_linear_scale()
        msg = msg_template.format(work_offset_name, axis, old_value, new_value)
        self.error_handler.write(msg, ALARM_LEVEL_QUIET)

        # we don't actually kick off a gremlin redraw here because the 500ms periodic
        # also checks for work offset changes and rotation changes and will do it
        # whenever a program is not running.  That's quick enough.  Otherwise you
        # end up with TWO refreshes which with large programs takes FOREVER.



    # previously known as check_button_permissions() which was less obvious on the return value meaning
    # button permissions were refactored to be bitfield of permitted states - no longer a numerical level
    def is_button_permitted(self, widget):
        # move the button back, ditch focus.
        btn.ImageButton.unshift_button(widget)
        self.window.set_focus(None)

        # figure out what the current state of the machine is

        if self.program_running_but_paused() or self.mdi_running_but_paused():
            current_state = STATE_PAUSED_PROGRAM

        elif self.program_running():
            # we're running a g code program
            current_state = STATE_RUNNING_PROGRAM

            # we might be in an ATC tool change remap with a prompt on the gremlin
            # waiting for the user to manually change tools
            # in this rare situation, we want to enable the spindle range hi/lo button
            # because they can open the spindle door and change the belt position
            # to match the new tool that is going to be loaded
            # otherwise they have to manually tweak their g-code to insert M00 breaks
            # before any belt position changes.
            #
            # but we combine this with STATE_RUNNING_PROGRAM so that all the buttons that
            # are valid during that state are also valid in this situation.
            if self.hal['atc-ngc-running'] and self.notify_at_cycle_start:
                current_state |= STATE_RUNNING_PROGRAM_TOOL_CHANGE_WAITING_ON_OPERATOR

        elif self.moving():
            # machine is moving (e.g. jog, MDI) or atc is doing something
            current_state = STATE_MOVING
            if self.status.axis[0]['homing'] or self.status.axis[1]['homing'] or self.status.axis[2]['homing']:
                current_state = STATE_HOMING

        elif self.status.task_state == linuxcnc.STATE_ON:
            # machine is on, connected, not moving or running g code
            # is it referenced?
            if self.x_referenced and self.y_referenced and self.z_referenced:
                current_state = STATE_IDLE_AND_REFERENCED
            else:
                current_state = STATE_IDLE

        else:
            # machine is in ESTOP state
            current_state = STATE_ESTOP

        # is there an overlap between the current state of the machine
        # and the widget's permitted machine states?
        permitted = (widget.permitted_states & current_state) != 0

        # give the user a clue why if we're going to fail
        if not permitted:
            statetext = ''
            if (widget.permitted_states & STATE_ESTOP) != 0:
                statetext += 'e-stop, '
            if (widget.permitted_states & STATE_IDLE) != 0:
                statetext += 'reset, '
            if (widget.permitted_states & STATE_IDLE_AND_REFERENCED) != 0:
                statetext += 'referenced, '
            if (widget.permitted_states & STATE_HOMING) != 0:
                statetext += 'homing, '
            if (widget.permitted_states & STATE_MOVING) != 0:
                statetext += 'moving, '
            if (widget.permitted_states & STATE_PAUSED_PROGRAM) != 0:
                statetext += 'g-code program paused, '
            if (widget.permitted_states & STATE_RUNNING_PROGRAM) != 0:
                statetext += 'g-code program running, '
            if (widget.permitted_states & STATE_RUNNING_PROGRAM_TOOL_CHANGE_WAITING_ON_OPERATOR) != 0:
                statetext += 'g-code program running and waiting on manual tool change, '

            if len(statetext) > 0:
                statetext = statetext[:-2]   # slice off the trailing comma and space
            self.error_handler.write('Button only permitted when machine is in state(s): %s' % statetext, ALARM_LEVEL_LOW)

        return permitted

    def program_running(self, do_poll=False):
        # are we executing a g code program?
        if do_poll:
            # need fresh status data, ask for it
            self.status.poll()
        return self.status.task_mode == linuxcnc.MODE_AUTO and self.status.interp_state != linuxcnc.INTERP_IDLE

    def program_running_but_paused(self):
        return (self.status.task_mode == linuxcnc.MODE_AUTO) and (self.status.interp_state == linuxcnc.INTERP_PAUSED)

    """ Check if we are moving or running a motion command in coordinated mode.
    Can be used to check if feedhold should be allowed.
    """
    def command_in_progress(self, do_poll=False):
        if do_poll:
            # need fresh status data, ask for it
            self.status.poll()
        return self.status.interp_state != linuxcnc.INTERP_IDLE or self.status.queue > 0 or self.status.paused

    def ensure_mode(self, mode):
        self.status.poll() #if this isn't called, self.status.task_mode can get out of sync
        if self.status.task_mode == mode:
            # if already in desired mode do nothing
            return True
        if self.moving():
            # if running a program do nothing
            return False
        # set the desired mode
        self.error_handler.write("ensure_mode: changing LCNC mode to %s" % (self.get_lcnc_mode_string(mode)), ALARM_LEVEL_DEBUG)
        self.command.mode(mode)
        self.command.wait_complete()
        return True

    def on_height_gauge_button_press_event(self):
        try:
            store, tree_iter = self.treeselection.get_selected()
            # if no row is selected, the iter returned is "None" and the set will fail
            if tree_iter == None: return
            tool_number = store.get_value(tree_iter, 0)
            tool_length = self.hal['hg-height'] * self.get_linear_scale()
            self.issue_tool_offset_command('Z', tool_number, tool_length)
            store.set(tree_iter, 3, (self.dro_long_format % tool_length))
            if tool_number == self.status.tool_in_spindle:
                # apply offset right away if we are measuring the current tool
                self.issue_mdi('G43')
            # do not move to the next line - it is a source or overwriting
            # the next tool via mulitple presses of the button the USB gauge
        except:
            #FIXME don't do global exception handling
            self.error_handler.write("Height gauge error", ALARM_LEVEL_DEBUG)

    def check_tool_table_for_warnings(self, unique_tool_list):
        '''
        Return True if warnings were issued, False otherwise
        '''
        warnings = False
        # only pull over tool_table across status channel once and then examine locally within python.
        tool_table = self.status.tool_table
        for tool in unique_tool_list:
            # mill check for tool lengths that are 0
            if iszero(tool_table[tool].zoffset) and (tool != 0):
                # Found a tool offset that's zero. High risk of tool breakage as operator forgot to specify correct offset.
                warnings = True
                self.error_handler.write("Program uses tool {:d} which has a length of 0.  Please confirm tool table accuracy.".format(tool), ALARM_LEVEL_HIGH)

        return warnings

    def load_initial_tool_liststore(self):
        linear_scale = self.get_linear_scale()
        self.tool_table_file_mtime = os.stat(self.tool_table_filename).st_mtime

        # with 1000 tools now, this can take 4 or 5 seconds on a slow Brix controller.
        # toss up the plexiglass to we don't look like we're dead
        p = None
        if singletons.g_Machine:
            p = plexiglass.PlexiglassInstance(singletons.g_Machine.window)
            p.show()

        self.error_handler.log('Loading initial tool liststore')
        self.tool_liststore_prev_linear_scale = linear_scale
        self.tool_liststore.clear()

        # CRITICAL!
        # only reach through status once for all the tool data as it is VERY slow otherwise
        tool_table_status = self.status.tool_table

        for pocket in xrange(1, MAX_NUM_MILL_TOOL_NUM + 1):
            # only reach through status once for all the tool data as it is VERY slow otherwise
            toolstatus = tool_table_status[pocket]

            tool_num = toolstatus.id
            assert pocket == tool_num
            description = self.get_tool_description(tool_num,'')
            diameter = self.dro_long_format % (toolstatus.diameter * linear_scale)
            length = self.dro_long_format % (toolstatus.zoffset * linear_scale)
            background_color = '#E1B3B7'
            if pocket in self.gcode_program_tools_used:
                background_color = '#EB8891'

            self.tool_liststore.append([tool_num, description, diameter, length, None, background_color])

        self.error_handler.log('Loading initial tool liststore complete.')

        if p: p.destroy()


    def on_filter_tool_table_combobox_changed(self, widget, data=None):
        tooltipmgr.TTMgr().on_mouse_leave(widget)

        ix = widget.get_active()

        # each row in the list store is a string and the int constant for the filter type
        # so the [1] below plucks out the filter type constant from the row.
        self.filter_tool_table = self.filter_tool_table_liststore[ix][1]
        self.window.set_focus(None)
        self.refresh_tool_liststore(forced_refresh=True)

    def on_filter_work_offsets_combobox_changed(self, widget, data=None):
        tooltipmgr.TTMgr().on_mouse_leave(widget)

        ix = widget.get_active()

        # each row in the list store is a string and the int constant for the filter type
        # so the [1] below plucks out the filter type constant from the row.
        self.filter_work_offsets = self.filter_work_offsets_liststore[ix][1]
        self.window.set_focus(None)
        self.refresh_work_offset_liststore()

    def search_entry_key_press_event(self, widget, event, data=None):
        # Its annoying to have the tooltip up as you're trying to type in the search box so auto-dismiss it
        # on every key press.
        tooltipmgr.TTMgr().on_esc_key()

        if event.keyval == gtk.keysyms.Escape:

            if len(widget.get_text()) > 0:
                widget.set_text('')
            else:
                self.window.set_focus(None)
            return True  # eat the event

        return False   # keep propagating event


    def on_search_activate(self, widget):
        if len(widget.get_text()) == 0:
            # enter key on a blank line gives up focus so you can jog and navigate again
            self.window.set_focus(None)
        else:
            # Make the enter key behave the same as 'find next'
            ev = gtk.gdk.Event(gtk.gdk.KEY_PRESS)
            ev.keyval = gtk.keysyms.Down
            ev.window = widget.window
            widget.emit('key-press-event', ev)
            widget.emit('key-release-event', ev)


    def refresh_tool_liststore(self, forced_refresh=False):
        # if the tool table file has been changed by linuxcnc directly through gcode, that
        # triggers a forced refresh for us.
        current_mtime = os.stat(self.tool_table_filename).st_mtime
        if current_mtime != self.tool_table_file_mtime:
            self.tool_table_file_mtime = current_mtime
            forced_refresh = True

        linear_scale = self.get_linear_scale()

        if (self.tool_liststore_prev_linear_scale != linear_scale) or forced_refresh:

            if forced_refresh == True:
                self.error_handler.write('Refreshing tool liststore due to forced refresh', ALARM_LEVEL_DEBUG)
            else:
                self.error_handler.write('Refreshing tool liststore due to linear scale change', ALARM_LEVEL_DEBUG)

            self.tool_liststore_prev_linear_scale = linear_scale
            self.tool_liststore.clear()

            # CRITICAL!
            # only reach through status once for all the tool data as it is VERY slow otherwise
            tool_table_status = self.status.tool_table

            for pocket in xrange(1, MAX_NUM_MILL_TOOL_NUM + 1):
                toolstatus = tool_table_status[pocket]
                tool_num = toolstatus.id
                assert pocket == tool_num
                description = self.get_tool_description(tool_num)

                # apply tool table filtering
                include = False
                if self.filter_tool_table == FILTER_TOOL_TABLE_ALL_TOOLS:
                    include = True
                elif self.filter_tool_table == FILTER_TOOL_TABLE_USED_BY_GCODE and pocket in self.gcode_program_tools_used:
                    include = True
                elif self.filter_tool_table == FILTER_TOOL_TABLE_NONBLANK_DESCRIPTIONS and len(description) > 0:
                    include = True
                elif self.filter_tool_table == FILTER_TOOL_TABLE_NONZERO and (not iszero(toolstatus.diameter) or not iszero(toolstatus.zoffset)):
                    include = True

                if include:
                    diameter = self.dro_long_format % (toolstatus.diameter * linear_scale)
                    length = self.dro_long_format % (toolstatus.zoffset * linear_scale)
                    background_color = '#E1B3B7'
                    if pocket in self.gcode_program_tools_used:
                        background_color = '#EB8891'
                    self.tool_liststore.append([tool_num, description, diameter, length, None, background_color])

            self.error_handler.write('Refreshing tool liststore - complete.', ALARM_LEVEL_DEBUG)


    def update_tool_store(self, row, data):
        # data is a tuple of (column_number,data)
        # this method maps the column_number ('n') to the routine which will update
        # the tree_view and also the specific non-volatile storage.
        model = self.tool_treeview.get_model()
        for n,val in data:
            if n is 1: self.on_tool_description_column_edited(None,row,val,model)
            elif n is 2: self.set_tool_diameter(row,val,model)


    def refresh_work_offset_liststore(self):
        self.work_liststore.clear()
        # Stop a false positive on the iteritems() member below
        # pylint: disable=no-member
        for offset_index, o in self.status.g5x_offsets.iteritems():
            if offset_index < 1:
                # Ignore current offset
                continue
            name = self.get_work_offset_name_from_index(offset_index)

            keyname = 'G54.1 P{:d} desc'.format(offset_index)
            description = self.redis.hget('machine_prefs', keyname)
            if description == None: description = ''

            # apply work offset table filtering
            include = False
            if self.filter_work_offsets == FILTER_WORK_OFFSETS_ALL:
                include = True
            elif self.filter_work_offsets == FILTER_WORK_OFFSETS_USED_BY_GCODE and offset_index in self.gremlin.get_work_offsets_used():
                include = True
            elif self.filter_work_offsets == FILTER_WORK_OFFSETS_NONBLANK_DESCRIPTIONS and len(description) > 0:
                include = True
            elif self.filter_work_offsets == FILTER_WORK_OFFSETS_NONZERO:
                for ii in o[:4]:
                    if not iszero(ii):
                        include = True
                        break

            if include:
                idcol_background_color = '#E1B3B7'
                if offset_index in self.gremlin.get_work_offsets_used():
                    idcol_background_color = '#EB8891'

                # we highlight the current work offset in the table (assuming its visible based on filtering)
                background = 'WHITE'
                if self.status.g5x_index == offset_index:
                    background = ROW_HIGHLIGHT

                # the 8th element of the row is the offset index because with filtering we cannot rely on
                # row-1 == offset_index anymore.
                self.work_liststore.append(
                    [name] + [description] + ['%.4f' % (ii * self.get_linear_scale()) for ii in o[:4]]
                    + ['BLACK', background] + [offset_index] + [idcol_background_color])

        self.work_treeview.queue_draw()  # force repaint of the work offset treeview


    def get_ttfont_name(self, font_file_name):
        #from fontTools import ttLib

        FONT_SPECIFIER_NAME_ID = 4
        FONT_SPECIFIER_FAMILY_ID = 1

        name = ""
        family = ""

        if is_ttlib == True:
            try:
                font = ttLib.TTFont(font_file_name)
            except:
                return name, family
        else:
            self.error_handler.write('ttLib module not loaded. Is fontTools installed?', ALARM_LEVEL_LOW)
            return name, family

        """Get the short name from the font's names table"""
        for record in font['name'].names:
            if record.nameID == FONT_SPECIFIER_NAME_ID and not name:
                if '\000' in record.string:
                    name = unicode(record.string, 'utf-16-be').encode('utf-8')
                else:
                    name = record.string
            elif record.nameID == FONT_SPECIFIER_FAMILY_ID and not family:
                if '\000' in record.string:
                    family = unicode(record.string, 'utf-16-be').encode('utf-8')
                else:
                    family = record.string
            if name and family:
                break
        return name, family

    def set_response_cancel(self):
        if self.notify_at_cycle_start:  # is anyone waiting on us
            self.notify_at_cycle_start = False
            try:
                self.redis.hset("TormachAnswers",self.notify_answer_key,"!")  #start pressed message
                self.hal['prompt-reply'] = 2
                self.error_handler.write('prompt output pin set to 2 by cancel/reset', ALARM_LEVEL_DEBUG)
            except Exception as e:
                traceback_txt = "".join(traceback.format_exception(*sys.exc_info()))
                self.error_handler.write("Whooops! - Tormach message reply not set.  Exception: %s" % traceback_txt, ALARM_LEVEL_DEBUG)

        if self.hal['atc-ngc-running']:
            # we're aborting the atc ngc code - issue an M81 to restore modal state of user
            self.issue_mdi('M81')

        if self.atc.in_a_thread.is_set():
            self.atc.stop_reset.set()   #only if atc thread in progress
        if not self.atc.feed_hold_clear.is_set():
            self.atc.feed_hold_clear.set()  #  signal feedhold is now cleared
            return True
        return False

    @staticmethod
    def format_dro_string(input_string, fontsize):
        #TODO implement word spacing
        spaced_string = re.sub(' ','    ',input_string)
        spaced_string = re.sub(':','    :',spaced_string)
        return '<span weight="light" font_desc="Bebas {0}" font_stretch="ultracondensed" foreground="white" >{1}</span>'.format(fontsize, spaced_string)


    def delete_event(self, widget, event):
        self.error_handler.write('Alt-F4/delete_event detected. Simulating Exit button press.', ALARM_LEVEL_DEBUG)
        try:
            self.enqueue_button_press_release(self.button_list['exit'])
        except Exception as e:
            self.error_handler.write('enqueue button press failed', ALARM_LEVEL_DEBUG)
            msg = "An exception of type {0} occured, these were the arguments:\n{1!r}"
            self.error_handler.write(msg.format(type(e).__name__, e.args), ALARM_LEVEL_DEBUG)
        return True

    def create_jobassignment_gremlin(self, width, height):
        return JobAssignmentGremlin(self, width, height)


#--end 'mill'-------------------------------------------------------------------



def is_dro_masked(dro_list):
    for name, dro in dro_list.iteritems():
        if dro.masked == True:
            return True
    return False


class Tormach_Mill_Gremlin(gremlinbase.Tormach_Gremlin_Base):
    def __init__(self, ui, width, height):
        gremlinbase.Tormach_Gremlin_Base.__init__(self, ui, width, height)

        self.ui_view = 'p'
        self.g21 = self.status.gcodes[linuxcnc.G_CODE_UNITS] == 210
        if self.g21:
            self.grid_size = (10.0/25.4)
        else:
            self.grid_size = 0.5
        self.connect("button_press_event", self.on_gremlin_double_click)

    def init_fourth_axis(self):
        enable_a = False
        if self.ui.redis.hexists('machine_prefs', 'enable_fourth_axis_toolpath'):
            enable_a = self.ui.redis.hget('machine_prefs', 'enable_fourth_axis_toolpath') == 'True'
        if enable_a:
            self.enable_fourth_axis_toolpath_display(None)
        else:
            self.disable_fourth_axis_toolpath_display(None)

    def realize(self,widget):
        super(Tormach_Mill_Gremlin, self).realize(widget)

    def set_grid_size(self, size):
        self.grid_size = size
        self._redraw()

    def destroy(self):
        gremlinbase.Tormach_Gremlin_Base.destroy(self)

    def get_view(self):
        # gremlin as used as a gladevcp widget has a propery for the view, which for a lathe
        # should be 'y'.  When it's not right the program extents won't be drawn.
        view_dict = {'x':0, 'y':1, 'z':2, 'p':3}
        return view_dict.get(self.ui_view)

    def get_show_metric(self):
        if self.status.gcodes[linuxcnc.G_CODE_UNITS] == 200:
            return False
        else:
            return True

    def posstrs(self):
        l, h, p, d = gremlin.Gremlin.posstrs(self)
        return l, h, [''], ['']

    def report_gcode_error(self, result, seq, filename):
        import gcode
        error_str = gcode.strerror(result)
        error_str = "\n\nG-Code error in " + os.path.basename(filename) + "\n" + "Near line: " + str(seq) + "\n" + error_str + "\n"
        self.ui.error_handler.write(error_str)
        self.ui.interp_alarm = True


    # misnomer, actually covers gremlin right click as well
    def on_gremlin_double_click(self, widget, event, data=None):
        if event.type == gtk.gdk._2BUTTON_PRESS:
            self.clear_live_plotter()
            return
        # Only open gremlin right click menu if the user is not jogging the machine via keyboard
        if event.type == gtk.gdk.BUTTON_PRESS and event.button == 3 and True not in self.ui.jogging_key_pressed.values():
            # it's a right click if event.button == 3
            menu = gtk.Menu()
            set_front_view = gtk.MenuItem("Front View")
            set_top_view = gtk.MenuItem("Top View")
            set_side_view = gtk.MenuItem("Side View")
            set_iso_view = gtk.MenuItem("Iso View")
            enable_fourth_display = gtk.MenuItem("Enable A Axis Display")
            disable_fourth_display = gtk.MenuItem("Disable A Axis Display")
            set_front_view.connect("activate", self.set_front_view)
            set_top_view.connect("activate", self.set_top_view)
            set_side_view.connect("activate", self.set_side_view)
            set_iso_view.connect("activate", self.set_iso_view)
            enable_fourth_display.connect("activate", self.enable_fourth_axis_toolpath_display)
            disable_fourth_display.connect("activate", self.disable_fourth_axis_toolpath_display)
            menu.append(set_iso_view)
            menu.append(set_top_view)
            menu.append(set_front_view)
            menu.append(set_side_view)

            imperial = not self.ui.g21
            sml_text = "Grid 0.1 inch" if imperial else "Grid 5 mm"
            med_text = "Grid 0.5 inch" if imperial else "Grid 10 mm"
            lrg_text = "Grid 1.0 inch" if imperial else "Grid 25 mm"

            set_grid_size_small = gtk.MenuItem(sml_text)
            set_grid_size_med = gtk.MenuItem(med_text)
            set_grid_size_large = gtk.MenuItem(lrg_text)
            set_grid_size_none = gtk.MenuItem("No Grid")

            set_grid_size_small.connect("activate", self.set_grid_size_small)
            set_grid_size_med.connect("activate", self.set_grid_size_med)
            set_grid_size_large.connect("activate", self.set_grid_size_large)
            set_grid_size_none.connect("activate", self.set_grid_size_none)

            menu.append(set_grid_size_small)
            menu.append(set_grid_size_med)
            menu.append(set_grid_size_large)
            menu.append(set_grid_size_none)

            menu.append(enable_fourth_display)
            menu.append(disable_fourth_display)

            menu.popup(None, None, None, event.button, event.time)
            set_front_view.show()
            set_side_view.show()
            set_top_view.show()
            set_iso_view.show()

            if self.ui_view != 'p':
                set_grid_size_small.show()
                set_grid_size_med.show()
                set_grid_size_large.show()

            try:
                if self.ui.redis.hget('machine_prefs', 'enable_fourth_axis_toolpath') == 'True':
                    disable_fourth_display.show()
                else:
                    enable_fourth_display.show()
            except:
                enable_fourth_display.show()

    def set_current_ui_view(self):
        if self.ui_view == 'y':
            self.set_front_view()
        elif self.ui_view == 'x':
            self.set_side_view()
        elif self.ui_view == 'z':
            self.set_top_view()
        elif self.ui_view == 'p':
            self.set_iso_view()

    def set_front_view(self, widget=None):
        self.set_view_y()
        self.ui_view = 'y'
        self._redraw()
        self.ui.gremlin_options.update_ui_view()

    def set_side_view(self, widget=None):
        self.set_view_x()
        self.ui_view = 'x'
        self._redraw()
        self.ui.gremlin_options.update_ui_view()

    def set_top_view(self, widget=None):
        self.set_view_z()
        self.ui_view = 'z'
        self._redraw()
        self.ui.gremlin_options.update_ui_view()

    def set_iso_view(self, widget=None):
        self.set_view_p()
        self.ui_view = 'p'
        self._redraw()
        self.ui.gremlin_options.update_ui_view()

    def set_grid_size_small(self, widget):
        size = (5/25.4) if self.ui.g21 else .1
        self.set_grid_size(size)
        self.ui.gremlin_options.update_grid_size('small')

    def set_grid_size_med(self, widget):
        size = (10/25.4) if self.ui.g21 else .5
        self.set_grid_size(size)
        self.ui.gremlin_options.update_grid_size('med')

    def set_grid_size_large(self, widget):
        size = (25/25.4) if self.ui.g21 else 1.0
        self.set_grid_size(size)
        self.ui.gremlin_options.update_grid_size('large')

    def set_grid_size_none(self, widget):
        self.set_grid_size(0.0)
        self.ui.gremlin_options.update_grid_size('none')

    def enable_fourth_axis_toolpath_display(self, widget):
        self.ui.redis.hset('machine_prefs', 'enable_fourth_axis_toolpath', 'True')
        self.set_geometry('AXYZ')
        self.ui.gremlin_options.update_a_axis(True)

    def disable_fourth_axis_toolpath_display(self, widget):
        self.ui.redis.hset('machine_prefs', 'enable_fourth_axis_toolpath', 'False')
        self.set_geometry('XYZ')
        self.ui.gremlin_options.update_a_axis(False)


class JobAssignmentGremlin(Tormach_Mill_Gremlin):
    def __init__(self, ja, width, height):
        Tormach_Mill_Gremlin.__init__(self, ja.conversational.ui, width, height)
        self.current_view = 'p'
        self.spooler = None

    def report_gcode_warnings(self, warnings, filename, suppress_after = 3):
        print 'JobAssignmentGremlin.report_gcode_warnings: file: %s, %d warnings' % (filename,len(warnings))

    def load_gcode_list(self, gcode_list):
        if self.initialised:
            path = TormachUIBase.gcode_list_to_tmp_file(gcode_list)
            if path is not None:
                self.load(path)
                self.queue_draw()
            self.spooler = None
        else:
            self.spooler = gcode_list

    def realize(self,widget):
        super(JobAssignmentGremlin, self).realize(widget)
        if self.spooler is not None:
            self.load_gcode_list(self.spooler)
            self.set_default_view()
            self.queue_draw()

    def set_default_view(self):
        self.current_view = self.ui_view = 'p'
        if self.initialised:
            self.set_current_view()

    def destroy(self):
        Tormach_Mill_Gremlin.destroy(self)
        self.spooler = None


import signal
def SIGINT_handler(signal, frame):
    print("Can't shut down via Ctrl-C, please use exit button instead")

signal.signal(signal.SIGINT, SIGINT_handler)



if __name__ == "__main__":
    del _

    # unbuffer stdout so print() shows up in sync with other output
    # the pipe from the redirect in operator_login causes buffering
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

    gobject.threads_init()

    # VLC code had this, but when this is done before above at load time, it hangs on a quick exit
    # still researching...
    #gtk.gdk.threads_init()

    # Rarely needed
    #debugconsole.listen()

    print "tormach_mill_ui.py arguments are ", sys.argv

    init_localization('en_US.UTF8')     # ISO standardized ways of identifying locale
    print _('msg_hello')                # Localization test

    UI = mill()
    singletons.g_Machine = UI

    screen_width = gtk.gdk.Screen().get_width()
    screen_height = gtk.gdk.Screen().get_height()
    UI.error_handler.write('screen resolution is now %d x %d' % (screen_width, screen_height), ALARM_LEVEL_DEBUG)
    if screen_width > 1024 and screen_height > 768:
        UI.window.set_decorated(True)

    # always connect to 'delete_event' in case Alt-F4 isn't disabled in keyboard shortcuts
    UI.window.connect('delete_event', UI.delete_event)
    UI.window.resize(1024, 768)

    UI.probe_notebook.set_current_page(0)

    UI.window.show()
    if UI.error_handler.get_alarm_active():
        set_current_notebook_page_by_id(UI.notebook, 'alarms_fixed')
    else:
        set_current_notebook_page_by_id(UI.notebook, 'notebook_main_fixed')

    UI.kill_splash_screen()

    # nuke the marker file so that pathpilotmanager.py knows for sure we got fully up with the UI displayed.
    crashdetection.delete_crash_detection_file()

    gtk.main()

    sys.exit(UI.program_exit_code)
