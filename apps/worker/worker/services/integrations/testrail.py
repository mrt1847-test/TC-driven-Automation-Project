from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlencode

import httpx

from worker.core.config import MASK, mask_secrets
from worker.models.schemas import NormalizedTestCase, SourceLocation, TestStep
from worker.services.case_import import _generate_automation_key, _parse_steps


class TestRailConnectorError(Exception):
    __test__ = False

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def import_from_testrail(
    project_id: int,
    suite_id: int | None,
    config: dict[str, Any],
    existing_keys: set[str] | None = None,
) -> list[NormalizedTestCase]:
    existing = existing_keys if existing_keys is not None else set()
    if bool(config.get("mock")):
        return _mock_cases(existing)

    missing = _missing_config(config)
    if missing:
        raise TestRailConnectorError(
            400,
            f"TestRail import requires {', '.join(missing)}. Configure TestRail in Settings and store the API token.",
        )

    raw_cases = await _fetch_testrail_cases(project_id, suite_id, config)
    return normalize_testrail_cases(raw_cases, project_id, suite_id, config, existing)


def normalize_testrail_cases(
    raw_cases: Iterable[dict[str, Any]],
    project_id: int,
    suite_id: int | None,
    config: dict[str, Any],
    existing_keys: set[str],
) -> list[NormalizedTestCase]:
    cases: list[NormalizedTestCase] = []
    endpoint = _api_url(str(config.get("base_url") or ""), f"get_cases/{project_id}", _suite_params(suite_id))
    for item in raw_cases:
        source_id = str(item.get("id") or item.get("case_id") or "")
        title = str(item.get("title") or source_id or "Untitled TestRail case")
        automation_key = _automation_key(item, title, source_id, existing_keys)
        existing_keys.add(automation_key)
        expected_result = _text(item.get("custom_expected") or item.get("expected_result") or item.get("expected"))
        cases.append(
            NormalizedTestCase(
                source_type="testrail",
                source_id=source_id,
                source_location=SourceLocation(api_endpoint=endpoint),
                title=title,
                preconditions=_preconditions(item),
                steps=_steps(item, title, expected_result),
                expected_result=expected_result,
                automation_key=automation_key,
                priority=_priority(item),
                start_url=_text(item.get("custom_start_url") or item.get("start_url")) or None,
            )
        )
    return cases


async def _fetch_testrail_cases(
    project_id: int,
    suite_id: int | None,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    base_url = str(config["base_url"])
    username = str(config["username"])
    api_token = str(config["api_token"])
    url: str | None = _api_url(base_url, f"get_cases/{project_id}", _suite_params(suite_id))
    cases: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            try:
                response = await client.get(
                    url,
                    auth=(username, api_token),
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as error:
                raise TestRailConnectorError(
                    502,
                    _mask_with_token(f"TestRail API request failed: {error}", api_token),
                ) from error
            _raise_for_testrail_error(response, api_token)
            payload = _json_payload(response, api_token)
            page_cases, next_url = _case_page(payload, base_url)
            cases.extend(page_cases)
            url = next_url
    return cases


def _case_page(payload: Any, base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None
    if not isinstance(payload, dict):
        raise TestRailConnectorError(502, "TestRail API returned an unsupported response shape.")
    raw_cases = payload.get("cases", [])
    cases = [item for item in raw_cases if isinstance(item, dict)] if isinstance(raw_cases, list) else []
    next_link = payload.get("_links", {}).get("next") if isinstance(payload.get("_links"), dict) else None
    if isinstance(next_link, str) and next_link:
        if next_link.startswith("http://") or next_link.startswith("https://"):
            return cases, next_link
        return cases, f"{base_url.rstrip('/')}{next_link}"
    return cases, None


def _raise_for_testrail_error(response: httpx.Response, api_token: str) -> None:
    if response.status_code < 400:
        return
    detail = _error_detail(response, api_token)
    if response.status_code in {401, 403}:
        raise TestRailConnectorError(response.status_code, f"TestRail credentials rejected or unauthorized. {detail}")
    if response.status_code == 404:
        raise TestRailConnectorError(404, f"TestRail project or suite was not found. {detail}")
    raise TestRailConnectorError(502, f"TestRail API returned HTTP {response.status_code}. {detail}")


def _json_payload(response: httpx.Response, api_token: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise TestRailConnectorError(
            502,
            _mask_with_token("TestRail API returned invalid JSON.", api_token),
        ) from error


def _error_detail(response: httpx.Response, api_token: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or str(payload)
    else:
        detail = str(payload)
    return _mask_with_token(detail, api_token)


def _missing_config(config: dict[str, Any]) -> list[str]:
    required = {
        "baseUrl": config.get("base_url"),
        "username": config.get("username"),
        "apiToken": config.get("api_token"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _mock_cases(existing: set[str]) -> list[NormalizedTestCase]:
    title = "Sample TestRail Case"
    source_id = "12345"
    automation_key = _generate_automation_key(title, "sample_testrail_case", existing)
    existing.add(automation_key)
    return [
        NormalizedTestCase(
            source_type="testrail",
            source_id=source_id,
            title=title,
            steps=[TestStep(index=1, action="Open app", expected="App loads")],
            automation_key=automation_key,
        )
    ]


def _api_url(base_url: str, endpoint: str, params: dict[str, Any] | None = None) -> str:
    url = f"{base_url.rstrip('/')}/index.php?/api/v2/{endpoint.lstrip('/')}"
    clean_params = {key: value for key, value in (params or {}).items() if value is not None}
    if clean_params:
        url = f"{url}&{urlencode(clean_params)}"
    return url


def _suite_params(suite_id: int | None) -> dict[str, Any]:
    return {"suite_id": suite_id} if suite_id is not None else {}


def _automation_key(item: dict[str, Any], title: str, source_id: str, existing: set[str]) -> str:
    raw = (
        item.get("custom_automation_key")
        or item.get("automation_key")
        or item.get("custom_automation_id")
        or item.get("refs")
    )
    key = _text(raw)
    if key and key not in existing:
        return key
    return _generate_automation_key(title, source_id, existing)


def _preconditions(item: dict[str, Any]) -> list[str]:
    raw = _text(item.get("custom_preconds") or item.get("preconditions"))
    return [line.strip() for line in raw.splitlines() if line.strip()] if raw else []


def _steps(item: dict[str, Any], title: str, expected_result: str | None) -> list[TestStep]:
    separated = item.get("custom_steps_separated")
    if isinstance(separated, list) and separated:
        steps: list[TestStep] = []
        for index, raw_step in enumerate(separated, start=1):
            if not isinstance(raw_step, dict):
                continue
            content = _text(raw_step.get("content") or raw_step.get("action") or raw_step.get("step"))
            expected = _text(raw_step.get("expected"))
            if content or expected:
                steps.append(TestStep(index=index, action=content or title, expected=expected or None))
        if steps:
            return steps

    raw_steps = _text(item.get("custom_steps") or item.get("steps"))
    if raw_steps:
        return _parse_steps(raw_steps, expected_result or "")
    return [TestStep(index=1, action=title, expected=expected_result)]


def _priority(item: dict[str, Any]) -> str | None:
    raw = item.get("priority")
    if isinstance(raw, dict):
        return _text(raw.get("name") or raw.get("short_name"))
    return _text(raw or item.get("priority_id")) or None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mask_with_token(message: str, api_token: str) -> str:
    masked = mask_secrets(message, {"TESTRAIL_API_TOKEN": api_token})
    return masked.replace(api_token, MASK) if api_token else masked
