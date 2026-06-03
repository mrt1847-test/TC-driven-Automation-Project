pytest_plugins = ["fixtures.browser_fixture", "fixtures.env_fixture"]


def pytest_addoption(parser):
    for name, kwargs in [
        ("--browser", {"default": "chromium"}),
        ("--headed", {"action": "store_true", "default": False}),
    ]:
        try:
            parser.addoption(name, **kwargs)
        except ValueError:
            pass
