# VT Learning Factory's Tormach PCNC-1100 Adapter

An MTConnect Use Case Study at Virginia Tech Learning Factory

Introduction
------
Partnered with AMT (The Association for Manufacturing Technologies), Virginia Tech’s Learning Factory newest acquisition of a Tormach PCNC-1100 is in need of MTConnect implementation for data extraction and data visualization purposes. In this documentation, a brief overview of every step needed to complete this project will be provided. 

**NOTE: In this case scenario MTConnect Agent Version 1.8.0.3 was installed in a custom PC with the following specs:
CPU: Intel Xeon E5-2650 
GPU: Nvidia GTX 690
RAM: 128GB 
Storage: 1 TB 
OS: Ubuntu Linux (20.04.1 SMP) 
 ** 

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

Installing MTConnect Agent
------
**NOTE: This project used MTConnect Agent Version 1.8.0.3**

To develop the adapter, some key functions need to be developed:
* `1) Download MTConnect Agent         - URL: 1.8.0.3 · Releases · mtconnect/cppagent (github.com). 
* `1) Make a folder called ‘build’ inside ‘agent’ folder`        - 
* `2)`        - Collect data from source.
* `3)`        - Translating data from source to MTConnect standard.
* `4)`        - Setup threadings.
* `5)`        -String outputs in MTConnect standard to Agent.


Followed the steps here: https://machiningcode.com/install-the-mtconnect-agent-in-two-easy-ish-steps

Make a folder called build inside agent folder
Cmake
Make
Sudo make install

Configuring the Agent
------
The first file to configure would be the XML schema, this serves the purpose of shaping the MTConnect UI to every machine, type and value that is assigned from the Adapter to the Agent. In simple words, it serves as the translator or intermediary between the Adapter and Agent. For more details on how to configure this, it is recommended to take a closer look at the MTConnect Github repositories of Haas, UR5 or Tormach and go through the XML files given there. Lastly, the Agent requires a file to be present named “agent.cfg” that should be configured to match the port and file path. For reference, please visit the MTConnect Github repositories of the machines mentioned before.

How to start the Agent
------


Because the Tormach was not functioning properly at the time the adapter was developed, a script named simulator.py was created with the purpose of simulated actual data. 






