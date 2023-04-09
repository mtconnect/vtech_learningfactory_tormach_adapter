# Database Link for MTConnect Agent and MongoDB

## About

The `database_link.py` Python script is an essential component in linking an existing MTConnect Agent deployment to MongoDB for time-series recordkeeping and further extensibility. The script queries the MTConnect Agent for current data, processes that data for ingestion, and delivers the resulting record to a MongoDB collection for storage and analysis.

In creating this project, MongoDB's cloud version, Atlas, was implemented for easier access from any IP address connected to the internet. The documentation provided follows this Atlas-based use case; minor changes will be necessary for use with a local database installation, which should be elementary for developers with any amount of experience in MongoDB.

The `database_link.py` Python script includes a helper function that will convert XML formatted element trees to the Python dictionary variable type, which is necessary for processing the data received from the Agent. The script then, on an infinite loop, performs the following operations:

1.  Increment the `record_number` field - this data field or the attached timestamps can both be used sort and query records
    
2.  Get the **current** data from the MTConnect Agent via a simple http request
    
3.  Convert this data into XML format, remove garbage substrings from the data, and then convert to Python dictionary format
    
4.  Extract and elevate specific data items of interest to the root of the record for easier querying in MongoDB
    
5.  Calculate overall availability and productive activity level for an aggregate of all manufacturing devices listed by the Agent, based on the MTConnect AVAILABILITY and EXECUTION data items
    
6.  PROTOTYPE ONLY: Simulate randomized data for the above two data items across a fleet of several virtual machines, in order to show Grafana dashboard use cases for such calculations. This section of the script is clearly marked in the code, and should be removed in a production environment.
    
7.  Append calculations from Step 5 to the root of the data record to be stored
    
8.  Store data record to a MongoDB Atlas cluster - must first create a cluster through MongoDB Atlas. However, it is not necessary to previously create a database or collection; if no database/collection by the specified name is found in the given MongoDB cluster, the software will automatically create a new database/collection by name.
    
9.  Wait for a user-definable period between data records (default 2 seconds)
    

  

## Installation

Before installing this software, make sure you have access to a working deployment of the MTConnect Agent and have instantiated a MongoDB Atlas Cluster to host your database.

The first section of this Python script contains several global variables that must be configured before deployment. These include, in order of appearance in the script:

1.  MTCONNECT_URL: The URL address of the MTConnect agent to connect to. Be sure to use the /current endpoint.
    
2.  ATLAS_USERNAME: A credential one must configure in MongoDB Atlas for access. This is not the username for you as a user to log into your account, but rather a delegated credential for access to the intended cluster specifically.
    
3.  ATLAS_PASSWORD: A password to match the Atlas username; see above.
    
4.  MONGODB_CONNECTION_STRING: This string can be pulled from Atlas, and is very similar to the string used to connect MongoDB’s graphical database exploration tool, Compass. Depending on how you pull the string from Atlas, it may already contain the username and password embedded within.
    
5.  MONGODB_DATABASE_NAME: The name of the database you would like to instantiate or add records to. If no database by this name is found in the cluster specified by the previous string, then one will be created.
    
6.  MONGODB_COLLECTION_NAME: The name of the collection within your database where you would like these records stored. As with the database, if no collection is found by name, a new collection will be created.
    
7.  RECORD_INTERVAL: The time, in seconds, for the software to wait between collecting each data record. Default value is 2 seconds. Make sure this update interval is at least twice as frequent as any intervals for updating graphical dashboards further down the pipeline!
    

  

Once these variables have been configured, you can run this script on any Linux or Windows PC with network access to your MTConnect Agent and MongoDB Cluster. Other platforms have not been tested, but should work similarly.

  

## Usage

Once the Installation steps above have been followed, simply leave this script running as a background process to continuously collect data from the MTConnect Agent and store to MongoDB. From here, you can install MongoDB Compass to filter, query, and inspect records for key information or to build long-term data reports, or you can install Grafana or any other visualization tool compatible with MongoDB to build a real-time dashboard for your MTConnect-compatible manufacturing shop.