import os

import pytest

pytest_plugins = ["fixtures.browser_fixture", "fixtures.env_fixture"]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }
