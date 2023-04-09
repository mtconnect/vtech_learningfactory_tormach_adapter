# Digitally Connected Manufacturing: A 2023 MTConnect Use Case Study at the Virginia Tech Learning Factory

Digitization and data sciences can be intimidating fields, and adapting legacy industrial equipment to modern standards can be a difficult undertaking. In this project, a team of undergraduates in the Virginia Tech Learning Factory attempted to adapt a legacy Tormach milling center to the MTConnect industrial data standard, and developed a proof-of-concept use case for MTConnect data that could help manufacturing organizations to run leaner operations, generate more accurate reports, and identify recurring issues in quality control, regardless of the specific machinery on their shop floor.

## Browsing this Repository

The work on this project can be divided into discrete components, **each with its own folder and Readme file**:
1. The **Simulator**: A script to simulate a Tormach PCNC-1100 milling center's internal operating data, as the team was not provided or able to procure an operational Tormach mill during the seven-month duration of the project
2. The MTConnect **Adapter** developed for the simulated Tormach PCNC-1100, which should be compatible with a real, operational instance of the machine
3. The **Database Link**, a Python script to periodically collect data from any deployment of the MTConnect Agent and store data records to a time-series MongoDB database collection
4. The **Dashboard**, a custom Grafana dashboard configuration built to display real-time and period-average statistics in an easily digestible visualization, with the primary intended audience being industrial production managers and facility engineers

This project was built to comply with MTConnect version 1.8; for more information on the MTConnect standard and MTConnect Agent, please see [MTConnect's official documentation](https://www.mtconnect.org/documents).

Each component is covered in more detail in its own Readme file, i.e. `$/Dashboard/ReadMe.md`.
