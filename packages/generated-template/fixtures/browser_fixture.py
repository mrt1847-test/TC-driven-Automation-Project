import os

import pytest


def _headless_default() -> bool:
    value = os.environ.get("TC_HEADLESS", "true").lower()
    return value not in ("0", "false", "no")


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"headless": _headless_default()}
