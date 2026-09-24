from __future__ import annotations


def test_reimport_posts_remain_bodyless_and_typed(client) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/library-import-tasks/{task_id}/continue" not in paths

    for path in (
        "/api/source-nodes/{source_node_id}/continue",
        "/api/library-import-tasks/{task_id}/reimport",
    ):
        operation = paths[path]["post"]
        assert "requestBody" not in operation
        response = operation["responses"]["202"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {
            "$ref": "#/components/schemas/SuccessEnvelope_ContinueImportPayload_"
        }


def test_reimport_posts_require_authentication(client) -> None:
    source_response = client.post("/api/source-nodes/missing/continue")
    task_response = client.post("/api/library-import-tasks/missing/reimport")

    assert source_response.status_code == 401
    assert task_response.status_code == 401
    assert task_response.json() == source_response.json()
