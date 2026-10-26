"""Smoke tests for the Streamlit screen (Streamlit's AppTest runs app.py headless, like a browser would)."""
import os

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))


def run():
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=60)
    return at.run()


def test_app_runs_without_errors():
    at = run()
    assert not at.exception, at.exception
    assert len(at.metric) == 8                       # 5 KPI tiles + 3 on the Baseline forecast tab
    assert at.radio(key="preset").value == "Base"


def test_presets_move_the_sliders_and_the_numbers():
    at = run()
    noi_base = at.metric[1].value
    at.radio(key="preset").set_value("High").run()
    assert at.slider(key="rent_growth").value == 5.0
    assert at.metric[1].value != noi_base
    at.radio(key="preset").set_value("Low").run()
    assert at.slider(key="rate_bp").value == 100
    assert not at.exception


def test_a_slider_changes_the_bridge():
    at = run()
    at.slider(key="rate_bp").set_value(200).run()
    assert not at.exception
    assert "adjusted" in " ".join(c.value for c in at.caption)


def test_switch_to_ttm_start():
    at = run()
    noi_fc = at.metric[1].value
    at.radio(key="start_from").set_value("TTM actuals").run()
    assert not at.exception
    assert at.metric[1].value != noi_fc
