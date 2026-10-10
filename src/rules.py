
from __future__ import annotations

import math
from typing import Any


# DEMONSTRATION THRESHOLDS ONLY.
# Replace these with verified limits from the actual equipment manual
# before using this application for real maintenance decisions.
DEFAULT_THRESHOLDS = {
    "vibration_mm_s": {
        "min": 0.0,
        "max": 4.5,
        "unit": "mm/s",
    },
    "bearing_temperature_c": {
        "min": 0.0,
        "max": 80.0,
        "unit": "°C",
    },
    "discharge_pressure_bar": {
        "min": 1.5,
        "max": 6.0,
        "unit": "bar",
    },
}

SEVERITY_BY_METRIC = {
    "vibration_mm_s": "warning",
    "bearing_temperature_c": "warning",
    "discharge_pressure_bar": "warning",
}


def _extract_value(reading: Any) -> float | None:
    """Extract a finite numeric value from a supported reading."""
    if isinstance(reading, bool):
        return None

    if isinstance(reading, dict):
        if "value" not in reading:
            return None
        reading = reading["value"]

    if not isinstance(reading, (int, float, str)):
        return None

    try:
        value = float(reading)
    except (TypeError, ValueError):
        return None

    return value if math.isfinite(value) else None


def evaluate_sensor_readings(
    readings: dict[str, Any],
    thresholds: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Evaluate sensor readings using deterministic rules.

    Supported reading formats:
        {"vibration_mm_s": 5.2}
        {"vibration_mm_s": {"value": 5.2, "unit": "mm/s"}}
        {"vibration_mm_s": [5.2, 5.4]}

    Lists represent multiple readings of the same metric. Conflicting
    values are flagged rather than silently averaged.
    """
    if not isinstance(readings, dict):
        raise ValueError("Sensor readings must be a dictionary.")

    limits = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    results = []
    alerts = []
    warnings = []

    for metric, rule in limits.items():
        if not isinstance(rule, dict):
            raise ValueError(f"Invalid threshold configuration for {metric}.")

        minimum = rule.get("min")
        maximum = rule.get("max")

        for bound_name, bound in (("min", minimum), ("max", maximum)):
            if bound is not None:
                if isinstance(bound, bool) or not isinstance(
                    bound, (int, float)
                ):
                    raise ValueError(
                        f"Threshold {bound_name} for {metric} must be numeric."
                    )
                if not math.isfinite(float(bound)):
                    raise ValueError(
                        f"Threshold {bound_name} for {metric} must be finite."
                    )

        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"Minimum exceeds maximum for {metric}.")

        if metric not in readings or readings[metric] is None:
            results.append({
                "metric": metric,
                "status": "missing",
                "message": "No sensor reading supplied; threshold check skipped.",
                "threshold": rule,
            })
            warnings.append(f"Missing reading: {metric}")
            continue

        raw = readings[metric]
        candidates = raw if isinstance(raw, list) else [raw]

        if not candidates:
            results.append({
                "metric": metric,
                "status": "missing",
                "message": "The reading list is empty.",
                "threshold": rule,
            })
            warnings.append(f"Missing reading: {metric}")
            continue

        values = [_extract_value(item) for item in candidates]

        if any(value is None for value in values):
            results.append({
                "metric": metric,
                "status": "invalid",
                "message": "One or more readings are invalid or non-finite.",
                "threshold": rule,
            })
            warnings.append(f"Invalid reading: {metric}")
            continue

        numeric_values = [float(value) for value in values]

        # A spread greater than 10% of the configured range is considered
        # conflicting demo data. This is a software rule, not a physical
        # safety standard.
        if len(numeric_values) > 1:
            if minimum is not None and maximum is not None:
                reference_range = float(maximum) - float(minimum)
            else:
                reference_range = max(abs(numeric_values[0]), 1.0)

            if max(numeric_values) - min(numeric_values) > (
                0.10 * max(reference_range, 1e-9)
            ):
                results.append({
                    "metric": metric,
                    "status": "conflicting",
                    "values": numeric_values,
                    "message": (
                        "Readings differ beyond the configured demo "
                        "tolerance. Verify the sensor before interpreting."
                    ),
                    "threshold": rule,
                })
                warnings.append(f"Conflicting readings: {metric}")
                continue

        value = numeric_values[0]

        below = minimum is not None and value < float(minimum)
        above = maximum is not None and value > float(maximum)

        if below or above:
            direction = "below minimum" if below else "above maximum"

            result = {
                "metric": metric,
                "value": value,
                "unit": rule.get("unit", ""),
                "status": "threshold_exceeded",
                "direction": direction,
                "threshold": rule,
                "severity": SEVERITY_BY_METRIC.get(metric, "warning"),
                "message": (
                    f"{metric} is {direction}. Verify the reading and "
                    "follow the approved inspection procedure."
                ),
            }
            results.append(result)
            alerts.append(result)
        else:
            results.append({
                "metric": metric,
                "value": value,
                "unit": rule.get("unit", ""),
                "status": "within_threshold",
                "threshold": rule,
                "message": "Reading is within the configured demo limits.",
            })

    return {
        "results": results,
        "alerts": alerts,
        "warnings": warnings,
        "has_alerts": bool(alerts),
        "has_warnings": bool(warnings),
        "overall_status": (
            "review_required"
            if alerts or warnings
            else "within_configured_limits"
        ),
        "note": (
            "Demo thresholds are not verified equipment safety limits. "
            "This result is not a diagnosis or authorization to operate."
        ),
    }
