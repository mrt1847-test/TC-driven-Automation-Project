from __future__ import annotations

from worker.models.schemas import NormalizedTestCase, TestStep


async def import_from_testrail(project_id: int, suite_id: int | None, config: dict) -> list[NormalizedTestCase]:
    # Placeholder for TestRail API v2 integration
    return [
        NormalizedTestCase(
            source_type="testrail",
            source_id="12345",
            title="Sample TestRail Case",
            steps=[TestStep(index=1, action="Open app", expected="App loads")],
            automation_key="sample_testrail_case",
        )
    ]
