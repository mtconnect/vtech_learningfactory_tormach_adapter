# Infinite loop random data generator that will be exported for adapter use. 

# TO DO: add the correct respective linuxcnc names in comments

import random

while True:
    # absolute X-axis position (output in linuxcnc) - float / max is 457mm (Tormach website)
    Xabs = round(random.uniform(0.0, 457.0), 1)
 
    # absolute Y-axis position (output in linuxcnc) - float / max is 279mm (Tormach website)
    Yabs = round(random.uniform(0.0, 279.0), 1)

    # absolute Z-axis position (output in linuxcnc) - float / max is 413mm (Tormach website)
    Zabs = round(random.uniform(0.0, 413.0), 1)

    # C-axis rotary velocity (output in linuxcnc) - float/max is 7500RPM (Tormach website)
    Srpm = round(random.uniform(0.0, 7500.0), 1)
    
    # emergency stop (estop in linuxcnc)- integer (0 to 1)
    estop = random.randint(0, 1)
    
    # execution state (execution_state in linuxcnc)- integer (0 to 7)
    execution = random.randint(0, 7)

    print(Xabs, Yabs, Zabs, Srpm, estop, execution)