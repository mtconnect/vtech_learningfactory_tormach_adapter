# VT Learning Factory's Tormach PCNC-1100 Adapter

An MTConnect Use Case Study at Virginia Tech Learning Factory

Introduction
------
Partnered with AMT (The Association for Manufacturing Technologies), Virginia Tech’s Learning Factory newest acquisition of a Tormach PCNC-1100 is in need of MTConnect implementation for data extraction and data visualization purposes. In this documentation, a brief overview of every step needed to complete this project will be provided. 

**NOTE: In this case scenario MTConnect Agent Version 1.8.0.3 was installed in a custom PC with the following specs:**
<br>
CPU: Intel Xeon E5-2650
<br>
GPU: Nvidia GTX 690
<br>
RAM: 128GB
<br>
Storage: 1 TB
<br>
OS: Ubuntu Linux (20.04.1 SMP)

# Step-By-Step Guide 
 
Data Extraction
------
First step is to figure out if the targeted device machine is able to output data. Every machine in the industry has different ways of outputting data and different formatted data as well. Tormach's way of extracting data involves the PathPilot GUI program that controls the machine during production times. This program contains various Python script files and in one of the files (named Tormach_mill_ui.py), a modification was made to call the function to output Tormach’s data dictionary. Also, it is important to note that Tormach’s operating system is Linux and the dictionary is based of linuxCNC.

Data Simulation
------
Due to unforeseen circumstances, the Tormach was not functioning properly even after finishing the project, so a simulated data script was developed instead. Using the same outputted dictionary from the Data Extraction section, the script was designed to be as close as possible to an actual Tormach outputted dictionary values. The position and rotational values were also smoothed to simulate a real scenario as much as possible.

Developing Adapter
------
To develop the adapter, some key functions need to be developed:
* `Socket connectivity`        - Creating socket objects, binding local port, and listening to socket.
* `Data fetching`        - Collect data from source.
* `Parsing data`        - Translating data from source to MTConnect standard.
* `Threading`        - Setup threadings.
* `Sending data to Agent`        -String outputs in MTConnect standard to Agent.

In this phase, we used reference code from other MTConnect adapters to develop Tormach’s. Since the rest key functions remain the same for this case scenario, what needs to be focused on is data fetching and parsing data. However, because the Tormach was inoperable at this time, we imported **simulator.py** into the adapter and then within the adapter, the data parser was developed.

To translate data to the correct standard, the following resources were used:
* `LinuxCNC library:` https://github.com/mtconnect/cppagent/releases?q=1.8.0.3&expanded=true

* `MTConnect model:` https://model.mtconnect.org/

Explain what each element signifies


Installing MTConnect Agent
------
**NOTE: This project used MTConnect Agent Version 1.8.0.3**

To develop the adapter, some key functions need to be developed:
* `1) Download MTConnect Agent from` https://github.com/mtconnect/cppagent/releases?q=1.8.0.3&expanded=true
* `2) Extract and move ‘cppagent-1.8.0.3’ folder to Documents`
* `3) Make a folder called ‘build’ inside ‘‘cppagent-1.8.0.3’ folder`
* `4) Open terminal and cd Documents>‘cppagent-1.8.0.3>build and run ‘cmake’`
* `5) Run <code>make</code>`   
* `6) Run <code>sudo make install</code>`

Configuring the Agent
------
**Before configuring the Agent, create a new folder called ‘Tormach’ in the Documents folder. Inside ‘Tormach’ the XML schema called ‘Tormach.xml’ and ‘agent.cfg’ will be stored.**

‘Tormach.xml’ serves the purpose of shaping the MTConnect UI to every machine, type and value that is assigned from the Adapter to the Agent. In simple words, it serves as the translator or intermediary between the Adapter and Agent.

Explain what each element signifies

‘agent.cfg’ should be configured to match the port and file path. The following is the header and it is important to specify SchemaVersion to be 1.7 so it matches the XML schema. Port was assigned to 5001 but the default is 5000.

     Devices = ./Tormach.xml
     AllowPut = true
     ReconnectInterval = 1000
     BufferSize = 17
     SchemaVersion = 1.7
     MonitorConfigFiles = true
     Pretty = true
     Port = 5001
     # MinimumConfigReloadAge = 30

In this part, the host is the IP address of the machine in use. This port will be important when the MTConnect web UI is being accessed from another computer in the local network.

    Adapters {
       # Log file has all machines with device name prefixed
        Tormach-PCNC1100
        {
          Host = 192.168.1.25
          Port = 7878
        } 
    }

Lastly, this step is important for the agent to work. Since ‘cppagent-1.8.0.3’ folder and ‘Tormach’ folder are both in one folder (‘Documents’), the configuration should be the following:

    Files {
        schemas {
            Path = ../cppagent-1.8.0.3/schemas
            Location = /schemas/
        }
        styles {
            Path = ../cppagent-1.8.0.3/styles
            Location = /styles/
        }
        Favicon {
            Path = ../cppagent-1.8.0.3/styles/favicon.ico
            Location = /favicon.ico
        }
    }

How to start the Agent
------
* `1) Open terminal and run Tormach_adapter.py script.`
* `2) Open a new terminal window and cd Documents/Tormach and run <code>agent run</code>`
* `3) If accessing from local computer, simply run http://localhost:5000 on the web browser`
* `4) If accessing from another computer in the same network, run http://{insertIPaddress}:5001`









