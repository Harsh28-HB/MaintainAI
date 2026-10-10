import pytest

from src.rules import evaluate_sensor_readings


def test_normal_sensor_readings():
    result = evaluate_sensor_readings({
        "vibration_mm_s": 3.0,
        "bearing_temperature_c": 55.0,
        "discharge_pressure_bar": 3.0,
    })

    assert result["has_alerts"] is False
    assert result["has_warnings"] is False


def test_high_vibration_triggers_alert():
    result = evaluate_sensor_readings({"vibration_mm_s": 5.2})

    assert result["has_alerts"] is True
    assert any(
        alert["metric"] == "vibration_mm_s"
        for alert in result["alerts"]
    )


def test_missing_readings_are_reported():
    result = evaluate_sensor_readings({})

    assert result["has_warnings"] is True
    assert all(
        item["status"] == "missing"
        for item in result["results"]
    )


def test_invalid_sensor_reading_is_flagged():
    result = evaluate_sensor_readings({
        "vibration_mm_s": float("nan")
    })

    assert result["results"][0]["status"] == "invalid"


def test_conflicting_sensor_readings_are_flagged():
    result = evaluate_sensor_readings({
        "vibration_mm_s": [2.0, 4.0]
    })

    assert result["results"][0]["status"] == "conflicting"


def test_invalid_thresholds_are_rejected():
    with pytest.raises(ValueError):
        evaluate_sensor_readings(
            {"vibration_mm_s": 3.0},
            {"vibration_mm_s": {"min": 5.0, "max": 1.0}},
        )
