"""FY2027 budget scenario app (Streamlit).

Run locally:   streamlit run app.py        (opens http://localhost:8501 in your browser)

How Streamlit works, in one paragraph: this file is an ordinary Python script. Streamlit runs it top to bottom and
turns each st.* call into something on the page (a slider, a number, a chart). When you move a slider, Streamlit
runs the WHOLE script again with the slider's new value and redraws the page. There are no "on change" handlers to
write: read the widget values, compute, draw. The comments marked STREAMLIT point out each new idea the first time
it appears.

The math lives in budget_model.py (plain Python, unit-tested). This file only gathers inputs and draws results.
"""
import io
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from budget_model import DRIVERS, LABELS, PRESETS, Drivers, Params, bridge, budget, by_entity, load_baseline, metrics, scenario_table

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
GOOD, BAD, NEUTRAL, PRIOR = "#2f6fc4", "#c2562f", "#8a8f98", "#8a8f98"   # steel blue = favourable, rust = unfavourable

# STREAMLIT: set_page_config must be the first st.* call. layout="wide" uses the full browser width.
st.set_page_config(page_title="FY2027 Budget Scenarios", layout="wide")


# ------------------------------------------------------------------------------------------------ formatting
def money(x, short=True):
    """$1.25M / $845K / ($0.15M): negatives in parentheses (BIWS)."""
    if x is None or pd.isna(x):
        return ""
    a = abs(x)
    s = f"${a / 1e6:,.2f}M" if (short and a >= 1e6) else (f"${a / 1e3:,.0f}K" if (short and a >= 1e3) else f"${a:,.0f}")
    return f"({s})" if x < 0 else s


def md(text):
    """Streamlit markdown reads $...$ as a math formula - escape dollar signs in captions and text."""
    return text.replace("$", "\\$")


def num(x):
    return "" if pd.isna(x) else (f"({abs(x):,.0f})" if x < 0 else f"{x:,.0f}")


# ------------------------------------------------------------------------------------------------ data
# STREAMLIT: @st.cache_data remembers a function's result for the same inputs, so the CSVs are read once - not on
# every slider move. (Remember: the whole script re-runs on every change; caching keeps that fast.)
@st.cache_data
def read_csv(content: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(content))


def file_bytes(name):
    with open(os.path.join(DATA, name), "rb") as fh:
        return fh.read()


# STREAMLIT: st.sidebar.* puts a widget in the left-hand panel; with st.sidebar: does the same for a block of code.
with st.sidebar:
    st.header("FY2027 drivers")

    # STREAMLIT: st.session_state is a dictionary that survives re-runs. Every widget with key="x" stores its value
    # in st.session_state["x"]. The preset buttons below write new values into session_state, which moves the sliders.
    def apply_preset():
        d = PRESETS[st.session_state.preset]
        st.session_state.occupancy_pp = float(d.occupancy_pp)
        st.session_state.rent_growth = round(d.rent_growth * 100, 2)
        st.session_state.opex_inflation = round(d.opex_inflation * 100, 2)
        st.session_state.rate_bp = int(d.rate_bp)
        st.session_state.raise_musd = int(d.raise_musd)
        st.session_state.deploy_pct = int(round(d.deploy_pct * 100))

    if "occupancy_pp" not in st.session_state:          # first visit: start at Base
        st.session_state.preset = "Base"
        apply_preset()

    # STREAMLIT: on_change runs a function BEFORE the re-run, so the sliders already show the preset when the page redraws.
    st.radio("Start from a scenario", ["Low", "Base", "High"], key="preset", horizontal=True, on_change=apply_preset,
             help="Base = 50/50 chance each assumption is too high or too low. Low = downside. High = aggressive but feasible.")

    st.subheader("Properties")
    # STREAMLIT: st.slider(label, min, max, step=..., key=...) returns the current value; the key ties it to session_state.
    st.slider("Occupancy change (percentage points)", -10.0, 10.0, step=0.5, key="occupancy_pp",
              help="Added to each property's baseline occupancy (assumptions.csv). Core and ancillary revenue move with occupied units.")
    st.slider("Rent growth (%)", -5.0, 10.0, step=0.25, key="rent_growth", help="Change in rent / site rate per occupied unit.")
    st.slider("Opex inflation (%)", 0.0, 10.0, step=0.25, key="opex_inflation",
              help="Applied to every operating expense except cost of sales (follows volume) and intercompany fees (follow revenue or AUM).")
    st.slider("Interest rate change (bp)", -200, 300, step=25, key="rate_bp", help="Reprices the floating-rate share of each property's debt.")
    st.subheader("Firm")
    st.slider("Raise pace: new commitments ($M)", 0, 100, step=5, key="raise_musd",
              help="New capital raised in FY2027. Earns asset management fees for the management company.")
    st.slider("Deployment: share of the raise invested in FY2027 (%)", 0, 100, step=5, key="deploy_pct",
              help="Invested capital buys properties at the cap rate and LTV under Model assumptions.")

    d = Drivers(occupancy_pp=st.session_state.occupancy_pp, rent_growth=st.session_state.rent_growth / 100,
                opex_inflation=st.session_state.opex_inflation / 100, rate_bp=st.session_state.rate_bp,
                raise_musd=st.session_state.raise_musd, deploy_pct=st.session_state.deploy_pct / 100)
    same = PRESETS[st.session_state.preset] == d
    st.caption(f"Showing: **{st.session_state.preset}**" + ("" if same else " (adjusted)"))

    # STREAMLIT: st.expander is a collapsible box - good for settings most people leave alone.
    with st.expander("Data"):
        # STREAMLIT: st.file_uploader lets the viewer drop in a file; it returns None until they do. Here it swaps
        # the demo baseline for a real pipeline export (run locally, never on a public deployment).
        up_b = st.file_uploader("baseline.csv from the pipeline", type="csv")
        up_f = st.file_uploader("forecast.csv from the pipeline (step 4c)", type="csv")
        up_a = st.file_uploader("assumptions.csv", type="csv")

    baseline_raw = read_csv(up_b.getvalue() if up_b else file_bytes("baseline.csv"))
    assumptions_raw = read_csv(up_a.getvalue() if up_a else file_bytes("assumptions.csv"))
    has_fc_file = os.path.exists(os.path.join(DATA, "forecast.csv"))
    forecast_raw = read_csv(up_f.getvalue()) if up_f else (read_csv(file_bytes("forecast.csv")) if has_fc_file and not up_b else None)
    start_from = st.radio("Drivers start from", ["FY2027 momentum baseline", "TTM actuals"], index=0 if forecast_raw is not None else 1, key="start_from",
                          disabled=forecast_raw is None, horizontal=False,
                          help="Momentum baseline = the statistical forecast (Baseline forecast tab): what FY2027 looks like if TTM operations "
                               "repeat, with partial years filled from peers. TTM actuals = as booked, partial years scaled up.")

    with st.expander("Model assumptions"):
        p0 = Params()
        funds = sorted(f for f in baseline_raw.loc[baseline_raw.Level == "Fund", "Fund"].dropna().unique())
        vehicle = st.selectbox("Raise vehicle (fund)", funds, index=funds.index(p0.vehicle) if p0.vehicle in funds else 0)
        # STREAMLIT: st.number_input is a typed box with +/- buttons.
        base_rate = st.number_input("Interest rate on new debt (%)", 0.0, 15.0, p0.base_rate * 100, 0.25) / 100
        ltv = st.number_input("LTV on new acquisitions (%)", 0.0, 90.0, p0.new_ltv * 100, 5.0) / 100
        cap = st.number_input("Going-in cap rate (%)", 3.0, 12.0, p0.cap_rate * 100, 0.25) / 100
        am_fee = st.number_input("Asset management fee on commitments (%)", 0.0, 3.0, p0.am_fee * 100, 0.25) / 100
        acq_fee = st.number_input("Acquisition fee on price (%)", 0.0, 3.0, p0.acq_fee * 100, 0.25) / 100
        timing = st.number_input("Share of the year earned (mid-year = 0.5)", 0.0, 1.0, p0.timing, 0.05)
    p = Params(vehicle=vehicle, base_rate=base_rate, new_ltv=ltv, cap_rate=cap, am_fee=am_fee, acq_fee=acq_fee, timing=timing)

meta = json.loads(file_bytes("meta.json")) if not up_b else {}
fc_board = read_csv(file_bytes("forecast_board.csv")) if forecast_raw is not None and not up_f and os.path.exists(os.path.join(DATA, "forecast_board.csv")) else pd.DataFrame()
fc_sum = read_csv(file_bytes("forecast_summary.csv")) if forecast_raw is not None and not up_f and os.path.exists(os.path.join(DATA, "forecast_summary.csv")) else pd.DataFrame()
checks = read_csv(file_bytes("checks.csv")) if not up_b else pd.DataFrame()
findings = read_csv(file_bytes("findings.csv")) if not up_b else pd.DataFrame()

# ------------------------------------------------------------------------------------------------ header
st.title("FY2027 budget scenarios")
st.caption(f"Baseline: trailing-12-month actuals {meta.get('window', '(uploaded file)')} from BudgetPipeline {meta.get('version', '')}"
           + (", projected to FY2027 by the pipeline's baseline forecaster. " if start_from == "FY2027 momentum baseline" else ". ") +
           "Move the drivers on the left; every number on the page recalculates. " + meta.get("note", ""))
if meta.get("provisional"):
    # STREAMLIT: st.warning / st.info / st.error draw coloured message boxes.
    st.warning(f"PROVISIONAL baseline: {len(meta.get('open_checks', []))} validation checks are open in the consolidation "
               f"({', '.join(meta.get('open_checks', [])[:6])}). See the Data quality tab before relying on these numbers.")

# STREAMLIT: st.container() reserves a spot on the page now and lets you fill it later in the script. The KPI tiles
# need the computed numbers, but must sit ABOVE the tabs, so their spot is reserved here.
kpi_area = st.container()

# STREAMLIT: tabs. st.tabs returns one container per label; "with tab:" puts content inside it.
tab_bridge, tab_fc, tab_scen, tab_funds, tab_dq, tab_how = st.tabs(["Bridge", "Baseline forecast", "Low / Base / High", "Funds & properties",
                                                                     "Data quality", "Assumptions & method"])

# The assumptions table lives in the last tab but is needed for every number, so fill that tab first.
# STREAMLIT: tabs are containers - you can write into them in any order; the page still shows them in tab order.
with tab_how:
    st.subheader("Property assumptions")
    st.caption("Edit a cell and the whole page recalculates. Occupancy is the TTM average; debt and floating share drive the rate slider; "
               "gross asset value is AUM at 100%.")
    # STREAMLIT: st.data_editor shows an editable table and RETURNS the edited copy - used straight away below.
    names = baseline_raw.drop_duplicates("SCODE").set_index("SCODE")["ShortName"]
    a_view = assumptions_raw.copy()
    a_view.insert(1, "Property", a_view.SCODE.map(names).fillna(""))
    a_view["Note"] = a_view["Note"].fillna("") if "Note" in a_view else ""
    assumptions = st.data_editor(a_view, key="assumptions_editor", hide_index=True, width="stretch", disabled=["SCODE", "Property"],
                                 column_config={
        "BaselineOccupancy": st.column_config.NumberColumn(format="percent", min_value=0.0, max_value=1.0, step=0.01),
        "GrossAssetValue": st.column_config.NumberColumn(format="dollar"),
        "DebtBalance": st.column_config.NumberColumn(format="dollar"),
        "FloatingShare": st.column_config.NumberColumn(format="percent", min_value=0.0, max_value=1.0, step=0.05),
        "Note": st.column_config.TextColumn(width="large")}).drop(columns="Property")
base, notes = load_baseline(baseline_raw, assumptions, forecast_raw if start_from == "FY2027 momentum baseline" else None)
fy = budget(base, d, p)
m_now, m_ttm = metrics(fy), metrics(fy, "Actual")

# ------------------------------------------------------------------------------------------------ KPI tiles
# STREAMLIT: st.columns(n) splits the page into side-by-side columns; st.metric draws a number with a change below it.
cols = kpi_area.columns(5)
tiles = [("Revenue", "Revenue", "Consolidated, intercompany eliminated"), ("NOI", "NOI", "Revenue less operating expenses"),
         ("Net income", "Net income", "After interest, capex as booked, depreciation"),
         ("Fees to mgmt company", "Fee income", "Fund and property fees earned by the management company (they cancel in the consolidated figures)"),
         ("AUM (gross asset value)", "AUM", "At 100%, incl. debt, plus FY2027 purchases")]
for c, (label, key, helptext) in zip(cols, tiles):
    chg = m_now[key] - m_ttm[key]
    # the delta's leading + / - sets its arrow and colour, so it carries a sign rather than parentheses
    c.metric(label, money(m_now[key]), (("+" if chg >= 0 else "-") + money(abs(chg)) + " vs TTM") if abs(chg) >= 1 else None,
             help=helptext, border=True)

# ------------------------------------------------------------------------------------------------ bridge
with tab_bridge:
    left, right = st.columns([3, 1])
    with right:
        # STREAMLIT: st.selectbox is a drop-down.
        metric = st.selectbox("Bridge for", ["NOI", "Net income", "Fee income"],
                              format_func=lambda k: {"Fee income": "Fees to the management company"}.get(k, k))
        st.caption("Drivers switch on one at a time in the order shown, so the bars add up exactly to the FY2027 figure. "
                   "Raise pace moves fees only: fees between funds and the management company cancel in the consolidated NOI.")
    br = bridge(base, d, p, metric)
    with left:
        br = br.assign(Step=br.Step.replace({"Full year of properties bought in the TTM": "Full year of TTM purchases",
                                             "Momentum baseline (forecast)": "Momentum baseline"}))
        def two_lines(x):                                    # balanced two-line labels instead of slanted ones
            w = x.split(" ")
            if len(x) <= 12 or len(w) == 1:
                return x
            cut = min(range(1, len(w)), key=lambda i: abs(len(" ".join(w[:i])) - len(" ".join(w[i:]))))
            return " ".join(w[:cut]) + "<br>" + " ".join(w[cut:])
        wrap = [two_lines(x) for x in br.Step]
        measure = ["absolute" if k == "total" else "relative" for k in br.Kind]
        colors = [NEUTRAL if k == "total" else (GOOD if a >= 0 else BAD) for k, a in zip(br.Kind, br.Amount)]
        # Plotly's Waterfall draws running totals; each bar's colour shows whether the driver helps (blue) or hurts (rust).
        fig = go.Figure(go.Waterfall(
            x=wrap, y=br.Amount, measure=measure, text=[money(v) if abs(v) >= 1 else "" for v in br.Amount], textposition="outside",
            connector=dict(line=dict(color="rgba(128,128,128,0.4)", width=1)),
            increasing=dict(marker=dict(color=GOOD)), decreasing=dict(marker=dict(color=BAD)), totals=dict(marker=dict(color=NEUTRAL)),
            customdata=[money(v, short=False) for v in br.Amount], hovertemplate="%{x}: %{customdata}<extra></extra>"))
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                          yaxis=dict(title=None, tickprefix="$", tickformat="~s", gridcolor="rgba(128,128,128,0.15)"),
                          xaxis=dict(title=None, tickangle=0), title=dict(text=f"{'Fees to the management company' if metric == 'Fee income' else metric}: TTM actual to FY2027", x=0))
        # STREAMLIT: st.plotly_chart shows a Plotly figure; theme="streamlit" matches the app's light/dark theme.
        st.plotly_chart(fig, width="stretch", theme="streamlit")
    # STREAMLIT: an expander keeps the table one click away - the accessible, exact-number view of the chart.
    with st.expander("Show the bridge as a table"):
        st.dataframe(br[["Step", "Amount"]], hide_index=True, column_config={
            "Step": st.column_config.TextColumn(width="medium"), "Amount": st.column_config.NumberColumn(format="accounting")})
    if base.attrs.get("baseline") == "forecast":
        st.caption("Momentum baseline (forecast): the TTM normalized for the pipeline's adjustments, months a property did not operate "
                   "under our ownership borrowed from its peers, and steady assets at their run-rate. See the Baseline forecast tab.")
    if len(notes):
        st.caption("Full-year effect: " + "; ".join(f"{r.Entity} has {r.MonthsInBaseline} months in the TTM, scaled x{r.Factor} ({r.Basis})"
                                                   for r in notes.itertuples(index=False)))

# ------------------------------------------------------------------------------------------------ baseline forecast
with tab_fc:
    if forecast_raw is None:
        st.info("The baseline forecast comes with the pipeline's step 4c export (forecast.csv). Not loaded.")
    else:
        st.subheader("FY2027 momentum baseline: what next year looks like if TTM operations repeat")
        st.caption("Statistical baseline before any driver: each line repeats its own month where the property has one; months it has "
                   "not operated under our ownership are borrowed from peers in the same family (seasonal or steady), using the approach "
                   "that won the backtest. The band is the 80% range. Budget = baseline + drivers + owned initiatives.")
        fa = forecast_raw[forecast_raw.Level == "Asset"].copy()
        ba = baseline_raw[baseline_raw.Level == "Asset"].copy()
        names_a = fa.drop_duplicates("SCODE").set_index("SCODE")["ShortName"]
        c1, c2 = st.columns([2, 1])
        with c1:
            sel = st.selectbox("Property", ["All properties"] + list(names_a.sort_values().index), format_func=lambda k: names_a.get(k, k))
        with c2:
            meas = st.radio("Measure", ["Revenue", "NOI"], horizontal=True, key="fc_measure")
        if sel != "All properties":
            fa, ba = fa[fa.SCODE == sel], ba[ba.SCODE == sel]
        grp = ["REV"] if meas == "Revenue" else ["REV", "OPX"]
        fm = fa[fa.Group.isin(grp)].groupby("Month")[["Low", "Base", "High"]].sum()
        ba["m"] = pd.to_datetime(ba.Month + "-01").dt.month
        am = ba[ba.Group.isin(grp)].groupby("m")["Amount"].sum()
        mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        act = [am.get(i + 1, None) for i in range(12)]
        fig3 = go.Figure()
        fig3.add_scatter(x=mon, y=fm.High.values, mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False)
        fig3.add_scatter(x=mon, y=fm.Low.values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(47,111,196,0.18)",
                         name="80% range", customdata=[money(h) for h in fm.High.values],
                         hovertemplate="%{x}: " + "%{y:$,.0f} to %{customdata}<extra>80% range</extra>")
        fig3.add_scatter(x=mon, y=fm.Base.values, mode="lines+markers", line=dict(color=GOOD, width=2), marker=dict(size=8), name="FY2027 base",
                         hovertemplate="%{x} FY2027 base: %{y:$,.0f}<extra></extra>")
        fig3.add_scatter(x=mon, y=act, mode="markers", marker=dict(color=PRIOR, size=8, symbol="circle-open", line=dict(width=2)),
                         name="TTM actual (same month)", hovertemplate="%{x} TTM actual: %{y:$,.0f}<extra></extra>")
        fig3.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
                           title=dict(text=f"{meas} by month: {names_a.get(sel, sel)}", x=0),
                           yaxis=dict(tickprefix="$", tickformat="~s", gridcolor="rgba(128,128,128,0.15)"),
                           legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
        st.plotly_chart(fig3, width="stretch", theme="streamlit")
        k1, k2, k3 = st.columns(3)
        k1.metric(f"FY2027 {meas} (base)", money(fm.Base.sum()), border=True)
        short = lambda x: f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else money(x)
        k2.metric("80% range", md(f"{short(fm.Low.sum())} – {short(fm.High.sum())}"), border=True)
        k3.metric(f"TTM actual {meas}", money(am.sum()), help="As booked; a property bought mid-year shows only its owned months.", border=True)
        if len(fc_sum):
            st.subheader("By property")
            v = fc_sum[fc_sum.SCODE != "TOTAL"][["Property", "Family", "Months observed", "Revenue TTM", "Revenue Base", "NOI TTM", "NOI Low",
                                                  "NOI Base", "NOI High", "Borrowed share of revenue"]].copy()
            v = v.rename(columns={"Months observed": "Months seen", "Borrowed share of revenue": "Borrowed"})
            moneycols = ["Revenue TTM", "Revenue Base", "NOI TTM", "NOI Low", "NOI Base", "NOI High"]
            # STREAMLIT: st.dataframe also accepts a pandas Styler, for number formats column_config doesn't offer
            st.dataframe(v.style.format({**{c: num for c in moneycols}, "Months seen": "{:.0f}", "Borrowed": "{:.0%}"}),
                         hide_index=True, width="stretch")
            st.caption("TTM columns are as booked (normalized): a property bought mid-year shows only its owned months. NOI is property-level, "
                       "after management fees and before debt service.")
        if len(fc_board):
            st.subheader("Which approach fills the gaps? The backtest")
            st.caption("Hide months of a complete property (keep a 3- or 5-month window, as if just bought), predict the rest, score against "
                       "actuals. Written rule: bias within 10%, lowest monthly error (WAPE), a simpler approach within 0.5 pp wins.")
            cols_b = st.columns(2)
            for col, (fam, g) in zip(cols_b, fc_board.groupby("Family")):
                g = g.sort_values("WAPE (monthly)", ascending=False)
                figb = go.Figure(go.Bar(x=g["WAPE (monthly)"] * 100, y=g.Approach, orientation="h",
                                        marker_color=[GOOD if x == "SELECTED" else NEUTRAL for x in g.Selected.fillna("")],
                                        text=[f"{x * 100:.1f}%" for x in g["WAPE (monthly)"]], textposition="outside", cliponaxis=False,
                                        hovertemplate="%{y}: %{x:.1f}% monthly error<extra></extra>"))
                figb.update_layout(height=320, margin=dict(l=10, r=40, t=40, b=10), title=dict(text=f"{fam} assets: backtest error (lower is better)", x=0),
                                   xaxis=dict(ticksuffix="%", gridcolor="rgba(128,128,128,0.15)", range=[0, g["WAPE (monthly)"].max() * 118]),
                                   yaxis=dict(title=None))
                col.plotly_chart(figb, width="stretch", theme="streamlit")
            with st.expander("Show the leaderboard as a table"):
                st.dataframe(fc_board, hide_index=True, width="stretch", column_config={
                    c: st.column_config.NumberColumn(format="percent") for c in ("WAPE (monthly)", "Bias", "Season-total error")})

# ------------------------------------------------------------------------------------------------ scenarios
with tab_scen:
    st.subheader("Low, Base and High against your scenario")
    tab = scenario_table(base, p, d)
    pct = {"Rent growth", "Opex inflation", "Deployment"}
    def fmt_row(name, v):
        if name in pct:
            return f"{v * 100:.2f}%"
        if name == "Occupancy":
            return f"{v:+.1f} pts"
        if name == "Interest rates":
            return f"{v:+.0f} bp"
        if name == "Raise pace":
            return f"${v:,.0f}M"
        return money(v, short=False)
    show = pd.DataFrame({c: [fmt_row(i, tab.loc[i, c]) for i in tab.index] for c in tab.columns}, index=tab.index)
    st.dataframe(show, width="stretch", height=35 * (len(show) + 1) + 3)
    nb = tab.loc["NOI"]
    st.caption(md(f"NOI range Low to High: {money(nb['Low'])} to {money(nb['High'])}; your scenario {money(nb['Your scenario'])}. "
                  "Items under about 50% probability belong on the risks & opportunities list, not in Base."))

# ------------------------------------------------------------------------------------------------ funds & properties
with tab_funds:
    ent = by_entity(base, d, p)
    # STREAMLIT: st.toggle is an on/off switch.
    share = st.toggle("Show at ownership share", value=False, help="Facts are stored at 100% of each property; the share view applies Own %.")
    e2 = ent.copy()
    if share:
        e2["Actual"], e2["FY27"] = e2["Actual"] * e2["Own"], e2["FY27"] * e2["Own"]
    fund_names = baseline_raw[baseline_raw.Level == "Fund"].drop_duplicates("Fund").set_index("Fund")["ShortName"].to_dict()
    fsum = e2.groupby("Fund")[["Actual", "FY27"]].sum().reset_index()
    fsum["Fund"] = fsum.Fund.map(lambda f: f"{fund_names.get(f, f)} ({f})")
    fig2 = go.Figure()
    fig2.add_bar(x=fsum.Fund, y=fsum.Actual, name="TTM actual", marker_color=PRIOR, text=[money(v) for v in fsum.Actual], textposition="outside",
                 hovertemplate="%{x} TTM actual: %{text}<extra></extra>")
    fig2.add_bar(x=fsum.Fund, y=fsum.FY27, name="FY2027 budget", marker_color=GOOD, text=[money(v) for v in fsum.FY27], textposition="outside",
                 hovertemplate="%{x} FY2027: %{text}<extra></extra>")
    fig2.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, height=380, margin=dict(l=10, r=10, t=40, b=10),
                       title=dict(text="Property NOI by fund" + (" (at share)" if share else " (100%)"), x=0),
                       yaxis=dict(tickprefix="$", tickformat="~s", gridcolor="rgba(128,128,128,0.15)"),
                       legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    st.plotly_chart(fig2, width="stretch", theme="streamlit")
    st.subheader("Properties")
    view = e2[["Fund", "ShortName", "AssetType", "Own", "Actual", "FY27", "Change", "Change %"]].round(
        {"Actual": 0, "FY27": 0, "Change": 0}).rename(
        columns={"ShortName": "Property", "AssetType": "Type", "Actual": "TTM NOI", "FY27": "FY2027 NOI"})
    # STREAMLIT: column_config controls how each column of st.dataframe is displayed (format, width, help text).
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "Own": st.column_config.NumberColumn(format="percent"),
        "TTM NOI": st.column_config.NumberColumn(format="accounting"),
        "FY2027 NOI": st.column_config.NumberColumn(format="accounting"),
        "Change": st.column_config.NumberColumn(format="accounting"),
        "Change %": st.column_config.NumberColumn(format="percent")})
    # STREAMLIT: st.download_button hands the viewer a file - here the FY2027 budget by entity and line.
    out = fy.groupby(["Fund", "SCODE", "ShortName", "Level", "LineID", "LineName", "Group", "ICPair"], dropna=False)[["Actual", "TTM", "FY27"]].sum().reset_index()
    st.download_button("Download the FY2027 budget (CSV)", out.to_csv(index=False).encode(), "FY2027_budget_scenario.csv", "text/csv")

# ------------------------------------------------------------------------------------------------ data quality
with tab_dq:
    if not len(checks):
        st.info("Data quality results come with the pipeline's export (checks.csv, findings.csv). Not available for an uploaded baseline.")
    else:
        st.subheader("Consolidation checks")
        ok = (checks.Status == "OK").sum()
        st.write(f"{ok} of {len(checks)} pipeline checks pass. Open checks keep the baseline PROVISIONAL; each one is listed with its difference.")
        st.dataframe(checks[["CheckID", "Check", "Status", "Detail"]].fillna(""), hide_index=True, width="stretch",
                     height=35 * (len(checks) + 1) + 3)
        if len(findings):
            st.subheader("Accounting findings the CFO rules on")
            ct = pd.crosstab(findings.DetectorID + " " + findings.Detector, findings.Route).rename_axis(index="Detector", columns=None)
            st.dataframe(ct, width="stretch")
            rule = findings[findings.Route.str.endswith("rules")].sort_values("Amount", ascending=False)
            st.markdown(f"**{len(rule)} items above the approval threshold** (over \\$5,000 or 5% of the line):")
            st.dataframe(rule[["Entity", "Detector", "AccountName", "Periods", "Amount", "Evidence"]].fillna(""), hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="accounting"),
                                        "Evidence": st.column_config.TextColumn(width="large")})
        st.caption("A budget built on unresolved findings inherits them: rule on the adjustments in the consolidation workbook, "
                   "re-run the pipeline, and the baseline here updates.")

# ------------------------------------------------------------------------------------------------ assumptions & method
with tab_how:
    st.subheader("How the FY2027 numbers are built")
    st.markdown("""
1. **Start** from the FY2027 momentum baseline (Baseline forecast tab): the trailing-12-month actuals the consolidation pipeline
   produced (cleaned, mapped, intercompany tagged), normalized for its adjustments, with months a property did not operate filled
   from its peers and steady assets at run-rate. (Switch to "TTM actuals" in the sidebar to start from the books as booked.)
2. **Occupancy**: core and ancillary revenue scale with (baseline occupancy + change) / baseline occupancy; cost of sales follows.
3. **Rent growth**: core revenue x (1 + growth).
4. **Opex inflation**: operating expenses x (1 + inflation), except cost of sales and intercompany fees.
5. **Interest rates**: debt x floating share x rate change.
6. **Raise pace**: new commitments x asset management fee x share of the year -> management-company revenue (cancels in consolidation).
7. **Deployment**: price = raise x deployed % / (1 - LTV); NOI = price x cap rate x share of the year; interest on the new loan;
   acquisition fee = price x fee rate (capitalized by the fund, revenue to the management company).

Every step is arithmetic on named inputs - no fitted model - so any number can be traced to a driver and an assumption.
Intercompany fees are kept out of consolidated revenue, expenses and NOI and shown on their own as fees to the management company.
""")
