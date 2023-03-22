import time
import xml.etree.ElementTree as ET
import requests
import sys
import datetime

def main(MTConnectURL, server_URL):
    if MTConnectURL[-1] != "/":
        MTConnectURL += "/"
    
    if server_URL[-1] != "/":
        server_URL += "/"

    while True:
        response = requests.get(MTConnectURL + "current")
        rawXML = response.text

        root = ET.fromstring(rawXML)
        #namespace = root.attrib["xmlns"]
        #print("namespace:", namespace)

        for child in root:
            print(child.tag)

        device = root.find(".//{urn:mtconnect.org:MTConnectStreams:1.5}DeviceStream")
        print(device)
        serverRequest = {
            "header": device.attrib["name"] + "_" + device.attrib["uuid"],
            "body": []
        }
        print(serverRequest)

        dataItems = root.findall(".//*[@dataItemId]")
        print(len(dataItems))
        for dataItem in dataItems:
            serverRequest["body"].append({
                "name":dataItem.attrib["dataItemId"],
                "value":dataItem.text,
                "timestamp":datetime.datetime.strptime(dataItem.attrib["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
            })

        response = requests.post(server_URL + "api/devices/registerData", json=serverRequest)
        print(response.text)
        time.sleep(1)



if len(sys.argv) < 3:
    print("expecting 2 arguments, Agent_URL and Server_URL")
    print("example: python http://192.168.1.2:5000 http://192.168.1.7")
    sys.exit()

main(sys.argv[1], sys.argv[2])