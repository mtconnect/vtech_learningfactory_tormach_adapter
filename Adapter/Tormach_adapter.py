import sys
import threading
import time
import socket
import datetime
from pathlib import Path

# Import simulator.py into this script
p1 = Path(__file__)
p1 = p1.parent.parent.absolute()
p1str = str(p1)
print(p1str + "/Simulator")
sys.path.append(p1str + "/Simulator")
from simulator import dataSimulator

client_counter = 0
client_list = []
first_run_flag = 1
lock = threading.Lock()
event = threading.Event()
event.set()

"""Creating Socket Objects"""
HOST = "0.0.0.0"
PORT = 7878

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

"""Binding to the local port/host"""
try:
    s.bind((HOST, PORT))
except socket.error as msg:
    print("Bind failed. Error Code : " + str(msg[0]) + " Message " + msg[1])
    sys.exit()

"""Start Listening to Socket for Clients"""
s.listen(5)

"""Function to Clear Out Threads List Once All Threads are Empty"""


def thread_list_empty():
    global client_list, client_counter

    while True:
        try:
            if client_counter == 0 and first_run_flag == 0 and client_list != []:
                print("%d Clients Active" % client_counter)
                print("Clearing All threads....")
                for index, thread in enumerate(client_list):
                    thread.join()
                client_list = []
        except:
            print("Invalid Client List Deletion")


def fetch_from_Tormach():
    global combined_output
    # Parser begins here
    sim = dataSimulator()

    XabsPrevious = "novalue"
    YabsPrevious = "novalue"
    ZabsPrevious = "novalue"
    SrpmPrevious = "novalue"
    estopPrevious = "novalue"
    executionPrevious = "novalue"
    machineAvailPrevious = "novalue"
    controllerModePrevious = "novalue"

    while True:
        updated = False
        try:
            result = sim.getData()

            # This is not from LinuxCNC and is for simulated data only - remove if using real machine
            if "availability" in result.keys():
                machineAvail = result["availability"]
                if machineAvail < 2:  # 2% chance
                    machineAvail = "UNAVAILABLE"
                else:
                    machineAvail = "AVAILABLE"

            if "estop" in result.keys():
                estop = result["estop"]
                if estop < 1:
                    estop = "TRIGGERED"
                else:
                    estop = "ARMED"

            if "exec_state" in result.keys():
                execution = str(result["exec_state"])
                if execution == "0":
                    execution = "READY"
                elif execution == "1":
                    execution = "ACTIVE"  # "PROGRAM_COMPLETED"
                elif execution == "2":
                    execution = "INTERRUPTED"  # "READY",
                elif execution == "3":
                    execution = "WAIT"
                elif execution == "4":
                    execution = "FEED_HOLD"
                elif execution == "5":
                    execution = "STOPPED"
                elif execution == "6":
                    execution = "OPTIONAL_STOP"
                elif execution == "7":
                    execution = "PROGRAM_STOPPED"
                else:
                    execution = "PROGRAM_COMPLETED"

            if "task_mode" in result.keys():
                controllerMode = str(result["task_mode"])
                if controllerMode == "0":
                    controllerMode = "MANUAL_DATA_INPUT"
                if controllerMode == "1":
                    controllerMode = "AUTOMATIC"
                if controllerMode == "2":
                    controllerMode = "MANUAL"

            if "axis" in result.keys():
                Xabs = str(result["axis"][0]["output"])
                Yabs = str(result["axis"][1]["output"])
                Zabs = str(result["axis"][2]["output"])
                Srpm = str(result["axis"][3]["velocity"])

            outString = ""

            # Xabs
            if Xabs != XabsPrevious:
                print(Xabs)
                outString += "|Xabs|" + Xabs
                XabsPrevious = Xabs
            print("Xabs: " + Xabs)

            # Yabs
            if Yabs != YabsPrevious:
                print(Yabs)
                outString += "|Yabs|" + Yabs
                YabsPrevious = Yabs
            print("Yabs: " + Yabs)

            # Zabs
            if Zabs != ZabsPrevious:
                print(Zabs)
                outString += "|Zabs|" + Zabs
                ZabsPrevious = Zabs
            print("Zabs: " + Zabs)

            # Srpm
            if Srpm != SrpmPrevious:
                print(Srpm)
                outString += "|Srpm|" + Srpm
                SrpmPrevious = Srpm
            print("Srpm: " + Srpm)

            # estop
            if estop != estopPrevious:
                print(estop)
                outString += "|estop|" + estop
                estopPrevious = estop
            print("estop: " + estop)

            # execution
            if execution != executionPrevious:
                print(execution)
                outString += "|execution|" + execution
                executionPrevious = execution
            print("execution: " + execution)

            # machine availability
            if machineAvail != machineAvailPrevious:
                print(machineAvail)
                outString += "|machineAvail|" + machineAvail
                machineAvailPrevious = machineAvail
            print("machineAvail: " + machineAvail)

            # controller mode
            if controllerMode != controllerModePrevious:
                print(controllerMode)
                outString += "|controllerMode|" + controllerMode
                controllerModePrevious = controllerMode
            print("controllerMode: " + controllerMode)
            # Parser ends here

            # Final data purge
            combined_output = (
                "\r\n" + datetime.datetime.now().isoformat() + "Z" + outString
            )
            print("---", combined_output)
            time.sleep(0.6)
        except Exception as ex:
            print("Failed fetching values from machine: ")
            print(ex)
            time.sleep(2)


"""Main Thread Class For Clients"""


class NewClientThread(threading.Thread):
    # init method called on thread object creation,
    def __init__(self, conn, string_address):
        threading.Thread.__init__(self)
        self.connection_object = conn
        self.client_ip = string_address

    # run method called on .start() execution
    def run(self):
        global client_counter, combined_output
        global lock
        while True:
            try:
                # print("Sending data to Client {} in {}".format(self.client_ip, self.getName()))
                out = combined_output
                print("OUT1:")
                print("OUT: " + out)
                self.connection_object.sendall(out.encode())
                time.sleep(0.5)

            except err:
                lock.acquire()
                try:
                    print(err)
                    client_counter = client_counter - 1
                    print("Connection disconnected for ip {} ".format(self.client_ip))
                    break
                finally:
                    lock.release()


"""Starts From Here"""
t1 = threading.Thread(target=thread_list_empty)
t2 = threading.Thread(target=fetch_from_Tormach)
t1.setDaemon(True)
t2.setDaemon(True)
t1.start()
t2.start()
time.sleep(2)

while event.is_set():

    if first_run_flag == 1:
        print("Listening to Port: %d...." % PORT)

    try:
        conn, addr = s.accept()
        lock.acquire()
        client_counter = client_counter + 1
        first_run_flag = 0
        print("Accepting Comm From:" + " " + str(addr))
        new_Client_Thread = NewClientThread(conn, str(addr))
        new_Client_Thread.setDaemon(True)
        client_list.append(new_Client_Thread)
        print(client_list)
        new_Client_Thread.start()
        lock.release()
    except KeyboardInterrupt:
        print("\nExiting Program")
        sys.exit()

if not event.is_set():
    print("\nExiting Program")
    sys.exit()
