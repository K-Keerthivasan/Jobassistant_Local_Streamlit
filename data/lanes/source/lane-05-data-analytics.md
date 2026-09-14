# Lane 5 | Data and analytics

NOC 21223, 21211, 21221, 21222, 12113. Priority lane. Read `00-index.md` for the Status conventions and tier rules.

**Status updated 2026-09-14.** Keerthi reviewed the full matrix and confirmed he can do every Must-tier and Important-tier item. Statuses below are `held` on his own confirmation. Optional and Later items stay `not yet` by his own ordering.

**PR note.** 21223, 21211, 21221 and 21222 are all TEER 1, among the strongest codes in the whole search. 12113 is TEER 2 and clears the floor. **No RCIP community list covers any lane 5 NOC, so never tag a lane 5 role RCIP.** AIP covers the lane entirely from a designated Atlantic employer, and Ontario's Workforce Priority stream takes any of them with a qualifying offer.

## NOC map

| NOC | Title | TEER | When it applies |
|---|---|---|---|
| **21223** | Database analysts and data administrators | **TEER 1** | Database design, data architecture, warehouse and data management work. The strongest code in the lane. |
| 21211 | Data scientists | 1 | Statistical modelling, machine learning, predictive analysis. Only where the posting genuinely asks for modelling rather than reporting. |
| 21221 | Business systems specialists | 1 | Requirements, process and systems analysis. Many business systems analyst and analytics analyst postings land here. |
| 21222 | Information systems specialists | 1 | Systems-side analysis and implementation. |
| 12113 | Statistical officers and related research support | 2 | The honest code for a junior reporting or data support seat doing no design or architecture. |

**The NOC comes from the duties in the body, never the title.** A "Data Analyst" building dashboards against a warehouse is 21223. The same title running requirements workshops is 21221. The same title pulling weekly numbers into a template is 12113. Write the code the duties support, not the flattering one, because that is what a CEC claim gets checked against later.

**12112 is Records management technicians and is not a data analyst code.** A "data" title doing filing, indexing, retention schedules and records requests is 12112 and a dead end for this lane.

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| SQL | SELECT, JOIN, GROUP BY, CTEs, subqueries, window functions, CASE, date functions, aggregations | held | Self-assessed, confirmed 2026-09-14. |
| Excel | Pivot tables, XLOOKUP, INDEX/MATCH, SUMIFS, charts, data cleaning, Power Query | held | Self-assessed, confirmed 2026-09-14. |
| Power BI | Data model, DAX, dashboards, filters, drill-through, KPI cards, Power Query | held | Self-assessed, confirmed 2026-09-14. |
| Python | pandas, NumPy, matplotlib, data cleaning and analysis | held | Self-assessed, confirmed 2026-09-14. Backed by production Python across the n8n and LLM pipelines. |
| Statistics | Mean and median, distributions, variance, correlation, confidence intervals, hypothesis tests | held | Self-assessed, confirmed 2026-09-14. |
| Business analytics | KPIs, trends, variance analysis, root-cause analysis | held | Self-assessed, confirmed 2026-09-14. Backed by campaign KPI and trend reporting for K2 Digital Media clients. |
| Data cleaning | Nulls, duplicates, incorrect data types, outliers, inconsistent categories | held | Self-assessed, confirmed 2026-09-14. Backed by transformation and normalisation work across the n8n pipelines. |
| Data visualization | Choosing the correct chart and explaining the finding clearly | held | Self-assessed, confirmed 2026-09-14. |
| Data storytelling | Turning numbers into a business recommendation | held | Self-assessed, confirmed 2026-09-14. Backed by client reporting at K2. |

## Important

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Git and GitHub | Projects, version control, README documentation | held | github.com/K-Keerthivasan, multiple maintained repos with documented READMEs. |
| APIs | Pulling JSON and API data and transforming it | held | n8n automation work and K2_Press, both API-driven with JSON transformation throughout. |
| Databases | PostgreSQL and MySQL basics | held | Self-assessed, confirmed 2026-09-14. Backed by Supabase, which is Postgres. |

## Optional

| Skill | Note | Status |
|---|---|---|
| Tableau | Useful alternative to Power BI, worth it only once Power BI is strong | not yet |
| R | Unnecessary while Python is the tool | not yet |

## Later

| Skill | Note | Status |
|---|---|---|
| Cloud | BigQuery, Snowflake, AWS basics | not yet |
| dbt | Analytics transformations and models | not yet |

## Not required

Machine learning beyond a basic conceptual understanding. Normal junior analyst roles do not ask for it, and a posting that hard-requires ML modelling is a 21211 data scientist seat that should be dropped rather than stretched into.

## Sourcing vocabulary

- **Core:** data analyst, junior data analyst, business intelligence analyst, BI analyst, BI developer, reporting analyst, analytics analyst, insights analyst, data operations analyst, business systems analyst, data quality analyst.
- **Tool-anchored, high signal:** Power BI developer, Power BI analyst, SQL analyst, Tableau analyst, data visualization analyst.
- **Adjacent, worth opening:** operations analyst, performance analyst, MIS analyst, decision support analyst, revenue analyst, marketing analytics analyst. Often real 21223 or 21221 seats wearing a department's name.

Two keyword variants minimum per Stream A run. Default pair is "data analyst" and "business intelligence analyst"; swap in "Power BI" and "reporting analyst" when the default pair comes back thin.

## What this changes for sourcing

With the Must tier `held`, **most junior analyst postings now grade Tier A rather than Tier C.** The standard hard-required trio of SQL, Excel and Power BI is covered, so the lane should start producing volume rather than dropping nearly everything. Expect lane 5 to become one of the largest contributors to a Stream A run.

## Honest positioning

Lead with the combination, because the combination is the unusual part: he can pull data through an API, clean and transform it in Python, query it in SQL, model it in Power BI, and then explain what it means to a client who does not care about any of that. Most junior analyst candidates have the middle three and not the ends. The pipeline work and the client reporting are what make the story coherent rather than a list of tools.

**One thing to be ready for.** These statuses are self-assessed rather than employer-verified, which is entirely normal for someone entering a lane, and it ships Tier A rows without any problem. What it does not do is survive a live SQL exercise on its own, and junior analyst screens are practical far more often than they are conversational. A public repo with a cleaned dataset, a documented SQL query set and a Power BI or matplotlib output turns the self-assessment into something an employer can check, and it is the single highest-leverage thing available in this lane. Note in the fit report whenever a posting asks for a portfolio or sets a take-home.

## Interview watch

Expect a live or take-home SQL exercise. Window functions and CTEs are the two things most often tested beyond basics. Expect "tell me about a time the data said something the business did not want to hear", which rewards a real example from client reporting. Expect a case question: here is a metric that dropped, how would you find out why. Answer it as a structured decomposition, not a guess list.

## Aliases

Alternate names the grader matches against posting text, one line per skill. The skill name before the colon must match a row in the tables above.

- SQL: sql, t-sql, structured query language, sql queries, mysql queries, postgresql queries, ctes, window functions, complex queries
- Excel: excel, microsoft excel, advanced excel, pivot tables, xlookup, vlookup, power query, spreadsheets, ms excel
- Power BI: power bi, powerbi, dax, bi dashboards, microsoft power bi, power bi desktop
- Python: python, pandas, numpy, matplotlib, jupyter, seaborn, python for data analysis
- Statistics: statistics, statistical analysis, hypothesis testing, regression analysis, descriptive statistics, statistical methods, quantitative analysis
- Business analytics: kpis, kpi reporting, business analytics, trend analysis, variance analysis, root cause analysis, business intelligence, bi reporting, performance metrics
- Data cleaning: data cleaning, data cleansing, data quality, data wrangling, data preparation, data validation, data integrity
- Data visualization: data visualization, data visualisation, dashboards, charts, visual reporting, looker studio, google data studio, reporting dashboards
- Data storytelling: data storytelling, presenting insights, stakeholder communication, insights, recommendations, communicate findings, presentation skills
- Git and GitHub: git, github, version control
- APIs: apis, rest api, json, api data, api integration
- Databases: postgresql, mysql, postgres, relational databases, database, databases, supabase, sql server, data warehouse basics
- Tableau: tableau, tableau desktop
- R: r programming, r language, rstudio, r
- Cloud: bigquery, snowflake, redshift, aws, azure, gcp, databricks, cloud data warehouse, data warehouse, azure synapse
- dbt: dbt, data build tool, analytics engineering
