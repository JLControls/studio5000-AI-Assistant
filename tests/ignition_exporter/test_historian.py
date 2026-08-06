"""Tests for signal-type historian recommendations (tool #4)."""

from ignition_exporter.historian_rules import suggest_historian_config


def test_continuous_pv_enables_history_with_time_deadband():
    for sig in ("level", "pressure", "temperature", "flow", "speed"):
        cfg = suggest_historian_config(signal_type=sig)
        assert cfg["history_enabled"] is True
        assert 0 < cfg["history_time_deadband"] <= 30


def test_discrete_alarm_logs_on_change():
    cfg = suggest_historian_config(signal_type="alarm")
    assert cfg["history_enabled"] is True
    assert cfg["history_time_deadband"] == 0


def test_static_spec_disables_history():
    cfg = suggest_historian_config(signal_type="static")
    assert cfg["history_enabled"] is False


def test_classification_from_description():
    cfg = suggest_historian_config(tag_name="AIn_HWT_Level", description="Tank Level Height")
    assert cfg["signal_type"] == "level"
    assert cfg["history_enabled"] is True


def test_value_deadband_is_advisory_only():
    cfg = suggest_historian_config(signal_type="pressure", eng_low=0, eng_high=150)
    # advisory absolute value from percent-of-span, plus an explicit "not written" note
    assert cfg["recommended_value_deadband"] == 0.75  # 0.5% of 150
    assert "advisory" in cfg["value_deadband_note"].lower()
    assert "not written" in cfg["value_deadband_note"].lower()
