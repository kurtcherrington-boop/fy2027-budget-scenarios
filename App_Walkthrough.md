# How the scenario app works: a walkthrough

This explains the app in the order you would build it. Open `app.py` alongside it; the comments marked `STREAMLIT` in the code match the numbered ideas below.

## The one idea: the script re-runs

A Streamlit app is an ordinary Python script. `streamlit run app.py` runs it top to bottom and turns each `st.` call into something on the page. When you move a slider, Streamlit runs the **whole script again** with the slider's new value and redraws the page.

You never write "when the slider changes, update the chart". You write "read the sliders, compute, draw", and Streamlit repeats it on every change. That is why the math lives in a separate file: every re-run calls the same functions with new inputs.

```
sliders (sidebar)  ->  Drivers(...)  ->  budget_model.budget()  ->  metrics / bridge / tables  ->  st.metric, charts, tables
```

## The Streamlit pieces, in the order they appear in app.py

1. **`st.set_page_config(layout="wide")`**: page title and full-width layout. It must be the first Streamlit call.
2. **`@st.cache_data`**: remembers a function's result. Because the script re-runs on every slider move, the CSV files would otherwise be read again each time. With the cache they are read once.
3. **`with st.sidebar:`**: everything inside goes into the left panel.
4. **`st.session_state`**: a dictionary that survives re-runs. A widget created with `key="rent_growth"` keeps its value in `st.session_state["rent_growth"]`. The Low / Base / High buttons write new values into session_state, and that moves the sliders.
5. **`on_change=apply_preset`**: a function Streamlit calls before the next re-run, so the sliders already show the preset when the page redraws.
6. **`st.slider(label, min, max, step=..., key=...)`**: returns the current value. The other inputs work the same way: `st.number_input`, `st.selectbox`, `st.toggle` and `st.radio`.
7. **`st.expander`**: a collapsible box, used here for model assumptions and data upload.
8. **`st.file_uploader`**: lets the viewer drop in a file. It returns `None` until they do. This is how a real-data baseline gets in when you run the app locally.
9. **`st.container()`**: reserves a spot on the page to fill later. The KPI tiles need the computed numbers but sit above the tabs, so their spot is reserved first.
10. **`st.tabs([...])`**: one container per tab. Tabs can be filled in any order. The assumptions tab is filled first because its table feeds every number.
11. **`st.data_editor`**: an editable table that returns the edited copy. Change a property's occupancy or debt and the page recalculates.
12. **`st.columns(5)` + `st.metric`**: five KPI tiles side by side, each with its change versus the TTM actual.
13. **`st.plotly_chart`**: shows a Plotly figure. `go.Waterfall` draws the bridge: blue bars help, rust bars hurt, grey bars are totals.
14. **`st.dataframe` + `column_config`**: tables with formats (accounting, percent) and column widths.
15. **`st.download_button`**: hands the viewer a CSV of the FY2027 budget by entity and line.
16. **`st.radio(..., key="start_from")` under Data in the sidebar**: chooses the starting point, either the FY2027 momentum baseline (forecast.csv) or the TTM actuals as booked. Every number on the page follows it.
17. **`st.dataframe(df.style.format(...))`**: a pandas Styler, for number formats that `column_config` doesn't offer (the by-property table on the Baseline forecast tab).
18. **`st.warning` / `st.info` / `st.caption`**: message boxes and small print. Markdown treats `$...$` as a math formula, which is why dollar signs in captions are escaped by `md()`.

## The model (budget_model.py), in plain terms

**Start.** The drivers start from the **FY2027 momentum baseline** that the pipeline's `BaselineForecaster` writes in notebook step 4c (`data/forecast.csv`). It is the TTM normalized for the pipeline's adjustments, projected line by line:

- A seasonal property repeats its own same month last year.
- Months a property didn't operate under our ownership are borrowed from peers in its family, using the approach that won the backtest. In the demo that is Bluewater (bought in May) and Elm Street's stopped September.
- Steady assets (apartments, storage, industrial) run at their latest run-rate.

The **Baseline forecast** tab shows it by month with its 80% band and the backtest leaderboard. The bridge's first bar, "Momentum baseline", is the step from TTM actual to this starting point.

Switch "Drivers start from" to **TTM actuals** to use the books as booked; a partial-year property is then scaled up by its peers' full-year / same-months revenue ratio (Bluewater ×1.515). The line-by-line forecast gives a Base net income $0.25M lower than the gross-up, because winter months carry costs and interest but little revenue.

**Drivers, applied in this order.** The bridge reports each one's dollar effect in the same order:

| # | Driver | Rule |
|---|---|---|
| 1 | Occupancy | core and ancillary revenue × (baseline occupancy + change) / baseline occupancy; cost of sales follows |
| 2 | Rent growth | core revenue × (1 + growth) |
| 3 | Opex inflation | operating expenses × (1 + inflation), except cost of sales and intercompany fees |
| 4 | Interest rates | debt × floating share × rate change |
| 5 | Raise pace | new commitments × asset management fee × share of the year earned |
| 6 | Deployment | purchase price = raise × deployed % / (1 − LTV); NOI = price × cap rate × share of the year; interest on the new loan; acquisition fee = price × fee rate |

**Intercompany.** Fees between funds, properties and the management company are left out of consolidated revenue, opex and NOI. They cancel, and a test checks it. The management company's fee income is shown on its own: the "fees to the parent" view.

**Bridge.** Drivers switch on one at a time, so the bars add up exactly to the FY2027 number. A test checks it for every scenario and every metric.

## Talking points for a CFO audience (accuracy vs. interpretability)

- **No fitted model.** Every number is arithmetic on a named driver and a named assumption. A board member can ask "why is NOI up $1.3M?" and the bridge answers it bar by bar.
- **The budget is a commitment, not a forecast.** Low / Base / High give the range. Base means a 50% chance each assumption is too high and 50% too low. Anything under about 50% probability belongs on the risks and opportunities list, not in Base.
- **The baseline's quality is visible.** The Data quality tab shows the consolidation checks and open findings, and a PROVISIONAL banner shows while any check is open. A budget built on unresolved findings inherits them.
- **Tested.**
  - 17 model tests: the 8 rules run on both starting points (the forecast and the TTM). The bridge adds up, intercompany cancels, rent growth touches only core revenue, the rate change equals floating debt × the rate move, and the deployment and fee arithmetic hold. One more checks that the forecast is the starting point.
  - 4 app tests: the app runs, the presets move the sliders and the numbers, a slider marks the scenario as adjusted, and switching the starting point changes the numbers.
- **Where a more "accurate" model could help later.** Occupancy and rent by property from a seasonal forecast (the Week 5 approach), to replace the single portfolio-wide change. The trade-off is explainability; the current version favours the CFO being able to defend every number.

## Changing things

- **Different Low / Base / High values:** edit `PRESETS` in `budget_model.py`.
- **A seventh slider** (for example, capex per property):
  1. Add a field to `Drivers`.
  2. Apply it in `budget()`.
  3. Add it to `DRIVERS` and `LABELS` so the bridge picks it up.
  4. Add an `st.slider(..., key="...")` in the sidebar and pass it into `Drivers(...)`.
- **Real data:** run notebook steps 4b and 4c, then run the app locally and upload `baseline.csv`, `forecast.csv` and your `assumptions.csv` under Data.
