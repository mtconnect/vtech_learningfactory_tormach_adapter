import threading, time, socket, sys, datetime, random, rtde, rtde_config, requests
from urllib.request import localhost

client_counter = 0
client_list = []
first_run_flag = 1
lock = threading.Lock()
event = threading.Event()
event.set()

# Initialising 6 global attributes for UR5 serial comm macros
jointangle0 = jointangle1 = jointangle2 = jointangle3 = jointangle4 = jointangle5 = 'Nil'

"""Creating Socket Objects"""
HOST = '0.0.0.0' #hostname
PORT = 7878 #Portnumber

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #create
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

"""Binding to the local port/host"""
try:
    s.bind((HOST, PORT)) #method of Python's socket class assigns an IP address and a port number to a socket instance.
except socket.error as msg:
    print ('Bind failed. Error Code : ' + str(msg)) 
    sys.exit() #print message if s.bind is unsuccessful

"""Start Listening to Socket for Clients"""
s.listen(5) #s.listen to listen to Socket for Clients. The "5" stands for how many incoming connections we're willing to queue before denying any more.


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


"""Function that parses attributes from the UR5"""

def fetch_from_UR5(): 
    global jointangle0, jointangle1, jointangle2, jointangle3, jointangle4, jointangle5, combined_output, grippervariable, jointangle0_prev,jointangle1_prev,jointangle2_prev,jointangle5_prev,jointangle3_prev,jointangle4_prev
    UR5IP = "10.42.0.2"
    UR5Port = 30004
    configFileName = "control_loop_configuration.xml"

    conf = rtde_config.ConfigFile(configFileName)
    state_names, state_types = conf.get_recipe("state")
    setp_names, setp_types = conf.get_recipe("setp")
    watchdog_names, watchdog_types = conf.get_recipe("watchdog")

    con = rtde.RTDE(UR5IP, UR5Port)
    con.connect()

    print(con.get_controller_version())

    con.send_output_setup(state_names, state_types)
    setp = con.send_input_setup(setp_names, setp_types)
    watchdog = con.send_input_setup(watchdog_names, watchdog_types)
    
    jointAngle0Previous = "novalue"
    jointAngle1Previous = "novalue"
    jointAngle2Previous = "novalue"
    jointAngle3Previous = "novalue"
    jointAngle4Previous = "novalue"
    jointAngle5Previous = "novalue"

    if not con.send_start():
        sys.exit()

    #Global, modify the variable outside of the current scope. It is used to create a global variable and make changes to the variable in a local context with the variables
    while True:
        state = con.receive()
        location = state.actual_q
        #outString = '|j0|' + 'Nil' + '|j1|' + 'Nil' + '|j2|' + 'Nil' + '|j3|' + 'Nil' + '|j4|' + 'Nil' + '|j5|' + 'Nil' +'|gripperstate1|' + 'Nil'
        outString = ""

        #Shows the angle and the time at which it was taken
        try:
            #So that the new angles don't have value
            jointangle0 = ""
            jointangle1 = ""
            jointangle2 = ""
            jointangle3 = ""
            jointangle4 = ""
            jointangle5 = ""

            try:
                jointangle0 = location[0] #values for the first joint
            except: # should never happen...
                jointangle0 = 'Nil'
            if jointangle0 != jointAngle0Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j0|" + str(jointangle0)
                jointAngle0Previous = jointangle0
                
            try:
                jointangle1 = location[1] #values for the second joint
            except: # should never happen...
                jointangle1 = 'Nil'
            if jointangle1 != jointAngle1Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j1|" + str(jointangle1)
                jointAngle1Previous = jointangle1
            try:
                jointangle2 = location[2] #values for the third joint
            except: # should never happen...
                jointangle2 = 'Nil'
            if jointangle2 != jointAngle2Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j2|" + str(jointangle2)
                jointAngle2Previous = jointangle2
            try:
                jointangle3 = location[3] #values for the forth joint
            except: # should never happen...
                jointangle3 = 'Nil'
            if jointangle3 != jointAngle3Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j3|" + str(jointangle3)
                jointAngle3Previous = jointangle3

            try:
                jointangle4 = location[4] #values for the fifth joint
            except: # should never happen...
                jointangle4 = 'Nil'
            if jointangle4 != jointAngle4Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j4|" + str(jointangle4)
                jointAngle4Previous = jointangle4
            try:
                jointangle5 = location[5] #values for the sixth joint
            except:  # should never happen...
                jointangle5 = 'Nil'
            if jointangle5 != jointAngle5Previous: #if new angle is different than past then show 
                updated = True
                outString += "|j5|" + str(jointangle5)
                jointaAgle5_Previous = jointangle5

            # if grippervariable == 'OPEN': 
            #     if jointangle0 >=-0.23 and jointangle0 <= -0.18: #if Base is in between -0.23 and -0.18 then gripper is closed
            #         grippervariable = "CLOSED"
            # elif grippervariable == 'CLOSED':
            #     if jointangle0 >= -3.43 and jointangle0 <= -3.38: #if Base is in between -3.43 and -3.38 then gripper is open
            #         grippervariable = 'OPEN'
            # out += "|gripperstate|" + grippervariable

            # for each variable you're reading, obtain the value (as a string) and set it equal to the "current" variable declared above.
            # next, compare it to the previous value.
            # if they are equal, do nothing.
            # if they are different, add |VAR.NAME|VAR.VALUE to the out string.
            # ex: out += "|xPos|" + XPositionCurrent
            
    #end of input
    #### Data with 6 joints

        # end section -----------------------------
        
            combined_output = '\r\n' + datetime.datetime.now().isoformat() + 'Z' + outString
            time.sleep(2)
        except Exception as ex:
            print("Failed fetching values from machine ")
            print(ex)
            time.sleep(2)

        #Main Thread Class For Clients

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
                time.sleep(2)

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
t2 = threading.Thread(target=fetch_from_UR5)
t1.setDaemon(True)
t2.setDaemon(True)
t1.start()
t2.start()
time.sleep(2)
print("setup")

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
