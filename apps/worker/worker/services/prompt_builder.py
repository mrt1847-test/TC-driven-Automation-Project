from __future__ import annotations

from worker.models.schemas import NormalizedTestCase


def build_webwright_prompt(
    case: NormalizedTestCase,
    start_url: str | None = None,
    environment: str = "stg",
    *,
    preset_guidance: str | None = None,
    batch_prompt: str | None = None,
    case_prompt_override: str | None = None,
) -> str:
    url = start_url or case.start_url or "https://example.com"
    preconditions = "\n".join(f"- {p}" for p in case.preconditions) or "- None"
    steps = "\n".join(f"{s.index}. {s.action}" + (f" (Expected: {s.expected})" if s.expected else "") for s in case.steps)
    prompt = f"""You are generating a Playwright Python automation draft for the following QA test case.

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
    context_blocks: list[str] = []
    if preset_guidance and preset_guidance.strip():
        context_blocks.append(f"Prompt Preset Guidance:\n{preset_guidance.strip()}")
    if batch_prompt and batch_prompt.strip():
        context_blocks.append(f"Batch Shared Prompt:\n{batch_prompt.strip()}")
    if case_prompt_override and case_prompt_override.strip():
        context_blocks.append(f"Per-Case Prompt Override:\n{case_prompt_override.strip()}")
    if context_blocks:
        prompt += "\nAdditional Prompt Context:\n" + "\n\n".join(context_blocks) + "\n"
    return prompt
