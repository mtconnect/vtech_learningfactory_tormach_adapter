# VT Learning Factory's Tormach PCNC-1100 Adapter

  
## Introduction

*Please review ReadMe.md in this project's root directory before this file for context.*

Partnered with The Association for Manufacturing Technologies (AMT), a team of undergraduate students in the Virginia Tech Learning Factory set out to develop an MTConnect adapter for the Tormach PCNC-1100 milling center. In this documentation, a brief overview of every step needed to complete this project will be provided.


**NOTE: In this specific environment, the MTConnect Agent Version 1.8.0.3 was installed in a custom PC with the following specs:**
- CPU: Intel Xeon E5-2650
- GPU: Nvidia GTX 690
- RAM: 128GB
- Storage: 1 TB
- OS: Ubuntu Linux (20.04.1 SMP)

  

## Installation and Usage Guide

These steps will provide both context on the MTConnect Agent and a guide to installing and using the Tormach PCNC-1100 MTConnect Adapter. **Please note that because the development team was not provided with and could not procure an operational Tormach milling center, this project was built on a simulated milling machine based on paper research.  Compatibility with real hardware is expected, but may require some additional configuration.** For more information on the MTConnect standard and MTConnect Agent, please see [MTConnect's official documentation](https://www.mtconnect.org/documents).

---
### Data Simulation

Under unforeseen circumstances, the Virginia Tech team was not provided with nor able to procure a functioning Tormach milling center. Instead, a data simulator was built using paper research and software investigations on a non-functioning machine. It was found that the Tormach PCNC-1100's "controller" is an instance of LinuxCNC, running on a fairly standard installation of Linux Mint. The data simulator was built around known LinuxCNC variables, with a Python dictionary schema formatted to represent as closely as possible the data that one would be able to retrieve by listening to LinuxCNC on an open port. Most variables were randomized, though positional and rotational values were smoothed from one instance to the next to add some realism.

Simulated data is accessed by this Adapter by simply importing and running the data simulator function. However, on a real machine, one would need to check the LinuxCNC configuration files and modify this Adapter to listen to the correct port, while removing the simulator import statement and adjusting the `fetch_from_Tormach` function to account for the new data source. For more context and an example of an MTConnect adapter for another LinuxCNC-based machine, refer to [the MTConnect adapter for the PocketNC milling machine](https://github.com/mtconnect/PocketNC_adapter).

---
### Installing the MTConnect Agent

**NOTE: This project used MTConnect Agent Version 1.8.0.3**

  

The following steps can be followed to download and install the MTConnect Agent:

1) Download MTConnect Agent from https://github.com/mtconnect/cppagent/releases?q=1.8.0.3&expanded=true
2) Extract and move ‘cppagent-1.8.0.3’ folder to Documents
3) Make a folder called ‘build’ inside ‘cppagent-1.8.0.3’ folder
4) Open terminal and cd Documents>cppagent-1.8.0.3>build and run 'cmake'
5) Run 'make'
6) Run 'sudo make install'

  

---
### Configuring the Agent

**Before configuring the Agent, create a new folder called ‘Tormach’ in the Documents folder. Inside ‘Tormach’ the XML schema called ‘Tormach.xml’ and ‘agent.cfg’ will be stored.**

  

‘Tormach.xml’ serves the purpose of shaping the MTConnect UI to every machine, type and value that is assigned from the Adapter to the Agent. In simple words, it serves as the translator or intermediary between the Adapter and Agent.
  

‘agent.cfg’ should be configured to match the port and file path. The following is the header and it is important to specify SchemaVersion to be 1.7 so it matches the XML schema. Port was assigned to 5001 but the default is 5000.

  

	Devices = ./Tormach.xml
	AllowPut = true
	ReconnectInterval = 1000
	BufferSize = 17
	SchemaVersion = 1.7
	MonitorConfigFiles = true
	Pretty = true
	Port = 5001
	MinimumConfigReloadAge = 30

  

In this part, the host is the IP address of the machine in use. This port will be important when the MTConnect web UI is being accessed from another computer in the local network.

  

	Adapters {
		#Log file has all machines with device name prefixed
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



---
### How to start the Agent

1) Open terminal and run Tormach_adapter.py script.
2) Open a new terminal window and cd Documents/Tormach and run 'agent run'
3) If accessing from local computer, simply run http://localhost:5001 on the web browser`
4) If accessing from another computer in the same network, run http://{insertIPaddress}:5001
