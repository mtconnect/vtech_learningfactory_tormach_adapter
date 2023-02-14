import threading
import time 
import socket
import sys
import datetime
import serial
import re
import requests

client_counter = 0
client_list = []
first_run_flag = 1
lock = threading.Lock()
event = threading.Event()
event.set()

# Initialising 7 global attributes for HAAS serial comm macros
## mac_status = part_num = prog_name = sspeed = coolant = sload = cut_status = combined_output = 'Nil'

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

def readData(ser, HAASCode):
    try:
        ser.write(bytes("?Q600 " + HAASCode + "\r\n", "ascii"))
        while True:
            value = ser.readline().decode("utf-8").strip()
            if len(value) > 4:
                break
        value = value.split(",")[2].strip()
        value = value.replace(chr(23), '')
    except Exception as ex:
        print(ex)
        value = 'Nil' # maybe UNAVAILABLE?
    return value

"""Function that parses attributes from the HAAS"""

def fetch_from_HAAS():
    ## global mac_status, part_num, prog_name, sspeed, coolant, sload, cut_status, combined_output
    

    ser = serial.Serial(bytesize=serial.SEVENBITS, xonxoff=True)
    ser.baudrate = 9600
    # Assuming HAAS is connected to ttyUSB0 port of Linux System
    ser.port = '/dev/ttyUSB0' 
    ser.timeout = 1

    try:
        ser.open()
    except serial.SerialException:
        if ser.is_open:
            try:
                print("Port was open. Attempting to close.")
                ser.close()
                time.sleep(2)
                ser.open()
            except:
                print("Port is already open. Failed to close. Try again.")
                event.clear()
        else:
            print("Failed to connect to serial port. Make sure it is free or it exists. Try again.")
            event.clear()

    print("ok1")
    coolantPrevious = "novalue"
    spindleSpeedPrevious = "novalue"
    spindleLoadPrevious = "novalue"
    xMachinePrevious = "novalue"
    xWorkPrevious = "novalue"
    yMachinePrevious = "novalue"
    yWorkPrevious = "novalue"
    zMachinePrevious = "novalue"
    zWorkPrevious = "novalue"
    aMachinePrevious = "novalue"
    aWorkPrevious = "novalue"
    bMachinePrevious = "novalue"
    bWorkPrevious = "novalue"

    while True:
        updated = False
        try:
            outString =""
            print("ok2")
            #coolant
            coolant = readData(ser, "1094")
            if coolant != coolantPrevious:
                print(coolant)
                #outString += "|coolant|"+coolant
                coolantPrevious = coolant
            print("coolant: " + coolant)

            #spindle speed
            spindleSpeed = readData(ser, "3027")
            if spindleSpeed != spindleSpeedPrevious:
                print(spindleSpeed, spindleSpeedPrevious)
                outString += "|spindleSpeed|"+spindleSpeed
                spindleSpeedPrevious = spindleSpeed
            print("spindleSpeed: " + spindleSpeed)

            # spindle load
            spindleLoad = readData(ser, "1098")
            if spindleLoad != spindleLoadPrevious:
                print(spindleLoad)
                #outString += "|spindleLoad|"+spindleLoad
                spindleLoadPrevious = spindleLoad
            print("spindleLoad: " + spindleLoad)

            # x machine
            xMachine = readData(ser, "5021")
            if xMachine != xMachinePrevious:
                print(xMachine)
                outString += "|xMachine|"+xMachine
                xMachinePrevious = xMachine
            print("xMachine: " + xMachine)

            # x work
            xWork = readData(ser, "5041")
            if xWork != xWorkPrevious:
                print(xWork)
                outString += "|xWork|"+xWork
                xWorkPrevious = xWork
            print("xWork: " + xWork)

            # y machine
            yMachine = readData(ser, "5022")
            if yMachine != yMachinePrevious:
                print(yMachine)
                outString += "|yMachine|"+yMachine
                yMachinePrevious = yMachine
            print("yMachine: " + yMachine)

            # y work
            yWork = readData(ser, "5042")
            if yWork != yWorkPrevious:
                print(yWork)
                outString += "|yWork|"+yWork
                yWorkPrevious = yWork
            print("yWork: " + yWork)

            #z machine
            zMachine = readData(ser, "5023")
            if zMachine != zMachinePrevious:
                print(zMachine)
                outString += "|zMachine|"+zMachine
                zMachinePrevious = zMachine
            print("zMachine: " + zMachine)

            #z work
            zWork = readData(ser, "5043")
            if zWork != zWorkPrevious:
                print(zWork)
                outString += "|zWork|"+zWork
                zWorkPrevious = zWork
            print("zWork: " + zWork)

            # machine a
            aMachine = readData(ser, "5024")
            if aMachine != aMachinePrevious:
                print(aMachine)
                outString += "|aMachine|"+aMachine
                aMachinePrevious = aMachine
            print("aMachine: " + aMachine)

            #machine b
            bMachine = readData(ser, "5025")
            if bMachine != bMachinePrevious:
                print(bMachine)
                outString += "|bMachine|"+bMachine
                bMachinePrevious = bMachine
            print("bMachine: " + bMachine)

            # work a
            aWork = readData(ser, "5044")
            if aWork != aWorkPrevious:
                print(aWork)
                outString += "|aWork|"+aWork
                aWorkPrevious = aWork
            print("aWork: " + aWork)

            # work b
            bWork = readData(ser, "5045")
            if bWork != bWorkPrevious:
                print(bWork)
                outString += "|bWork|"+bWork
                bWorkPrevious = bWork
            print("bWork: " + bWork)

            # Final data purge
            combined_output = '\r\n' + datetime.datetime.now().isoformat() + 'Z' + outString
            print("---",combined_output)
        except Exception as ex:
            print("Failed fetching values from machine: ")
            print(ex)
            time.sleep(2)

        # time.sleep(0.6)

    ser.close()


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
t2 = threading.Thread(target=fetch_from_HAAS)
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
