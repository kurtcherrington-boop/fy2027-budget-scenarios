"""FY2027 top-down driver model - the math behind the scenario app (no Streamlit here, so it can be read and tested).

Start: the FY2027 momentum baseline from the pipeline's BaselineForecaster (forecast.csv), or, without it, the
trailing-12-month (TTM) actuals by entity and budget line exported by the consolidation pipeline.
Then six drivers, applied in this order (the bridge reports each one's dollar effect in the same order):

  1. Occupancy (percentage points)  core and ancillary revenue move with occupied units/sites; cost of sales follows
  2. Rent growth (%)                core revenue (rent, site fees) per occupied unit
  3. Opex inflation (%)             every operating expense except cost of sales and intercompany fees
  4. Interest rates (bp)            floating-rate share of each property's debt
  5. Raise pace ($M)                new commitments to the raise vehicle -> asset management fees to the management company
  6. Deployment (%)                 share of the raise invested in FY2027 -> new properties' NOI, interest, acquisition fees

Consolidated views leave out intercompany rows (fees between funds, properties and the management company), so they
cancel by construction. The management-company view shows the same fees as revenue ("fees to the parent").
Every rule is a line of arithmetic: no fitted model, so every number can be traced back to a driver and an input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

DRIVERS = ["occupancy_pp", "rent_growth", "opex_inflation", "rate_bp", "raise_musd", "deploy_pct"]
LABELS = {"occupancy_pp": "Occupancy", "rent_growth": "Rent growth", "opex_inflation": "Opex inflation", "rate_bp": "Interest rates",
          "raise_musd": "Raise pace", "deploy_pct": "Deployment"}


@dataclass
class Drivers:
    occupancy_pp: float = 0.0      # change in occupancy, percentage points (e.g. +2.0)
    rent_growth: float = 0.03      # growth in rent per occupied unit
    opex_inflation: float = 0.035  # growth in operating costs
    rate_bp: float = 0.0           # change in floating interest rates, basis points
    raise_musd: float = 25.0       # new commitments raised in FY2027, $ millions
    deploy_pct: float = 0.60       # share of the FY2027 raise invested during FY2027


@dataclass
class Params:
    """Model constants - shown in the app under 'Model assumptions' and editable there."""
    vehicle: str = "OPF"           # fund the FY2027 raise goes into
    base_rate: float = 0.065       # current all-in interest rate on new debt
    new_ltv: float = 0.60          # loan-to-value on new acquisitions
    cap_rate: float = 0.070        # going-in cap rate on new acquisitions
    new_opex_ratio: float = 0.45   # operating expense ratio of new acquisitions (to split NOI into revenue and opex)
    am_fee: float = 0.015          # annual asset management fee on new commitments
    acq_fee: float = 0.010         # acquisition fee on purchase price
    timing: float = 0.5            # mid-year convention: raised and invested on average half-way through FY2027
    max_occupancy: float = 0.99


# Low / Base / High: Base = 50% chance each assumption is too high and 50% too low; Low = downside; High = aggressive but feasible
PRESETS = {
    "Low": Drivers(occupancy_pp=-3.0, rent_growth=0.01, opex_inflation=0.050, rate_bp=100.0, raise_musd=10.0, deploy_pct=0.40),
    "Base": Drivers(occupancy_pp=0.0, rent_growth=0.03, opex_inflation=0.035, rate_bp=0.0, raise_musd=25.0, deploy_pct=0.60),
    "High": Drivers(occupancy_pp=2.0, rent_growth=0.05, opex_inflation=0.025, rate_bp=-50.0, raise_musd=40.0, deploy_pct=0.80),
}

ENT_COLS = ["SCODE", "ShortName", "Level", "Fund", "AssetType", "Own"]


# ------------------------------------------------------------------------------------------------ baseline
def load_baseline(baseline: pd.DataFrame, assumptions: pd.DataFrame, forecast: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annual starting point by entity x line, before the drivers.

    Column Actual = TTM as booked. Column TTM = the starting point the drivers move:
      * with forecast (the pipeline's BaselineForecaster output, forecast.csv): the FY2027 momentum baseline, i.e. the
        TTM normalized for approved adjustments, partial years filled from peers, steady assets at run-rate. Low and
        High hold its 80% statistical range.
      * without: the TTM, with a partial-year property scaled to a full year by its peers' seasonality
        (same asset type, 12 months of data): factor = peers' full-year revenue / peers' revenue in the same months.
    Returns (annual baseline, notes on each annualization)."""
    b = baseline.copy()
    for c in ("ICPair", "ICRole", "Fund"):
        b[c] = b[c].fillna("").astype(str)
    b["Own"] = pd.to_numeric(b["Own"], errors="coerce").fillna(1.0)
    months = b.groupby("SCODE")["Month"].nunique()
    all_months = sorted(b["Month"].unique())
    notes = []
    rev = b[b.Group == "REV"].groupby(["SCODE", "Month"])["Amount"].sum()
    full = [sc for sc, n in months.items() if n >= len(all_months)]
    factor = {}
    for sc, n in months.items():
        lvl = b.loc[b.SCODE == sc, "Level"].iloc[0]
        if n >= len(all_months) or lvl != "Asset":
            continue
        own = sorted(b.loc[b.SCODE == sc, "Month"].unique())
        at = b.loc[b.SCODE == sc, "AssetType"].iloc[0]
        peers = [p for p in full if b.loc[b.SCODE == p, "AssetType"].iloc[0] == at and p != sc]
        tot = sum(rev.get((p, m), 0.0) for p in peers for m in all_months)
        part = sum(rev.get((p, m), 0.0) for p in peers for m in own)
        f = tot / part if part > 0 else len(all_months) / n
        factor[sc] = f
        notes.append(dict(SCODE=sc, Entity=b.loc[b.SCODE == sc, "ShortName"].iloc[0], MonthsInBaseline=n,
                          Factor=round(f, 3), Basis=f"{len(peers)} {at} peer(s): full-year revenue / revenue in {own[0]} to {own[-1]}"
                          if peers and part > 0 else "straight-line 12 / months"))
    a = b.groupby(ENT_COLS + ["LineID", "LineName", "Group", "ICPair", "ICRole"], dropna=False)["Amount"].sum().reset_index()
    a = a.rename(columns={"Amount": "Actual"})                       # TTM actual as booked
    a["TTM"] = a["Actual"] * a["SCODE"].map(factor).fillna(1.0)      # full-year run-rate (annualized where partial)
    kind = "ttm"
    if forecast is not None and len(forecast):
        f = forecast.copy()
        for c in ("ICPair", "ICRole", "Fund"):
            f[c] = f[c].fillna("").astype(str)
        f["Own"] = pd.to_numeric(f["Own"], errors="coerce").fillna(1.0)
        k = ["SCODE", "LineID", "ICPair", "ICRole"]
        fa = f.groupby(k)[["Low", "Base", "High"]].sum()
        attrs = f.drop_duplicates(k).set_index(k)[[c for c in ENT_COLS[1:] + ["LineName", "Group"]]]
        a = a.set_index(k).join(fa, how="outer")
        for c in attrs.columns:                                     # lines that exist only after normalization (e.g. a reclass)
            a[c] = a[c].combine_first(attrs[c])
        a = a.reset_index()
        a["Actual"] = a["Actual"].fillna(0.0)
        a["TTM"] = a["Base"].combine_first(a["TTM"]).fillna(0.0)
        a["Low"], a["High"] = a["Low"].combine_first(a["TTM"]), a["High"].combine_first(a["TTM"])
        a = a.drop(columns="Base")
        notes, kind = [], "forecast"
    a = a.merge(assumptions, on="SCODE", how="left")
    a.attrs["baseline"] = kind
    return a, pd.DataFrame(notes)


# ------------------------------------------------------------------------------------------------ FY2027
def budget(base: pd.DataFrame, d: Drivers, p: Params = Params()) -> pd.DataFrame:
    """FY2027 amount for every TTM row, plus rows for new acquisitions and new fees. Column FY27 (income +, cost -)."""
    x = base.copy()
    occ0 = x["BaselineOccupancy"].fillna(1.0).clip(lower=0.01)
    occ1 = (occ0 + d.occupancy_pp / 100.0).clip(lower=0.0, upper=p.max_occupancy).where(x.BaselineOccupancy.notna(), occ0)
    occ_f = (occ1 / occ0).where(x.Level == "Asset", 1.0)
    rent_f = 1.0 + d.rent_growth
    infl_f = 1.0 + d.opex_inflation
    ic = x.ICPair != ""
    f = pd.Series(1.0, index=x.index)
    f = f.mask(~ic & (x.LineID == "REV-100"), occ_f * rent_f)
    f = f.mask(~ic & x.LineID.isin(["REV-200", "OPX-105"]), occ_f)
    f = f.mask(~ic & (x.Group == "OPX") & ~x.LineID.isin(["OPX-105"]), infl_f)
    x["FY27"] = x["TTM"] * f
    # property management fees (IC-02 style: % of the property's revenue) follow each property's revenue
    rv0 = x[~ic & (x.Group == "REV")].groupby("SCODE")["TTM"].sum()
    rv1 = x[~ic & (x.Group == "REV")].groupby("SCODE")["FY27"].sum()
    rev_f = (rv1 / rv0).replace([float("inf")], 1.0).fillna(1.0)
    pm_pay = ic & (x.ICRole == "Payor") & (x.Level == "Asset")
    x.loc[pm_pay, "FY27"] = x.loc[pm_pay, "TTM"] * x.loc[pm_pay, "SCODE"].map(rev_f).fillna(1.0)
    for pair in x.loc[pm_pay, "ICPair"].unique():           # the payee books exactly what the properties pay
        pay_chg = (x.loc[pm_pay & (x.ICPair == pair), "FY27"] - x.loc[pm_pay & (x.ICPair == pair), "Actual"]).sum()
        pe = ic & (x.ICPair == pair) & (x.ICRole == "Payee")
        if pe.any():
            tot = x.loc[pe, "Actual"].sum()
            share = x.loc[pe, "Actual"] / tot if tot else 1.0 / pe.sum()
            x.loc[pe, "FY27"] = x.loc[pe, "Actual"] - pay_chg * share
    # interest rates: floating share of each property's debt reprices
    dbt = (x.LineID == "DBT-100") & x.DebtBalance.notna()
    first = dbt & ~x.duplicated(["SCODE", "LineID"])
    x.loc[first, "FY27"] = x.loc[first, "TTM"] - x.loc[first, "DebtBalance"] * x.loc[first, "FloatingShare"].fillna(0) * d.rate_bp / 10000.0
    # raise pace and deployment: new rows
    raise_usd = d.raise_musd * 1e6
    price = raise_usd * d.deploy_pct / (1.0 - p.new_ltv) if p.new_ltv < 1 else 0.0
    noi = price * p.cap_rate * p.timing
    new_rev = noi / (1.0 - p.new_opex_ratio) if p.new_opex_ratio < 1 else noi
    rows = []
    def add(sc, name, level, line, lname, grp, amt, pair="", role=""):
        rows.append(dict(SCODE=sc, ShortName=name, Level=level, Fund=p.vehicle, AssetType="New acquisitions", Own=1.0, LineID=line,
                         LineName=lname, Group=grp, ICPair=pair, ICRole=role, Actual=0.0, TTM=0.0, FY27=amt))
    nm = f"FY27 acquisitions ({p.vehicle})"
    add("NEW_ACQ", nm, "Asset", "REV-100", "Core revenue", "REV", new_rev)
    add("NEW_ACQ", nm, "Asset", "OPX-185", "Operating expenses (new acquisitions)", "OPX", -(new_rev - noi))
    add("NEW_ACQ", nm, "Asset", "DBT-100", "Interest expense", "BNOI", -price * p.new_ltv * (p.base_rate + d.rate_bp / 10000.0) * p.timing)
    am = raise_usd * p.am_fee * p.timing
    acq = price * p.acq_fee
    fund = f"{p.vehicle}_FUND"
    add(fund, f"{p.vehicle} (new commitments)", "Fund", "OPX-170", "Management fees - affiliate (IC)", "OPX", -am, "NEW-AM", "Payor")
    add("MGMT_CO", "Management company (new fees)", "ManagementCo", "REV-300", "Asset management fees on new commitments", "REV", am, "NEW-AM", "Payee")
    add(fund, f"{p.vehicle} (acquisition fees, capitalized)", "Fund", "CAP-100", "Acquisition fees (capitalized)", "BNOI", -acq, "NEW-ACQFEE", "Payor")
    add("MGMT_CO", "Management company (new fees)", "ManagementCo", "REV-300", "Acquisition fees", "REV", acq, "NEW-ACQFEE", "Payee")
    out = pd.concat([x, pd.DataFrame(rows)], ignore_index=True)
    out["IsIC"] = out["ICPair"].astype(str) != ""
    out.attrs.update(price=price, raise_usd=raise_usd)
    return out


def metrics(fy: pd.DataFrame, col: str = "FY27") -> dict:
    """Headline numbers. Consolidated = intercompany rows left out (they cancel)."""
    c = fy[~fy.IsIC] if "IsIC" in fy else fy[fy.ICPair.astype(str) == ""]
    ic = fy[fy.ICPair.astype(str) != ""]
    rev = c.loc[c.Group == "REV", col].sum()
    opx = c.loc[c.Group == "OPX", col].sum()
    fees = ic.loc[(ic.ICRole == "Payee") & (ic.Level == "ManagementCo"), col].sum()
    gav = fy.drop_duplicates("SCODE")["GrossAssetValue"].fillna(0).sum() if "GrossAssetValue" in fy else 0.0
    if col == "FY27":
        gav += fy.attrs.get("price", 0.0)        # AUM = gross asset value at 100%, plus FY2027 purchases
    return {"Revenue": rev, "Opex": opx, "NOI": rev + opx, "Net income": c[col].sum(), "Fee income": fees, "AUM": gav}


def bridge(base: pd.DataFrame, d: Drivers, p: Params = Params(), metric: str = "NOI") -> pd.DataFrame:
    """Waterfall from TTM actual to FY2027: switch the drivers on one at a time, in model order. The steps add up
    exactly to the FY2027 figure (the order decides which driver gets the interaction between drivers)."""
    zero = Drivers(occupancy_pp=0, rent_growth=0, opex_inflation=0, rate_bp=0, raise_musd=0, deploy_pct=0)
    start = metrics(budget(base, zero, p), "Actual")[metric]
    steps, cur = [dict(Step="TTM actual", Amount=start, Kind="total")], asdict(zero)
    prev = metrics(budget(base, zero, p))[metric]
    if abs(prev - start) > 0.5:                             # TTM actual -> starting point (forecast, or partial years annualized)
        label = "Momentum baseline (forecast)" if base.attrs.get("baseline") == "forecast" else "Full year of properties bought in the TTM"
        steps.append(dict(Step=label, Amount=prev - start, Kind="step"))
    for k in DRIVERS:
        cur[k] = getattr(d, k)
        v = metrics(budget(base, Drivers(**cur), p))[metric]
        steps.append(dict(Step=LABELS[k], Amount=v - prev, Kind="step"))
        prev = v
    steps.append(dict(Step="FY2027 budget", Amount=prev, Kind="total"))
    return pd.DataFrame(steps)


def scenario_table(base: pd.DataFrame, p: Params = Params(), custom: Drivers | None = None) -> pd.DataFrame:
    """Low / Base / High (and the custom slider position) side by side: drivers on top, results below."""
    cols = dict(PRESETS)
    if custom is not None:
        cols["Your scenario"] = custom
    out = {}
    for name, d in cols.items():
        m = metrics(budget(base, d, p))
        out[name] = {**{LABELS[k]: getattr(d, k) for k in DRIVERS}, **m}
    return pd.DataFrame(out)


def by_entity(base: pd.DataFrame, d: Drivers, p: Params = Params()) -> pd.DataFrame:
    """NOI per property and fund, TTM vs FY2027, at 100% and at ownership share (intercompany fees included in each
    property's NOI, as the property's own P&L shows them)."""
    fy = budget(base, d, p)
    a = fy[(fy.Level == "Asset") & fy.Group.isin(["REV", "OPX"])]
    g = a.groupby(["Fund", "SCODE", "ShortName", "AssetType", "Own"], dropna=False)[["Actual", "FY27"]].sum().reset_index()
    g["Change"] = g["FY27"] - g["Actual"]
    g["Change %"] = (g["Change"] / g["Actual"].abs()).where(g["Actual"].abs() > 0)
    g["FY27 at share"] = g["FY27"] * g["Own"]
    return g.sort_values(["Fund", "SCODE"]).reset_index(drop=True)
