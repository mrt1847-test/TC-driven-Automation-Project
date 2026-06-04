from __future__ import annotations

from sqlmodel import Session, select

from worker.models.db import RawAction
from worker.services.action_extraction import (
    CORE_ACTION_TYPES,
    EXTENDED_ACTION_TYPES,
    SUPPORTED_ACTION_TYPES,
    extract_actions_from_script,
)


def test_action_extraction_covers_core_extended_and_custom_playwright_shapes(
    client,
    tmp_path,
) -> None:
    import worker.core.database as database

    script_path = tmp_path / "expanded_actions.py"
    script_path.write_text(
        "\n".join(
            [
                "page.goto('https://example.test')",
                "page.get_by_role('button', name='Submit').click(timeout=1000)",
                "page.locator('#name').fill('Ada')",
                "page.locator('#country').select_option('KR')",
                "page.locator('#tos').check()",
                "page.locator('#tos').uncheck()",
                "page.locator('#menu').hover()",
                "page.keyboard.press('Enter')",
                "page.locator('#upload').set_input_files(['a.txt', 'b.txt'])",
                "page.locator('#source').drag_to(page.locator('#target'))",
                "page.wait_for_timeout(250)",
                "page.wait_for_load_state('networkidle')",
                "page.locator('#ready').wait_for(state='visible')",
                "with page.expect_request(re.compile(r'/track')) as request_info:",
                "    pass",
                "with page.expect_response('**/api/items') as response_info:",
                "    pass",
                "expect(page.locator('#message')).to_contain_text('Done')",
                "expect(page).to_have_url(re.compile(r'/done'))",
                "expect(page.locator('#dialog')).to_be_visible()",
                "expect(page.locator('#spinner')).to_be_hidden()",
                "expect(page.locator('.row')).to_have_count(3)",
                "button = page.get_by_role('button', name='Ignored locator setup')",
                "page.locator('#thing').dblclick()",
                "expect(page.locator('#thing')).to_have_attribute('data-long-state-name', 'ready-for-review-with-complete-raw-text-preserved-without-truncation')",
                "await page.locator('#async-submit').click()",
                "async with page.expect_response('**/async/items') as async_response:",
                "    pass",
                "logger.info('not a Playwright operation')",
            ]
        ),
        encoding="utf-8",
    )

    with Session(database.engine) as session:
        actions = extract_actions_from_script(
            str(script_path),
            "expanded_actions",
            "ww_expanded_actions",
            session,
        )
        persisted = session.exec(
            select(RawAction)
            .where(RawAction.webwright_run_id == "ww_expanded_actions")
            .order_by(RawAction.order_index)
        ).all()

        second_pass = extract_actions_from_script(
            str(script_path),
            "expanded_actions",
            "ww_expanded_actions",
            session,
        )
        persisted_second_pass = session.exec(
            select(RawAction)
            .where(RawAction.webwright_run_id == "ww_expanded_actions")
            .order_by(RawAction.order_index)
        ).all()

    expected_types = [
        "goto",
        "click",
        "fill",
        "select",
        "check",
        "uncheck",
        "hover",
        "press",
        "set_input_files",
        "drag_to",
        "wait",
        "wait",
        "wait",
        "wait_for_request",
        "wait_for_response",
        "assert_text",
        "assert_url",
        "assert_visible",
        "assert_hidden",
        "assert_count",
        "custom_code",
        "custom_code",
        "click",
        "wait_for_response",
    ]
    assert [action.type for action in actions] == expected_types
    assert [action.order_index for action in actions] == list(range(1, len(actions) + 1))
    assert [action.type for action in persisted] == expected_types
    assert [action.type for action in second_pass] == expected_types
    assert [action.type for action in persisted_second_pass] == expected_types
    assert len(persisted_second_pass) == len(actions)

    by_type = {}
    for action in actions:
        if action.type not in {"wait", "custom_code"}:
            by_type.setdefault(action.type, action)
    assert by_type["goto"].target == "https://example.test"
    assert by_type["click"].selector == "page.get_by_role('button', name='Submit')"
    assert by_type["fill"].value == "Ada"
    assert by_type["select"].selector == "page.locator('#country')"
    assert by_type["select"].value == "KR"
    assert by_type["press"].selector == "page.keyboard"
    assert by_type["press"].value == "Enter"
    assert by_type["set_input_files"].value == "['a.txt', 'b.txt']"
    assert by_type["drag_to"].selector == "page.locator('#source')"
    assert by_type["drag_to"].value == "page.locator('#target')"
    assert by_type["wait_for_request"].value == "/track"
    assert by_type["wait_for_response"].value == "**/api/items"
    assert by_type["assert_text"].selector == "page.locator('#message')"
    assert by_type["assert_text"].value == "Done"
    assert by_type["assert_url"].selector is None
    assert by_type["assert_url"].value == "/done"
    assert by_type["assert_count"].value == "3"

    waits = [action for action in actions if action.type == "wait"]
    assert [action.value for action in waits] == ["250", "networkidle", "visible"]
    assert waits[2].selector == "page.locator('#ready')"

    custom = [action for action in actions if action.type == "custom_code"]
    assert "dblclick" in (custom[0].target or "")
    assert "to_have_attribute" in (custom[1].target or "")
    assert custom[1].target and len(custom[1].target) > 120
    assert custom[1].target.endswith("without-truncation')")
    assert actions[-2].selector == "page.locator('#async-submit')"
    assert actions[-1].type == "wait_for_response"
    assert actions[-1].value == "**/async/items"
    assert all(action.source_line for action in actions)
    assert len(CORE_ACTION_TYPES) == 17
    assert set(EXTENDED_ACTION_TYPES) == {"set_input_files", "drag_to"}
    assert set(expected_types).issubset(SUPPORTED_ACTION_TYPES)
