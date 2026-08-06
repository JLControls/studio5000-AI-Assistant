"""Unit tests for sanitize rules and Ignition JSON serialization parity."""

import json

from ignition_exporter.ignition_tag_builder import IgnitionTagBuilder, sanitize_name


def test_sanitize_char_rules():
    assert sanitize_name("Level & Volume") == "Level and Volume"
    assert sanitize_name("Flow/Rate") == "Flow Rate"
    assert sanitize_name("Temp (degF):") == "Temp degF"
    assert sanitize_name('Angle 90° "raw"') == "Angle 90 raw"
    assert sanitize_name("A   B\tC") == "A B C"
    assert sanitize_name("Pump*1?") == "Pump1"


def test_serialize_escapes_equals_and_amp_and_sorts_keys():
    builder = IgnitionTagBuilder("DeviceX")
    tag = {"opcItemPath": "ns=1;s=[DeviceX]Foo&Bar", "name": "Foo", "dataType": "Float4"}
    out = builder.serialize(tag)
    # '=' and '&' are unicode-escaped exactly as Ignition writes them.
    assert "\\u003d" in out
    assert "\\u0026" in out
    assert "=" not in out and "&" not in out
    # sort_keys parity: keys appear alphabetically.
    assert out.index('"dataType"') < out.index('"name"') < out.index('"opcItemPath"')
    # Round-trips back to the original once unicode escapes are decoded.
    assert json.loads(out)["opcItemPath"] == "ns=1;s=[DeviceX]Foo&Bar"


def test_history_never_writes_value_deadband():
    builder = IgnitionTagBuilder("DeviceX")
    tag = builder.tag("Lvl", "Some_Tag", "Float4", eng_low=0, eng_high=100,
                      history=True, time_deadband=15)
    assert tag["historyEnabled"] is True
    assert tag["historyProvider"] == "Ignition_SCADA"
    assert tag["historyTimeDeadband"] == 15
    for forbidden in ("historicalDeadband", "historicalDeadbandMode", "deadband", "deadbandStyle"):
        assert forbidden not in tag


def test_scaled_tag_carries_scaled_keys_distinct_from_eng():
    builder = IgnitionTagBuilder("DeviceX")
    tag = builder.tag("Raw", "Raw_Tag", "Int2", requires_scaling=True,
                      raw_low=0, raw_high=4095, scaled_low=0, scaled_high=100)
    assert tag["scaleMode"] == "Linear"
    assert tag["rawLow"] == 0.0 and tag["rawHigh"] == 4095.0
    # correction #2: scaledLow/scaledHigh carry the real conversion...
    assert tag["scaledLow"] == 0.0 and tag["scaledHigh"] == 100.0
    # ...and engLow/engHigh are distinct keys (display/deadband metadata).
    assert "engLow" in tag and "engHigh" in tag


def test_engineering_tag_has_no_scaling_keys():
    builder = IgnitionTagBuilder("DeviceX")
    tag = builder.tag("Eng", "Eng_Tag", "Float4", eng_low=0, eng_high=60, unit="Hz")
    for scaling_key in ("scaleMode", "rawLow", "rawHigh", "scaledLow", "scaledHigh"):
        assert scaling_key not in tag
    assert tag["engLow"] == 0.0 and tag["engHigh"] == 60.0 and tag["engUnit"] == "Hz"
