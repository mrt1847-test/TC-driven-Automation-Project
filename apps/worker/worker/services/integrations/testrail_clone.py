from __future__ import annotations

import httpx

from worker.core.config import load_settings
from worker.models.schemas import NormalizedTestCase, TestStep
from worker.services.case_import import _generate_automation_key


async def import_from_testrail_clone(project_id: str, suite_id: str | None, existing_keys: set[str]) -> list[NormalizedTestCase]:
    settings = load_settings()
    base_url = settings.integrations.get("testrailClone", {}).get("baseUrl", "http://localhost:3000")
    params = {"projectId": project_id}
    if suite_id:
        params["suiteId"] = suite_id
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/api/automation/cases", params=params)
        resp.raise_for_status()
        payload = resp.json()

    cases: list[NormalizedTestCase] = []
    for item in payload.get("cases", []):
        case_id = str(item.get("caseId", ""))
        title = item.get("title", case_id)
        automation_key = item.get("automationKey") or _generate_automation_key(title, case_id, existing_keys)
        existing_keys.add(automation_key)
        steps = [TestStep(index=i + 1, action=s.get("action", ""), expected=s.get("expected")) for i, s in enumerate(item.get("steps", []))]
        cases.append(NormalizedTestCase(
            source_type="testrail-clone",
            source_id=case_id,
            title=title,
            steps=steps,
            automation_key=automation_key,
            expected_result=item.get("expectedResult"),
        ))
    return cases
