# ---------------------------------------------------------------------------------------------#
#                Random number generator for Tormach PCNC-1100 simuled data                    #
# ---------------------------------------------------------------------------------------------#

import random
import time


# Generates random numbers respective to each max output by Tormach

# absolute X-axis position (output in linuxcnc) - float / max is 457mm (Tormach website)
output1 = round(random.uniform(0.0, 457.0), 1)
# absolute Y-axis position (output in linuxcnc) - float / max is 279mm (Tormach website)
output2 = round(random.uniform(0.0, 279.0), 1)
# absolute Z-axis position (output in linuxcnc) - float / max is 413mm (Tormach website)
output3 = round(random.uniform(0.0, 413.0), 1)
# C-axis rotary velocity (output in linuxcnc) - float/max is 7500RPM (Tormach website)
Srpm = round(random.uniform(0.0, 7500.0), 1)
# emergency stop (estop in linuxcnc)- integer (0 to 1)
estop = random.randint(0, 1)
# execution state (exec_state_state in linuxcnc)- integer (0 to 7)
exec_state = random.randint(0, 7)


# Makes data smoother 

def smoothData_simulator():
    while True:
        changesoutput1 = round(random.uniform(-1.0, 1.0), 1)
        output1Previous = output1 + changesoutput1

        changesoutput2 = round(random.uniform(-1.0, 1.0), 1)
        output2Previous = output2 + changesoutput2

        changesoutput3 = round(random.uniform(-1.0, 1.0), 1)
        output3Previous = output3 + changesoutput3

        # changesSrpm = round(random.uniform(-1.0, 1.0), 1) 
        # SrpmPrevious = Srpm + changesSrpm
        # print (SrpmPrevious)

        # changesestop = round(random.uniform(-1.0, 1.0), 1)
        # estopPrevious = estop + changesestop
        # print (estopPrevious)

        # changesexec_state = round(random.uniform(-1.0, 1.0), 1)
        # exec_statePrevious = exec_state + changesexec_state
        # print (exec_statePrevious)

        time.sleep(0.5)

        print("'output': " + output1Previous) 
        
        
if __name__ == "__main__":
    smoothData_simulator()



# ---------------------------------------------------------------------------------------------#
#                    Depreciated because machine values should be smooth                       #
# ---------------------------------------------------------------------------------------------#

# while True:
#     # absolute X-axis position (output in linuxcnc) - float / max is 457mm (Tormach website)
#     output = round(random.uniform(0.0, 457.0), 1)

#     # absolute Y-axis position (output in linuxcnc) - float / max is 279mm (Tormach website)
#     output = round(random.uniform(0.0, 279.0), 1)

#     # absolute Z-axis position (output in linuxcnc) - float / max is 413mm (Tormach website)
#     output = round(random.uniform(0.0, 413.0), 1)

#     # C-axis rotary velocity (output in linuxcnc) - float/max is 7500RPM (Tormach website)
#     Srpm = round(random.uniform(0.0, 7500.0), 1)

#     # emergency stop (estop in linuxcnc)- integer (0 to 1)
#     estop = random.randint(0, 1)

#     # exec_state state (exec_state_state in linuxcnc)- integer (0 to 7)çc
#     exec_state = random.randint(0, 7)

#     print(output, output, output, Srpm, estop, exec_state)