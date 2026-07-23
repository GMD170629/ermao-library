def test_health_response_shape(client, test_settings):
    monitor = test_settings.resolved_monitor_root
    assert monitor is not None
    monitor.mkdir(parents=True)
    setup = client.post(
        "/api/auth/setup",
        json={
            "name": "Administrator",
            "email": "admin@example.com",
            "password": "starshipnas",
        },
    )
    assert setup.status_code == 201

    response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"
    assert isinstance(payload["data"]["checks"], list)
    conversion = next(check for check in payload["data"]["checks"] if check["name"] == "ebookConversion")
    assert conversion["details"]["converter"] == "libmobi+shuku-internal"
    assert {engine["converter"] for engine in conversion["details"]["engines"]} == {"libmobi", "shuku-internal"}


def test_health_reports_monitor_failure(client):
    response = client.get("/api/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["service"] == "shuku-starship"
    assert payload["data"]["status"] == "error"
