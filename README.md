# FY2027 budget scenarios (Streamlit app)

An interactive top-down budget for a fictional real estate firm, **Juniper Ridge Partners**. Every name and number in
`data/` is invented. The app starts from trailing-12-month actuals produced by the BudgetPipeline consolidation
notebook, projected to an FY2027 momentum baseline by the pipeline's forecaster (notebook step 4c). Six drivers then move the FY2027 budget:

- occupancy
- rent growth
- opex inflation
- interest rates
- raise pace
- deployment

## What is in this folder

| File | What it is |
|---|---|
| `app.py` | The screen: sliders, KPI tiles, the bridge, Low/Base/High, funds and properties, data quality, assumptions |
| `budget_model.py` | The math: plain Python with no Streamlit, so it can be read and tested |
| `data/baseline.csv` | TTM actuals by entity, budget line and month, with intercompany rows tagged (exported by the pipeline) |
| `data/forecast.csv` | FY2027 momentum baseline (Low / Base / High) by entity, budget line and month, from notebook step 4c. The drivers start from it |
| `data/forecast_board.csv`, `forecast_summary.csv` | The forecast backtest leaderboard and the by-property summary, shown on the Baseline forecast tab |
| `data/assumptions.csv` | Per-property occupancy, gross asset value, debt and floating-rate share (editable in the app) |
| `data/checks.csv`, `findings.csv`, `meta.json` | The pipeline's validation checks and accounting findings, shown on the Data quality tab |
| `test_budget_model.py`, `test_app.py` | 21 tests: the bridge adds up and intercompany cancels on both starting points, the forecast is the starting point, rates and deployment arithmetic, and the app runs |
| `requirements.txt` | The packages the app needs |
| `.streamlit/config.toml` | Theme colour |

## Run it on your computer

1. Install Python 3.11 or later from python.org.
2. Open a terminal in this folder and install the packages:

   ```
   pip install -r requirements.txt
   ```

3. Start the app:

   ```
   streamlit run app.py
   ```

   Your browser opens `http://localhost:8501`. Press Ctrl+C in the terminal to stop it.

4. (Optional) Run the tests:

   ```
   pip install pytest
   pytest -q
   ```

## Put it on the web (Streamlit Community Cloud, free)

Only the anonymized demo data goes online. Real company data is used only on your own computer.

1. **Create a GitHub account** at github.com (free), if you don't have one.
2. **Create a new repository**: click + (top right), then New repository. Name it, e.g., `fy2027-budget-scenarios`; Private is fine. Click Create repository.
3. **Upload the files**: on the new repository page, click "uploading an existing file". Drag in everything in this folder, including the `data` and `.streamlit` folders, then click Commit changes.
4. **Deploy**:
   - Go to share.streamlit.io and sign in with GitHub.
   - Choose Create app, then "Deploy a public app from GitHub".
   - Pick the repository, branch `main`, and main file `app.py`, then click Deploy.
   - The first build takes 2-3 minutes. You get a link like `https://fy2027-budget-scenarios.streamlit.app`.
5. **Update it later**: upload a changed file to the repository. The app redeploys by itself.

## Use it with real data (on your computer only)

1. In the consolidation notebook, step 4b writes `app_data.zip` from the real run.
2. Run the app locally. Under Data in the sidebar, upload that `baseline.csv`, `forecast.csv` and your own `assumptions.csv`. The SCODEs must match.
3. Nothing is sent anywhere: a local Streamlit app runs entirely on your computer.

Property-level figures are unaudited; the funds are audited annually. Every output needs human review before it is used.
