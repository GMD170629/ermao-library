from io import BytesIO
from pathlib import Path

from fastapi import Request
from PIL import Image

from app.core.config import Settings
from app.modules.media.infrastructure.http_streaming import send_pse_page_file


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/opds/page",
            "headers": [],
            "query_string": b"",
        }
    )


def _settings(storage_root: Path) -> Settings:
    return Settings(session_secret="test-secret", storage_root=str(storage_root))


def test_pse_preserves_uniform_png_and_never_upscales(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    Image.new("RGBA", (320, 200), (255, 0, 0, 128)).save(source, format="PNG")

    response = send_pse_page_file(
        source,
        _request(),
        "user-1",
        _settings(tmp_path / "storage"),
        max_width=640,
        asset_id="asset-1",
        output_media_type="image/png",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["x-opds-pse-width"] == "640"
    with (
        Image.open(source) as original,
        Image.open(BytesIO(response.body)) as delivered,
    ):
        assert delivered.size == original.size == (320, 200)


def test_pse_gif_is_returned_without_a_width_variant_and_head_has_no_body(
    tmp_path: Path,
) -> None:
    source = tmp_path / "page.gif"
    Image.new("P", (16, 16)).save(source, format="GIF")
    settings = _settings(tmp_path / "storage")

    get_response = send_pse_page_file(
        source,
        _request(),
        "user-1",
        settings,
        max_width=None,
        asset_id="asset-1",
        output_media_type="image/gif",
    )
    head_response = send_pse_page_file(
        source,
        _request("HEAD"),
        "user-1",
        settings,
        max_width=None,
        asset_id="asset-1",
        output_media_type="image/gif",
    )

    assert get_response.body == source.read_bytes()
    assert get_response.headers["content-type"].startswith("image/gif")
    assert head_response.body == b""
    assert int(head_response.headers["content-length"]) == len(source.read_bytes())
