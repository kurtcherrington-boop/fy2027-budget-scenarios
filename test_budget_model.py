"""Tests for the FY2027 driver model: the arithmetic the app shows must hold for any slider position."""
import os

import pandas as pd
import pytest

from budget_model import PRESETS, Drivers, Params, budget, bridge, by_entity, load_baseline, metrics, scenario_table

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module", params=["forecast", "ttm"])
def base(request):
    """Every test runs twice: drivers on the FY2027 momentum baseline (forecast.csv), and on the TTM actuals."""
    b = pd.read_csv(os.path.join(HERE, "data", "baseline.csv"))
    a = pd.read_csv(os.path.join(HERE, "data", "assumptions.csv"))
    f = pd.read_csv(os.path.join(HERE, "data", "forecast.csv")) if request.param == "forecast" else None
    return load_baseline(b, a, f)[0]


def test_forecast_baseline_is_the_starting_point():
    """With no drivers, consolidated FY2027 = the forecast's own Base (intercompany rows left out), and the first bridge
    step moves TTM actual to exactly that number."""
    b = pd.read_csv(os.path.join(HERE, "data", "baseline.csv"))
    a = pd.read_csv(os.path.join(HERE, "data", "assumptions.csv"))
    f = pd.read_csv(os.path.join(HERE, "data", "forecast.csv"))
    base = load_baseline(b, a, f)[0]
    fy = budget(base, ZERO)
    fc = f[f.ICPair.fillna("") == ""]
    want = fc[fc.Group.isin(["REV", "OPX"])].Base.sum()
    assert abs(metrics(fy)["NOI"] - want) < 0.05
    br = bridge(base, ZERO, metric="NOI")
    assert br.Step.iloc[1] == "Momentum baseline (forecast)"
    assert abs(br.Amount.iloc[0] + br.Amount.iloc[1] - want) < 0.05


ZERO = Drivers(occupancy_pp=0, rent_growth=0, opex_inflation=0, rate_bp=0, raise_musd=0, deploy_pct=0)


def test_no_drivers_means_run_rate(base):
    m0, m1 = metrics(budget(base, ZERO), "TTM"), metrics(budget(base, ZERO))
    for k in ("Revenue", "Opex", "NOI", "Net income"):
        assert abs(m0[k] - m1[k]) < 0.01


def test_intercompany_cancels_in_consolidation(base):
    for d in PRESETS.values():
        fy = budget(base, d)
        ic = fy[fy.IsIC & ~fy.ICPair.isin(["IC-03"])]                 # pairs (IC-03 is the one-sided equity elimination)
        assert abs(ic.FY27.sum()) < 0.01


def test_bridge_adds_up(base):
    for metric in ("NOI", "Net income", "Fee income"):
        for d in PRESETS.values():
            br = bridge(base, d, metric=metric)
            steps = br[br.Kind == "step"].Amount.sum()
            assert abs(br.Amount.iloc[0] + steps - br.Amount.iloc[-1]) < 0.01
            assert abs(br.Amount.iloc[-1] - metrics(budget(base, d))[metric]) < 0.01


def test_rent_growth_only_moves_core_revenue(base):
    d = Drivers(occupancy_pp=0, rent_growth=0.10, opex_inflation=0, rate_bp=0, raise_musd=0, deploy_pct=0)
    fy = budget(base, d)
    core = fy[~fy.IsIC & (fy.LineID == "REV-100")]
    assert abs(core.FY27.sum() - 1.10 * core.TTM.sum()) < 0.01


def test_rates_reprice_floating_debt_only(base):
    d = Drivers(occupancy_pp=0, rent_growth=0, opex_inflation=0, rate_bp=100, raise_musd=0, deploy_pct=0)
    a = base.drop_duplicates("SCODE")
    expected = -(a.DebtBalance.fillna(0) * a.FloatingShare.fillna(0)).sum() * 0.01
    assert abs(metrics(budget(base, d))["Net income"] - metrics(budget(base, ZERO))["Net income"] - expected) < 0.01


def test_raise_and_deployment_arithmetic(base):
    p = Params()
    d = Drivers(occupancy_pp=0, rent_growth=0, opex_inflation=0, rate_bp=0, raise_musd=20, deploy_pct=0.5)
    fy = budget(base, d, p)
    price = 20e6 * 0.5 / (1 - p.new_ltv)
    assert abs(fy.attrs["price"] - price) < 0.01
    noi = metrics(fy)["NOI"] - metrics(budget(base, ZERO, p))["NOI"]
    assert abs(noi - price * p.cap_rate * p.timing) < 0.01
    fees = metrics(fy)["Fee income"] - metrics(budget(base, ZERO, p))["Fee income"]
    assert abs(fees - (20e6 * p.am_fee * p.timing + price * p.acq_fee)) < 0.01


def test_low_base_high_order(base):
    t = scenario_table(base)
    assert t.loc["NOI", "Low"] < t.loc["NOI", "Base"] < t.loc["NOI", "High"]
    assert t.loc["Fee income", "Low"] < t.loc["Fee income", "Base"] < t.loc["Fee income", "High"]


def test_entity_view_ties_to_property_noi(base):
    e = by_entity(base, PRESETS["Base"])
    fy = budget(base, PRESETS["Base"])
    a = fy[(fy.Level == "Asset") & fy.Group.isin(["REV", "OPX"])]
    assert abs(e.FY27.sum() - a.FY27.sum()) < 0.01
