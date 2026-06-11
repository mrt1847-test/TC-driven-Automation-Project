"""C8-11/C8-12: generated method body full-plan rendering and value parameterization."""
from __future__ import annotations

import json
from types import SimpleNamespace

from sqlmodel import Session

from worker.models.db import PageObjectMethod
from worker.services.project_generator import _method_body, _page_content


def _pom(
    body_plan: list[dict] | None,
    *,
    name: str = "do_step",
    method_type: str = "composite",
    selector: str | None = None,
    value_template: str | None = None,
) -> PageObjectMethod:
    return PageObjectMethod(
        id=f"pom_{name}",
        page_object_id="po_test",
        name=name,
        method_type=method_type,
        selector=selector,
        value_template=value_template,
        body_plan_json=json.dumps(body_plan) if body_plan is not None else "[]",
        status="approved",
    )


def _entry(action: str, **kwargs) -> dict:
    return {"action": action, **kwargs}


def test_method_body_renders_all_plan_entries_in_order() -> None:
    plan = [
        _entry("goto", value="https://example.test/login"),
        _entry("fill", selector="page.get_by_label('Email')", value="user@example.test"),
        _entry("click", selector="page.get_by_role('button', name='Login')"),
        _entry("assert_visible", selector="page.get_by_text('Dashboard')"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        self.page.goto(\"https://example.test/login\")",
        "        self.page.get_by_label('Email').fill(\"user@example.test\")",
        "        self.page.get_by_role('button', name='Login').click()",
        "        expect(self.page.get_by_text('Dashboard')).to_be_visible()",
    ]


def test_method_body_extended_interaction_coverage() -> None:
    plan = [
        _entry("select", selector="page.get_by_label('Country')", value="KR"),
        _entry("set_input_files", selector="page.locator('#upload')", value="report.pdf"),
        _entry("set_input_files", selector="page.locator('#multi')", value="['a.png', 'b.png']"),
        _entry("drag_to", selector="page.locator('#card')", value="page.locator('#done-column')"),
        _entry("press", selector="page.get_by_label('Search')", value="Enter"),
        _entry("check", selector="page.get_by_label('Agree')"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        self.page.get_by_label('Country').select_option(\"KR\")",
        "        self.page.locator('#upload').set_input_files(\"report.pdf\")",
        "        self.page.locator('#multi').set_input_files(['a.png', 'b.png'])",
        "        self.page.locator('#card').drag_to(self.page.locator('#done-column'))",
        "        self.page.get_by_label('Search').press(\"Enter\")",
        "        self.page.get_by_label('Agree').check()",
    ]


def test_method_body_assertion_coverage() -> None:
    plan = [
        _entry("assert_text", selector="page.locator('#message')", value="Saved"),
        _entry("assert_url", value="https://example.test/done"),
        _entry("assert_visible", selector="page.locator('#dialog')"),
        _entry("assert_hidden", selector="page.locator('#spinner')"),
        _entry("assert_count", selector="page.locator('.row')", value="3"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        expect(self.page.locator('#message')).to_contain_text(\"Saved\")",
        "        expect(self.page).to_have_url(\"https://example.test/done\")",
        "        expect(self.page.locator('#dialog')).to_be_visible()",
        "        expect(self.page.locator('#spinner')).to_be_hidden()",
        "        expect(self.page.locator('.row')).to_have_count(3)",
    ]


def test_method_body_assert_count_non_int_falls_back_to_comment() -> None:
    plan = [_entry("assert_count", selector="page.locator('.row')", value="several")]
    body = _method_body(_pom(plan))
    assert body == [
        "        # unsupported generated action: assert_count page.locator('.row')",
        "        pass",
    ]


def test_method_body_wait_coverage() -> None:
    plan = [
        _entry("wait", selector="page.locator('#ready')", value="visible"),
        _entry("wait", selector="page.locator('#ready')"),
        _entry("wait", value="networkidle"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        self.page.locator('#ready').wait_for(state=\"visible\")",
        "        self.page.locator('#ready').wait_for()",
        "        self.page.wait_for_load_state(\"networkidle\")",
    ]


def test_method_body_wait_for_request_stays_reviewable_comment() -> None:
    plan = [
        _entry("wait_for_request", value="**/api/save", target="**/api/save"),
        _entry("click", selector="page.get_by_role('button', name='Save')"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        # unsupported generated action: wait_for_request **/api/save",
        "        self.page.get_by_role('button', name='Save').click()",
    ]


def test_method_body_review_required_entries_stay_comments() -> None:
    plan = [
        _entry(
            "wait",
            value="2500",
            target="page.wait_for_timeout(2500)",
            requiresReview=True,
            reviewReason="hard_wait",
        ),
        _entry(
            "custom_code",
            target="page.evaluate('window.scrollTo(0, 0)')",
            requiresReview=True,
            reviewReason="unsupported_action",
        ),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        # review required (hard_wait): wait page.wait_for_timeout(2500)",
        "        # review required (unsupported_action): custom_code page.evaluate('window.scrollTo(0, 0)')",
        "        pass",
    ]


def test_method_body_strips_terminal_action_from_selector() -> None:
    plan = [
        _entry("click", selector="page.get_by_role('link', name='More information').click()"),
        _entry("select", selector="page.get_by_label('Country').select_option('KR')", value="KR"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        self.page.get_by_role('link', name='More information').click()",
        "        self.page.get_by_label('Country').select_option(\"KR\")",
    ]
    assert not any(".click().click()" in line for line in body)
    assert not any(".select_option('KR').select_option" in line for line in body)


def test_method_body_is_deterministic() -> None:
    plan = [
        _entry("goto", value="https://example.test"),
        _entry("assert_visible", selector="page.locator('#ok')"),
    ]
    assert _method_body(_pom(plan)) == _method_body(_pom(plan))


def test_method_body_legacy_selector_fallback_without_plan() -> None:
    pom = _pom(
        None,
        method_type="click",
        selector="page.get_by_role('button', name='Go')",
    )
    assert _method_body(pom) == [
        "        self.page.get_by_role('button', name='Go').click()",
    ]

    navigate = _pom(None, method_type="navigate", selector="page", value_template="https://example.test")
    assert _method_body(navigate) == [
        "        self.page.goto(\"https://example.test\")",
    ]


def test_method_body_empty_plan_without_selector_is_pass() -> None:
    assert _method_body(_pom([])) == ["        pass"]


def test_method_body_goto_resolves_relative_against_base_url() -> None:
    plan = [
        _entry("goto", value="https://example.test/login?next=%2Fhome#form"),
        _entry("goto", value="https://example.test"),
    ]
    body = _method_body(_pom(plan), base_url="https://example.test")
    assert body == [
        "        self.page.goto(\"/login?next=%2Fhome#form\")",
        "        self.page.goto(\"/\")",
    ]


def test_method_body_goto_keeps_absolute_for_foreign_origin() -> None:
    plan = [
        _entry("goto", value="https://other.example/login"),
        _entry("goto", value="http://example.test/insecure"),
    ]
    body = _method_body(_pom(plan), base_url="https://example.test")
    assert body == [
        "        self.page.goto(\"https://other.example/login\")",
        "        self.page.goto(\"http://example.test/insecure\")",
    ]


def test_method_body_goto_without_base_url_stays_absolute() -> None:
    plan = [_entry("goto", value="https://example.test/login")]
    assert _method_body(_pom(plan)) == [
        "        self.page.goto(\"https://example.test/login\")",
    ]


def test_method_body_env_placeholder_values_render_env_lookup() -> None:
    plan = [
        _entry("fill", selector="page.get_by_label('Email')", value="${env.user.email}"),
        _entry("fill", selector="page.get_by_label('Memo')", value="hello ${env.user.name}!"),
        _entry("select", selector="page.get_by_label('Region')", value="${env.region}"),
        _entry("assert_text", selector="page.locator('#welcome')", value="${env.user.name}"),
        _entry("goto", value="${env.startUrl}"),
    ]
    body = _method_body(_pom(plan), base_url="https://example.test")
    assert body == [
        "        self.page.get_by_label('Email').fill(self._env_value(\"user.email\"))",
        "        self.page.get_by_label('Memo').fill(\"hello {}!\".format(self._env_value(\"user.name\")))",
        "        self.page.get_by_label('Region').select_option(self._env_value(\"region\"))",
        "        expect(self.page.locator('#welcome')).to_contain_text(self._env_value(\"user.name\"))",
        "        self.page.goto(self._env_value(\"startUrl\"))",
    ]


def test_method_body_non_placeholder_values_keep_literal_rendering() -> None:
    plan = [
        _entry("fill", selector="page.get_by_label('Note')", value="plain $ {env.x} text"),
        _entry("fill", selector="page.get_by_label('Other')", value="${data.user}"),
    ]
    body = _method_body(_pom(plan))
    assert body == [
        "        self.page.get_by_label('Note').fill(\"plain $ {env.x} text\")",
        "        self.page.get_by_label('Other').fill(\"${data.user}\")",
    ]


def test_method_body_parameterized_output_is_deterministic() -> None:
    plan = [
        _entry("goto", value="https://example.test/login"),
        _entry("fill", selector="page.get_by_label('Email')", value="${env.user.email}"),
    ]
    first = _method_body(_pom(plan), base_url="https://example.test")
    second = _method_body(_pom(plan), base_url="https://example.test")
    assert first == second


def _generation_for(case_key: str, case_id: str, method_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        case=SimpleNamespace(automation_key=case_key, id=case_id),
        steps=[SimpleNamespace(page_object_method_id=method_id) for method_id in method_ids],
    )


def test_page_content_adds_expect_import_only_when_assertions_exist(client) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        with_assert = _pom(
            [_entry("assert_visible", selector="page.locator('#ok')")],
            name="verify_ok",
        )
        without_assert = _pom(
            [_entry("click", selector="page.locator('#go')")],
            name="click_go",
        )
        session.add(with_assert)
        session.add(without_assert)
        session.commit()

        content = _page_content(session, [
            _generation_for("case_a", "tc_a", [with_assert.id, without_assert.id]),
        ])
        assert content.startswith("from playwright.sync_api import expect")
        assert "expect(self.page.locator('#ok')).to_be_visible()" in content
        assert "self.page.locator('#go').click()" in content

        interaction_only = _page_content(session, [
            _generation_for("case_b", "tc_b", [without_assert.id]),
        ])
        assert "import expect" not in interaction_only
        assert interaction_only.startswith("class GeneratedPage:")


def test_page_content_emits_env_helper_only_when_placeholders_used(client) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        with_env = _pom(
            [
                _entry("fill", selector="page.get_by_label('Email')", value="${env.user.email}"),
                _entry("assert_visible", selector="page.locator('#ok')"),
            ],
            name="login_with_env",
        )
        without_env = _pom(
            [_entry("click", selector="page.locator('#go')")],
            name="click_go_env_free",
        )
        session.add(with_env)
        session.add(without_env)
        session.commit()

        content = _page_content(session, [
            _generation_for("case_env", "tc_env", [with_env.id, without_env.id]),
        ])
        assert content.startswith("import json\nimport os\nfrom pathlib import Path")
        assert "from playwright.sync_api import expect" in content
        assert "def _load_env_config():" in content
        assert "self._env_config = _load_env_config()" in content
        assert "def _env_value(self, path):" in content
        assert "self.page.get_by_label('Email').fill(self._env_value(\"user.email\"))" in content
        compile(content, "generated_page.py", "exec")

        env_free = _page_content(session, [
            _generation_for("case_plain", "tc_plain", [without_env.id]),
        ])
        assert env_free.startswith("class GeneratedPage:")
        assert "_load_env_config" not in env_free
        assert "_env_value" not in env_free
        compile(env_free, "generated_page.py", "exec")
