from src.ai_service import analyze_issue, AIServiceError
from src.rules import evaluate_sensor_readings
from src.retrieval import search_manuals

issue = {
    "equipment_id": "CP-101",
    "equipment_type": "Centrifugal Pump",
    "description": "Unusual vibration during operation",
    "operating_events": ["Vibration noticed after startup"],
}

sensors = evaluate_sensor_readings({
    "vibration_mm_s": 5.2,
})

evidence = search_manuals(
    "excessive vibration bearing wear inspection",
    top_k=3,
)

print("Retrieved evidence:", len(evidence))

try:
    result = analyze_issue(issue, sensors, evidence)
    print("\nAI provider:", result["ai_provider"])
    print("Possible causes:", result["possible_causes"])
    print("Follow-up questions:", result["follow_up_questions"])
    print("Proposed priority:", result["proposed_priority"])
    print("Work-order draft:", result["draft_work_order"])
    print("\nPASS: Local AI analysis completed")

except AIServiceError as exc:
    print("\nAI analysis failed:", exc)
    raise
