from __future__ import annotations

from worker.services.case_import import _parse_steps


def test_parse_steps_maps_expected_lines_one_to_one() -> None:
    steps = _parse_steps(
        "Open login page\nEnter credentials\nClick login",
        "Login page is visible\nCredentials accepted\nDashboard opens",
    )

    assert [step.expected for step in steps] == [
        "Login page is visible",
        "Credentials accepted",
        "Dashboard opens",
    ]


def test_parse_steps_keeps_single_step_expected() -> None:
    steps = _parse_steps("Open app", "App loads")

    assert len(steps) == 1
    assert steps[0].expected == "App loads"


def test_parse_steps_treats_single_expected_as_case_level_only() -> None:
    steps = _parse_steps(
        "Given user opens SauceDemo login page\n"
        "When user enters invalid credentials\n"
        "And clicks Login\n"
        "Then login error message is shown",
        "Login error message is shown",
    )

    assert len(steps) == 4
    assert all(step.expected is None for step in steps)


def test_parse_steps_supports_semicolon_delimited_pairs() -> None:
    steps = _parse_steps(
        "example.com 접속; More information 링크 클릭",
        "iana.org 도메인 페이지 표시; PDP 이동",
    )

    assert [step.expected for step in steps] == [
        "iana.org 도메인 페이지 표시",
        "PDP 이동",
    ]
