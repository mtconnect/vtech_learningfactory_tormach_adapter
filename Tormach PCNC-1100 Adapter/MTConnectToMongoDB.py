import pymongo
import json
import requests
import time

# Connect to the MongoDB server
client = pymongo.MongoClient('mongodb://localhost:27017/')

# Select the database and collection to use
db = client['mydatabase']
collection = db['mycollection']

# MTConnect format testing purposes
# response = "2023-03-20T14:13:42.104677Z|Xabs|215.9|Yabs|11.5|Zabs|101.39999999999999|Srpm|5677.7|execution|EXEC_WAITING_FOR_MOTION"

# While loop that iterates infinitely to convert MTConnect string to JSON
while True:
    # Request to MTConnect 
    response = requests.get("http://localhost:5001/current")

    # Splits MTConnect data format
    fields = response.split("|")
    
    # Initialize data
    data = {
    }
    
    # While loop that parses through the MTConnect string and sends a field to data
    i = 1
    while i < len(fields):
        data[fields[i]] = fields[i + 1]
        i += 2
    print(data)

    #Convert the dictionary to a JSON string
    json_data = json.dumps(data)

    #Insert the JSON document into the collection
    collection.insert_one(json.loads(json_data))

    # sleep time matches adapter's to avoid missing data
    time.sleep(0.6)