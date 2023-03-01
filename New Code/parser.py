import threading
import time 
import socket
import sys
import datetime
# import serial -not being used
# import re -not being used
# import requests -not being used
from simulatorV2 import dataSimulator

Xabs = 0
Yabs = 0
Zabs = 0
Srpm = 0
estop = 0
execution = 0

sim = dataSimulator()
result = sim.getData()
for dataKey in result.keys():
    if dataKey == 'estop':
       estop = str(result[dataKey])
    
    if dataKey == 'exec_state':
       execution = result[dataKey]

    if dataKey == 'axis':
       Xabs = result[dataKey][0]['output']

    if dataKey == 'axis':
       Yabs = result[dataKey][1]['output']

    if dataKey == 'axis':
       Zabs = result[dataKey][2]['output']

    if dataKey == 'axis':
       Srpm = result[dataKey][3]['velocity']

    
       print(estop, execution, Xabs, Yabs, Zabs, Srpm)    


# with dataSimulator() as sim:
#     for dataKey in sim.getData():
#         if dataKey == 'estop':
#             [dataKey] = estop