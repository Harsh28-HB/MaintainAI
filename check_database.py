import os
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maintainai-db-check-") as temp_dir:
        os.environ["MAINTAINAI_DB_PATH"] = str(
            Path(temp_dir) / "maintainai.db"
        )
        from src.database import (
            create_issue,
            create_work_order,
            get_issue_history,
            get_work_orders,
            init_db,
            register_equipment,
            review_work_order,
        )

        init_db()
        register_equipment("CP-101", "Centrifugal Pump")

        issue_id = create_issue(
            equipment_id="CP-101",
            description="Unusual vibration during operation",
            operating_events=["Vibration noticed after startup"],
            sensor_readings={"vibration_mm_s": 5.2},
            observations=[
                {"text": "Vibration reading reported as 5.2 mm/s"}
            ],
        )

        work_order_id = create_work_order(
            issue_id,
            {
                "priority": "pending assessment",
                "actions": ["Inspect mounting bolts and alignment"],
            },
        )

        print("Issue history:", get_issue_history("CP-101"))
        print("Work orders before review:", get_work_orders(issue_id))

        review_work_order(
            work_order_id,
            "rejected",
            technician="Demo Technician",
            notes="Demonstration of the rejection workflow",
        )

        print("Work orders after review:", get_work_orders(issue_id))
        print("DATABASE CHECK PASSED")


if __name__ == "__main__":
    main()
