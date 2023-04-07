from pymongo import MongoClient
import requests
from xml.etree import ElementTree
from collections import defaultdict
import time
import json
import random

# Set this variable to the URL of your MTConnect Agent server. Be sure to use the /current endpoint.
MTCONNECT_URL = "http://localhost:5001/current"

# Get these variables from your Atlas portal for the cluster you want to use
# TODO: Improve documentation for getting connection string from Atlas
ATLAS_USERNAME = "SD_Team"
ATLAS_PASSWORD = "ISESD2"
MONGODB_CONNECTION_STRING = f"mongodb+srv://{ATLAS_USERNAME}:{ATLAS_PASSWORD}@firstcluster.u1xe7sf.mongodb.net/?retryWrites=true&w=majority"

# Change these variables to create and use a new database or collection
MONGODB_DATABASE_NAME = "dashboard_data"
MONGODB_COLLECTION_NAME = "collection_8"

# Set this variable to the number of seconds between stored records.
# Ensure this is at least 2x the frequency of any dashboard updates!
RECORD_INTERVAL = 2


def etree_to_dict(tree):
    """
    Necessary helper method to convert element trees (XML) to Python dict/JSON
    """
    d = {tree.tag: {} if tree.attrib else None}

    children = list(tree)
    if children:
        dd = defaultdict(list)
        for dc in map(etree_to_dict, children):
            for k, v in dc.items():
                dd[k].append(v)
        d = {tree.tag: {k: v[0] if len(v) == 1 else v for k, v in dd.items()}}
    if tree.attrib:
        d[tree.tag].update(("@" + k, v) for k, v in tree.attrib.items())
    if tree.text:
        text = tree.text.strip()
        if children or tree.attrib:
            if text:
                d[tree.tag]["#text"] = text
        else:
            d[tree.tag] = text
    return d


# Sets the 0th record number to store (first record will be stored with subsequent number).
# Use this when adding data to an existing collection to avoid doubling record numbers; set 0 for new collection.
record_number = 0

# Runs continuously, collects data from MTConnect agent and stores to MongoDB
while True:
    # Increment record number
    record_number = record_number + 1

    # Get data from MTConnect agent
    response = requests.get(MTCONNECT_URL)
    response_string = response.text
    tree = ElementTree.fromstring(response_string)

    # Convert device data to dict format for mongo storage
    record = json.loads(
        json.dumps(etree_to_dict(tree)).replace(
            "{urn:mtconnect.org:MTConnectStreams:1.7}", ""
        )
    )

    # Extract arrayed data items into nested dictionary entries for Mongo
    machines = 0
    available_machines = 0
    active_machines = 0
    for device in record["MTConnectStreams"]["Streams"]["DeviceStream"]:

        # TODO: Ask AMT - Will this work if there are multiple machines in the fleet with the same name? Is that even possible in MTConnect (e.g. might be a non issue?)
        # Determine name of device stream
        device_name = device["@name"]
        if device_name != "Agent":
            machines += 1
        # Extract components in ComponentStream to nested dict entries for Mongo
        for component in device["ComponentStream"]:
            component_name = component["@component"]
            device[component_name] = component

        # Convert numeric values stored as strings to true numeric
        if "Rotary" in device.keys():
            device["Rotary"]["Samples"]["RotaryVelocity"]["value"] = float(
                device["Rotary"]["Samples"]["RotaryVelocity"]["#text"]
            )

        # Clean up doubled data in record
        del device["ComponentStream"]

        # Store reformatted device data to record
        record[device_name] = device

        # Check availability for Charts display
        if (device_name != "Agent") and device["Device"]["Events"]["Availability"][
            "#text"
        ] in ["STATE_ON"]:
            available_machines += 1

        # Check activity for Charts display
        if (device_name != "Agent") and device["Path"]["Events"]["Execution"][
            "#text"
        ] in ["ACTIVE"]:
            active_machines += 1

    # Clean up doubled data in record
    del record["MTConnectStreams"]["Streams"]

    # Add extra simulated data for fleet management demo
    for device_name in [
        "Haas",
        "UR5",
        "Tormach_2",
        "Tormach_3",
        "Tormach_4",
        "Tormach_5",
        "Tormach_6",
    ]:
        machines += 1
        device = {
            "Device": {"Events": {"Availability": {"#text": ""}}},
            "Path": {"Events": {"Execution": {"#text": ""}}},
        }
        rand1 = random.random()
        rand2 = random.random()
        if rand1 < 0.97:
            device["Device"]["Events"]["Availability"]["#text"] = "STATE_ON"
            available_machines += 1
            if rand2 < 0.85:
                device["Path"]["Events"]["Execution"]["#text"] = "ACTIVE"
                active_machines += 1
            elif rand2 < 0.93:
                device["Path"]["Events"]["Execution"]["#text"] = "READY"
            elif rand2 < 0.94:
                device["Path"]["Events"]["Execution"]["#text"] = "INTERRUPTED"
            elif rand2 < 0.95:
                device["Path"]["Events"]["Execution"]["#text"] = "WAIT"
            elif rand2 < 0.96:
                device["Path"]["Events"]["Execution"]["#text"] = "FEED_HOLD"
            elif rand2 < 0.97:
                device["Path"]["Events"]["Execution"]["#text"] = "STOPPED"
            elif rand2 < 0.98:
                device["Path"]["Events"]["Execution"]["#text"] = "OPTIONAL_STOP"
            elif rand2 < 0.99:
                device["Path"]["Events"]["Execution"]["#text"] = "PROGRAM_STOPPED"
            else:
                device["Path"]["Events"]["Execution"]["#text"] = "PROGRAM_COMPLETED"
        elif rand1 < 0.98:
            device["Device"]["Events"]["Availability"]["#text"] = "STATE_OFF"
            device["Path"]["Events"]["Execution"]["#text"] = "STOPPED"
        elif rand1 < 0.99:
            device["Device"]["Events"]["Availability"]["#text"] = "STATE_ESTOP"
            device["Path"]["Events"]["Execution"]["#text"] = "INTERRUPTED"
        else:
            device["Device"]["Events"]["Availability"]["#text"] = "STATE_ESTOP_RESET"
            device["Path"]["Events"]["Execution"]["#text"] = "STOPPED"

        record[device_name] = device

    # Add record sequence and availability metric to metadata for charts
    record["RecordNumber"] = record_number
    record["Total Machines"] = machines
    record["Available Machines"] = available_machines
    record["Aggregate Availability"] = 100 * available_machines / machines
    record["Active Machines"] = active_machines
    record["Production Level"] = 100 * active_machines / machines

    # Send device data to database
    client = MongoClient(MONGODB_CONNECTION_STRING)
    client[MONGODB_DATABASE_NAME][MONGODB_COLLECTION_NAME].insert_one(record)
    print(f"successfully updated database: {record_number}")
    time.sleep(RECORD_INTERVAL)
