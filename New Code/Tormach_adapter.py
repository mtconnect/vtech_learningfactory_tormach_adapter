import threading
import time 
import socket
import sys
import datetime
# import serial -not being used
# import re -not being used
# import requests -not being used
from simulatorV2 import dataSimulator

client_counter = 0
client_list = []
first_run_flag = 1
lock = threading.Lock()
event = threading.Event()
event.set()

"""Creating Socket Objects"""
HOST = '0.0.0.0'
PORT = 7878

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

"""Binding to the local port/host"""
try:
    s.bind((HOST, PORT))
except socket.error as msg:
    print ('Bind failed. Error Code : ' + str(msg[0]) + ' Message ' + msg[1])
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
    
    # Test purposes        
    #print(estop, execution, Xabs, Yabs, Zabs, Srpm)
    # Parser ends here

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
            for dataKey in result.keys():
                if dataKey == 'estop':
                    estop = str(result[dataKey])
                    if estop == "0":
                        estop = "OFF"
                    if estop == "1":
                        estop = "ON"
                
                if dataKey == 'exec_state':
                    execution = str(result[dataKey])
                    if execution == "0":
                        execution = "EXEC_ERROR"
                    if execution == "1":
                        execution = "EXEC_DONE"
                    if execution == "2":
                        execution = "EXEC_WAITING_FOR_MOTION"
                    if execution == "3":
                        execution = "EXEC_WAITING_FOR_MOTION_QUEUE"
                    if execution == "4":
                        execution = "EXEC_WAITING_FOR_PAUSE"
                    if execution == "5":
                        execution = "EXEC_WAITING_FOR_MOTION_AND_IO"
                    if execution == "6":
                        execution = "EXEC_WAITING_FOR_DELAY"
                    if execution == "7":
                        execution = "EXEC_WAITING_FOR_SYSTEM_CMD"

                if dataKey == 'task_state':
                    machineAvail = str(result[dataKey])
                    if machineAvail == "0":
                        machineAvail = "STATE_ESTOP"
                    if machineAvail == "1":
                        machineAvail = "STATE_ESTOP_RESET"
                    if machineAvail == "2":
                        machineAvail = "STATE_ON"
                    if machineAvail == "3":
                        machineAvail = "STATE_OFF"
                    print("==========================================")
                    print (machineAvail)
                    print("==========================================")

                if dataKey == 'task_mode':
                    controllerMode = str(result[dataKey])
                    if controllerMode == "0":
                        controllerMode = "MODE_MDI"
                    if controllerMode == "1":
                        controllerMode = "MODE_AUTO"
                    if controllerMode == "2":
                        controllerMode = "MODE_MANUAL"

                if dataKey == 'axis':
                    Xabs = str(result[dataKey][0]['output'])

                if dataKey == 'axis':
                    Yabs = str(result[dataKey][1]['output'])

                if dataKey == 'axis':
                    Zabs = str(result[dataKey][2]['output'])

                if dataKey == 'axis':
                    Srpm = str(result[dataKey][3]['velocity'])
            outString =""
            print("ok2")

            # Xabs
            if Xabs != XabsPrevious:
                print(Xabs)
                outString += "|Xabs|"+Xabs
                XabsPrevious = Xabs
            print("Xabs: " + Xabs)

            # Yabs
            if Yabs != YabsPrevious:
                print(Yabs)
                outString += "|Yabs|"+Yabs
                YabsPrevious = Yabs
            print("Yabs: " + Yabs)

            # Zabs
            if Zabs != ZabsPrevious:
                print(Zabs)
                outString += "|Zabs|"+Zabs
                ZabsPrevious = Zabs
            print("Zabs: " + Zabs)

            # Srpm
            if Srpm != SrpmPrevious:
                print(Srpm)
                outString += "|Srpm|"+Srpm
                SrpmPrevious = Srpm
            print("Srpm: " + Srpm)

            # estop
            if estop != estopPrevious:
                print(estop)
                outString += "|estop|"+estop
                estopPrevious = estop
            print("estop: " + estop)

            # execution
            if execution != executionPrevious:
                print(execution)
                outString += "|execution|"+execution
                executionPrevious = execution
            print("execution: " + execution)

            # machine availability
            if machineAvail != machineAvailPrevious:
                print(machineAvail)
                outString += "|machineAvail|"+machineAvail
                machineAvailPrevious = machineAvail
            print("machineAvail: " + machineAvail)

            # cotroller mode
            if controllerMode != controllerModePrevious:
                print(controllerMode)
                outString += "|controllerMode|"+controllerMode
                controllerModePrevious = controllerMode
            print("controllerMode: " + controllerMode)

        
        
#-------------------------------------------------------------------#
            # Final data purge
            combined_output = '\r\n' + datetime.datetime.now().isoformat() + 'Z' + outString
            print("---",combined_output)
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
                #print("Sending data to Client {} in {}".format(self.client_ip, self.getName()))
                out = combined_output
                print("OUT1:")
                print("OUT: "+ out)
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
