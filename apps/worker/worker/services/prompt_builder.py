from __future__ import annotations

from worker.models.schemas import NormalizedTestCase


def build_webwright_prompt(case: NormalizedTestCase, start_url: str | None = None, environment: str = "stg") -> str:
    url = start_url or case.start_url or "https://example.com"
    preconditions = "\n".join(f"- {p}" for p in case.preconditions) or "- None"
    steps = "\n".join(f"{s.index}. {s.action}" + (f" (Expected: {s.expected})" if s.expected else "") for s in case.steps)
    return f"""You are generating a Playwright Python automation draft for the following QA test case.

Automation Key:
{case.automation_key}

Start URL:
{url}

Environment:
{environment}

Goal:
{case.title}

Preconditions:
{preconditions}

Steps:
{steps}

Expected Result:
{case.expected_result or 'As described in steps'}

Constraints:
- Prefer stable selectors.
- Avoid hard-coded dynamic ids.
- Add explicit waits where necessary.
- Produce a final Playwright Python script.
"""
