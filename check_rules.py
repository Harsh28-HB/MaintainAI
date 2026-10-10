from src.rules import evaluate_sensor_readings


def run_checks():
    # Case 1: Normal readings
    normal = evaluate_sensor_readings({
        "vibration_mm_s": 3.0,
        "bearing_temperature_c": 55.0,
        "discharge_pressure_bar": 3.0,
    })
    assert not normal["has_alerts"]
    assert not normal["has_warnings"]
    print("PASS: Normal readings")

    # Case 2: Excessive vibration
    high = evaluate_sensor_readings({
        "vibration_mm_s": 5.2,
    })
    assert high["has_alerts"]
    assert high["alerts"][0]["metric"] == "vibration_mm_s"
    print("PASS: Threshold violation")

    # Case 3: Missing readings
    missing = evaluate_sensor_readings({})
    assert missing["has_warnings"]
    print("PASS: Missing sensor data")

    # Case 4: Invalid reading
    invalid = evaluate_sensor_readings({
        "vibration_mm_s": float("nan"),
    })
    assert invalid["has_warnings"]
    assert invalid["results"][0]["status"] == "invalid"
    print("PASS: Invalid sensor data")

    # Case 5: Conflicting readings
    conflicting = evaluate_sensor_readings({
        "vibration_mm_s": [2.0, 4.0],
    })
    assert conflicting["has_warnings"]
    assert conflicting["results"][0]["status"] == "conflicting"
    print("PASS: Conflicting sensor data")

    # Case 6: Invalid threshold configuration
    try:
        evaluate_sensor_readings(
            {"vibration_mm_s": 3.0},
            {"vibration_mm_s": {"min": 5.0, "max": 1.0}},
        )
    except ValueError:
        print("PASS: Invalid threshold configuration")
    else:
        raise AssertionError("Invalid threshold configuration was accepted")

    print("\nAll rule checks passed!")


if __name__ == "__main__":
    run_checks()
