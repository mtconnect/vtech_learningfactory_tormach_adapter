# Grafana Dashboard for MTConnect Data Stored in MongoDB

As a **proof-of-concept use case,** the AMT/Virginia Tech development team built a real-time dashboard in Grafana capable of visualizing MTConnect agent data stored in MongoDB with the `database_link.py` Python script. This example dashboard includes panels that display real-time operational data such as a specific machine's emergency-stop status or spindle speed, panels that display aggregated data across an entire fleet of MTConnect-compliant machinery to visualize a shop's overall productivity level or network connectivity issues, and period-run data reports to present a look back at overall productivity or machine availability over a specific period.

With proper implementation and extension, these dashboard panels and others like them can:
- Help manufacturing shops to focus on safety and consistency
- Help production managers to more easily supervise large shops and to build production reports more quickly and accurately
- Help shops focused on **Lean production** to identify equipment that is underutilized or consistently problematic to run

This documentation will cover deploying the sample dashboard included with this project, as well as extending this dashboard to create custom display panels for your organization or manufacturing environment.
  

## Deploy Dashboard into Grafana

The dashboard we created in Grafana was formatted into a JSON file in the repository. In the Grafana dashboard, it gives the option to import a dashboard model, so we uploaded the JSON dashboard model into the dashboard.

  

## Connect Data to MongoDB Compass

Due to unforeseen circumstances, MongoDB Compass could not function as a dashboard in real time, allowing it to only be a source for data storage. MongoDB Compass can be connected to a data source where the data is taken continuously, but it requires a few key items:

*MTConnect URL  -URL to MTConnect Agent Server

*MongoDB Connection URL  -URL to Atlas Server

*MongoDB Database Name  -Name of Database in MongoDB database

*MongoDB Collection Name  -Collection Name of Database in MongoDB database

  

To find the MongoDB Connection URL we logged into MongoDB Atlas, under the Database Deployments we found our database and clicked Connect where there are many ways to connect the data to the database. For these options we used Connect your Application, then under driver and version we used Python as the driver and then under version we used 3.6 or later. Finally, under step 2 Add your connection string into your application code make sure to check Include full driver code example and copy and paste the code below it. When it is copy and pasted, replace the <password> for the password and <username> for the username of the database.

  
  

## Connect MongoDB to Grafana

  

To connect MongoDB to Grafana we used the MongoDB add-on in Grafana. When the Grafana account was created we then launched Grafana in the Account portal. From the Grafana portal we went to Connect Data and found the MongoDB add-on in the search panel. With the free trial of Grafana, we could add one free add-on and so in the MongoDB add-on we installed it onto our Grafana account. Then under Create a Mongo Data Source we copied the connection string from MongoDB Atlas and pasted the connection string under the connection string. Under Authentication, we checked Credentials and entered the username and password for the connection string of the database. To connect this MongoDB database to a dashboard we first went into the menu and went under Dashboard. Then under New we used New Dashboard then went to Add a new panel. Under the Query section there is a tab called Data Source and under it we found our MongoDB data source.