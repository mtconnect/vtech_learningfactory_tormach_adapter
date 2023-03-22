from pymongo import MongoClient
import requests
from xml.etree import ElementTree
from collections import defaultdict
import time
import json
import random

# Set this variable to the URL of your MTConnect Agent server
MTCONNECT_URL = "http://localhost:5001/current"

# Get this string from your Atlas portal for the cluster you want to use
# TODO: Improve documentation for getting connection string from Atlas
MONGODB_CONNECTION_STRING = f"mongodb+srv://SD_Team:ISESD2@firstcluster.u1xe7sf.mongodb.net/?retryWrites=true&w=majority"

# Change these variables to create and use a new database or collection
MONGODB_DATABASE_NAME = 'dashboard_data'
MONGODB_COLLECTION_NAME = 'collection_8'



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
        d = {tree.tag: {k: v[0] if len(v) == 1 else v
                     for k, v in dd.items()}}
    if tree.attrib:
        d[tree.tag].update(('@' + k, v)
                        for k, v in tree.attrib.items())
    if tree.text:
        text = tree.text.strip()
        if children or tree.attrib:
            if text:
                d[tree.tag]['#text'] = text
        else:
            d[tree.tag] = text
    return d
    
record_number = 5000
# Stores a set number of records to database. TODO: Set this to run continuously ('while True') for production
while record_number < 6000:
    # Increment record number
    record_number = record_number + 1

    # Get data from MTConnect agent
    response = requests.get(MTCONNECT_URL)
    response_string = response.text
    tree = ElementTree.fromstring(response_string)

    # Convert device data to dict format for mongo storage
    record = json.loads(
        json.dumps(
            etree_to_dict(tree)).replace('{urn:mtconnect.org:MTConnectStreams:1.7}', '')
        )
    
    # Extract arrayed data items into nested dictionary entries for Mongo
    machines = 0
    available_machines = 0
    for device in record['MTConnectStreams']['Streams']['DeviceStream']:
        
        # TODO: Ask AMT - Will this work if there are multiple machines in the fleet with the same name? Is that even possible in MTConnect (e.g. might be a non issue?)
        # Determine name of device stream
        device_name = device['@name']
        if device_name != "Agent":
            machines += 1
        # Extract components in ComponentStream to nested dict entries for Mongo
        for component in device['ComponentStream']:
            component_name = component['@component']
            device[component_name] = component

        # Convert numeric values stored as strings to true numeric
        if 'Rotary' in device.keys():
            device['Rotary']['Samples']['RotaryVelocity']['value'] = float(device['Rotary']['Samples']['RotaryVelocity']['#text'])

        # Clean up doubled data in record
        del device['ComponentStream']

        # Store reformatted device data to record
        record[device_name] = device

        # Check availability for Charts display
        if (device_name != "Agent") and device['Device']['Events']['Availability']['#text'] in ['STATE_ON']:
                available_machines += 1
                

    # Clean up doubled data in record
    del record['MTConnectStreams']['Streams']

    # Add extra simulated data for fleet management demo
    for device_name in ["Haas", "UR5", "Tormach_2", "Tormach_3", 'Tormach_4', "Tormach_5", 'Tormach_6']:
        machines += 1
        device = {
            'Device': {
                'Events': {
                    'Availability': {
                        '#text': ""
                    }
                }
            }
        }
        rand = random.random()
        if rand < 0.91:
            device['Device']['Events']['Availability']['#text'] = 'STATE_ON'
            available_machines += 1
        elif rand < 0.94:
            device['Device']['Events']['Availability']['#text'] = 'STATE_OFF'
        elif rand < 0.97:
            device['Device']['Events']['Availability']['#text'] = 'STATE_ESTOP'
        else:
            device['Device']['Events']['Availability']['#text'] = 'STATE_ESTOP_RESET'
        
        record[device_name] = device        


    # Add record sequence and availability metric to metadata for charts
    record['RecordNumber'] = record_number
    record['Total Machines'] = machines
    record['Available Machines'] = available_machines
    record['Aggregate Availability'] = 100 * available_machines/machines

        

    # Send device data to database
    client = MongoClient(MONGODB_CONNECTION_STRING)
    client[MONGODB_DATABASE_NAME][MONGODB_COLLECTION_NAME].insert_one(record)
    print(f"successfully updated database: {record_number}")
    rotary_velocity = record['Tormach-PCNC1100']['Rotary']['Samples']['RotaryVelocity']['#text']
    print(f'rotary velocity: {rotary_velocity}')
    time.sleep(2)



