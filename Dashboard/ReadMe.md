# MTConnect Dashboard

This proof-of-concept sample dashboard, built with Grafana, was built with industrial production managers in mind. The display panels allow the user to see real-time statistics or alarms for specific machines, aggregate productivity statistics and machine status across an entire shop, and can be configured to display period-average aggregations of these same statistics to quickly generate reports. 

With proper implementation and extension, these dashboard panels and new additions like them can:
- Help manufacturing shops to focus on safety and consistency
- Help production managers to more easily supervise large shops and to build production reports more quickly and accurately
- Help shops focused on **Lean production** to identify equipment that is underutilized or consistently problematic to run

This dashboard was built in **Grafana Cloud Pro** and with MongoDB Atlas for easy access and visibility over the world wide internet. It should work with a local, free installation of Grafana software, but this has not been tested. This documentation will guide you through the installation, deployment, and customization options for this dashboard.

## Prerequisites

Before starting, you must have:
- A Grafana Cloud Pro or Enterprise account (this dashboard should work with a local, free installation of Grafana software, but this has not been verified)
- A MongoDB database and collection with data records stored by the `database_link.py` script from this project

## Connecting Grafana to MongoDB

Before launching your dashboard, let's get Grafana to recognize your MongoDB collection as a data source. First, you must **install the MongoDB Data Source plugin**.  As of April 2023, poor UX design on Grafana's part means that **this looks like it can be installed in the Grafana Cloud web app, but this will not work. Instead, navigate directly to the [Grafana Plugins page](https://grafana.com/plugins), log in to your Grafana Cloud Pro account, and install the MongoDB Data Source Plugin.**

Now, **launch a new Grafana Cloud instance** by navigating to My Account at Grafana.com and selecting "Add Stack" under Grafana Cloud in the left sidebar. Once your instance is ready, select Launch.

Next, **connect your MongoDB collection** by searching connections for MongoDB; you should see a green checkmark and "installed" on the plugin's display card if the previous steps have been done correctly. Open the plugin, and select "Create a MongoDB data source." Rename the data source if desired, and enter the Connection string from MongoDB Atlas or MongoDB for the cluster containing your database and collection (see MongoDB docs for more information). You may need to create a database user for access credentials, first. Once your connection string is entered, select "Save & test," and ensure a successful plugin health check before continuing.

Now we can **deploy the dashboard from the json model.** Go back to the Home page of the Grafana Cloud web app, and navigate to Dashboards > All Dashboards > New (drop down selection) > Import.  Here, you can upload the `grafanaModel.json` file found in this project. Rename the dashboard and change the folder if desired, then click Import to confirm. You should immediately see a dashboard of empty panels, with no data.

The very **first thing** we need to do with this empty dashboard is to **configure our dashboard variables.** Go to Dashboard Settings > Variables, and you should see two variables called `database_name` and `collection_name`. These values are referenced in every pre-configured panel query so that the entire dashboard can be pointed to a new data source at any time. Set these values to the names of the MongoDB database and collection that `database_link.py` is storing records in.
  

Next, to **get the first panel working**, select the panel title in the top left and then Edit. Change the data source to MongoDB, and then in the grafanaModel json file, locate the string stored at `$.panels[0].targets[0].query`. Copy this query string into Grafana; you should notice that the database name and collection name in the query are parameterized, and will automatically reference the variables we just created in the last step. If your collection contains valid data, you should immediately see the gauge render a valid output at some percentage.

To **connect all other panels**, navigate to Dashboard Settings > JSON Model. Note the `datasource` data now stored at `$.panels[0].datasource`. It should show:

	"datasource":  {
		"type":  "grafana-mongodb-datasource",
		"uid":  "#This string will vary"
	},

Make sure you are looking at the panel that you have updated - it should show a different UID than all other panels. Copy this data to all other items in the `panels` array, overwriting existing data. Make sure to click "Save changes" at the bottom of the screen, and then "Save dashboard" in the top right if you would like to add a note for version history. Close settings and return to your dashboard, and you should now see at least the first two columns displaying valid renderings.

## Sample Panel Descriptions

The panels included with this sample dashboard are split into three columns. The first two columns represent aggregated data across an industrial machine fleet, and should work immediately with your database; the final column represents data for a specific machine, and will likely require some extra configuration.

> Known issue: while templated queries deployed from a JSON model appear to work just fine, Grafana does not appear to properly display these queries in the usual place when editing an existing panel. To see the original queries for context, check the JSON model at `$.panels[{panel_number}].targets[0].query`

**In the first column**, we look at MTConnect-defined **Availability** across an entire production fleet. This is a simple check for whether the MTConnect Agent can see and receive data from each machine, and should typically be 95-100%. This data can help us to identify machines or MTConnect adapters that are consistently encountering data communication errors.

If you explore the "Fleet Availability" panel Options > Value mappings, you will see that a **regular expression-based edit** is applied to transform all JsonPath expressions representing each machine into a simple name, based on that machine's identifier in the MTConnect Agent. Additionally, custom value mappings have been applied to some machines; while these will have no effect on your dashboard unless the name(s) of your machine(s) happen to match the development team's, this provides an example of how each machine can be manually renamed for display purposes.

In the Dashboard's **second column**, you will see visualizations for Production Level. This real-time aggregate statistic is calculated by taking the most recent record, which includes a tally of all machines recognized by the MTConnect agent as well as all machines where the MTConnect `Execution State` data item is currently `Active`, and dividing the latter by the former.  This gauge allows production managers to get a quick glance at an estimate of shop productivity at any time; if you open the panel and navigate to **Options > Thresholds**, you will see that the development team has applied default values of 60 and 80 percent, but these targets will vary by manufacturing shop and should be changed as desired.

Below the gauge, a table allows production managers to get a more detailed look at exactly which machines are in what execution state at any time. Again, you'll see a RegEx-based value mapping to clean up JsonPath formatting for machine names as in the Fleet Availability table, as well as some custom name transformations.

In the Dashboard's **third column**, we finally have display panels focused on a single, specific machine that may be of interest to the kiosk user.  **Note that these panels may not render correctly at initialization, as the queries will need to be edited to reference a specific machine in your data set.** However, if you are using the Tormach simulator and adapter in this project with your deployment of the MTConnect agent, then these panels should render automatically.

The top panel displays a line graph of spindle speed (standardized by MTConnect as Rotational Velocity) over a preceding period for a Tormach milling center.  This proof-of-concept simply **demonstrates how any time-series integer value in the MTConnect data standard can easily be visualized in Grafana from MongoDB**.

The second panel displays a **real-time readout for a non-numeric data item** - in this case, Emergency Stop Status (defined in MTConnect as `EMERGENCY_STOP`).  If you again explore the panel's value mappings, you will see that the panel has been configured to display the value `ARMED` as a bright green readout of "`ARMED (READY)`" to improve the clarity of this information to less technical users.  Upon a change in the data to `TRIGGERED`, the panel will display this new value in red. Research suggests that this readout could also be linked to physical lights or sirens, allowing for real alarms to be triggered if machine operations fall out of a particular range or threshold - see the Grafana documentation on Alarms for more information.

The final panel displays a **history** of the Tormach milling center's **execution state**. This, by default, is limited to the last 120 records, which---when combined with the default 2 second document storage interval from this project's `database_link.py` script---equates to the last minute of history. By editing the panel's data query, you can adjust how far back this panel will search, or aggregate the data to find the percentage of time the machine spent in each execution state over a specific interval of time, such as the last week or month.

## Building Additional Panels

With the basics covered, adding new types of display panels is easy. Try creating a panel to generate a weekly productivity report for one of the machines in your database:
1. Select "Add New Panel" and choose the Table panel type
2. Query your database for a particular machine's metadata over a particular lookback interval. Here, we'll query for the Tormach PCNC-1100 over the last 1 week. At one data record per 2 seconds, that equates to the last 302,400 records. We'll access a database named `mtconnect_database` and a collection named `collection_0`, where data has been stored for a machine named `Tormach-PCNC1100`:

		mtconnect_database.collection_0.aggregate([
			{'$project': {'_id': 0,  'RecordNumber': 1,  'Tormach-PCNC1100.Path.Events': 1}},
			{'$sort': {'RecordNumber': -1}},
			{'$limit': 302400},
			{'$group': {'_id': '$Tormach-PCNC1100.Path.Events.Execution.#text',  'Count': {'$sum': 1}}},
			{'$project': {'Count': 1,  'Percentage': {'$divide': ['$Count',  3024]}}}
		])

	This aggregation performs the following steps:
	1. In order to conserve memory before/during sorting, only the relevant fields are **projected** from the data set (`RecordNumber` and `Tormach-PCNC1100.Path.Events`)
	2. The records are **sorted** in reverse, in order to find our most recent data
	3. The records are **limited** to the last 302,400 entries, representing the last week of data. Older entries are ignored and removed from the process.
	4. The records are **grouped** and returned as a new set of records, where `_id` is a valid Execution State, and `Count` is the number of records in the data set where that Execution State was represented
	5. Finally, we use another **projection** to calculate a `Percentage` field for each Execution State as a division of each `Count` by the total number of records in the intended subset, divided by 100 in order to represent percentage as a whole number.

3. If all other steps have been implemented correctly, and variable names for database, collection, and machine name in the above query are valid, then you should now see a readout of execution states, the total number of records over the last week matching each state, and a calculated percentage of records matching each state as well. You can use Transform > Organize Fields to order and rename your columns.  This configuration updates automatically, always showing aggregated statistics over the last 168 hours (one week), but you can easily generate aggregate reports for a specific period of time:
	1. Add a new argument to the Project step at the beginning of the aggregation that returns only records where `MTConnectStreams.Header.@CreationTime` is within a specific range of values
	2.  Remove the Limit step from the aggregation pipeline, and adjust the division during the final Projection step to account for the total number of records within your desired time period. Again, divide this number by 100 if you wish to represent percentages as whole numbers.

	With these tools, you can quickly build dynamic or static reports for any machine, group of machines, or entire fleet and for any data item in the MTConnect standard.