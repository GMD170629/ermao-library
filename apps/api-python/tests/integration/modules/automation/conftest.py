import pytest


@pytest.fixture(autouse=True)
def isolated_automation_secrets(monkeypatch, test_settings):
    monkeypatch.setattr("app.bootstrap.automation.get_settings", lambda: test_settings)
