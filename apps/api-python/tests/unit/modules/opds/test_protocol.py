from __future__ import annotations

import base64
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from app.modules.opds.application.dto import (
    OPDS_ACQUISITION_REL,
    OpdsAuthorDto,
    OpdsEntryDto,
    OpdsFeedDto,
    OpdsLinkDto,
    PsePageRequestDto,
    PseStreamDto,
    normalize_pse_max_width,
    select_pse_stream_media_type,
)
from app.modules.opds.domain.errors import OpdsAuthenticationRequired
from app.modules.opds.presentation.atom import serialize_opds_feed
from app.modules.opds.presentation.auth import parse_basic_authorization
from app.modules.opds.presentation.opensearch import serialize_opensearch_description
from app.modules.opds.presentation.schemas import OpdsProgressionDocument


def test_pse_resource_page_number_is_zero_based_but_internal_index_is_one_based() -> None:
    request = PsePageRequestDto(
        actor_id="user-1",
        resource_id="resource-1",
        page_number=0,
        max_width=1080,
    )

    assert request.internal_page_index == 1
    assert normalize_pse_max_width(request.max_width) == 960


def test_opensearch_description_escapes_and_publishes_atom_template() -> None:
    payload = serialize_opensearch_description(
        "https://books.example/search?q={searchTerms}&page=1"
    )
    root = ET.fromstring(payload)
    namespace = {"os": "http://a9.com/-/spec/opensearch/1.1/"}
    url = root.find("os:Url", namespace)

    assert url is not None
    assert url.attrib["template"].endswith("q={searchTerms}&page=1")
    assert "kind=navigation" in url.attrib["type"]


def test_pse_max_width_never_exceeds_request_and_is_bounded() -> None:
    assert normalize_pse_max_width(None) is None
    assert normalize_pse_max_width(31) == 31
    assert normalize_pse_max_width(1000) == 960
    assert normalize_pse_max_width(9000) == 2560
    with pytest.raises(ValueError):
        normalize_pse_max_width(0)


def test_pse_mime_is_preserved_only_for_uniform_supported_pages() -> None:
    assert select_pse_stream_media_type(("image/png", "image/png")) == "image/png"
    assert select_pse_stream_media_type(("image/jpeg; charset=binary",)) == "image/jpeg"
    assert select_pse_stream_media_type(("image/png", "image/jpeg")) == "image/jpeg"
    assert select_pse_stream_media_type(("image/webp",)) == "image/jpeg"
    assert select_pse_stream_media_type(()) == "image/jpeg"


def test_pse_last_read_is_strictly_one_based() -> None:
    with pytest.raises(ValueError):
        PseStreamDto(
            href_template="https://books.test/pages/{pageNumber}",
            media_type="image/jpeg",
            page_count=3,
            last_read=0,
        )
    with pytest.raises(ValueError):
        PseStreamDto(
            href_template="https://books.test/pages/{pageNumber}",
            media_type="image/avif",
            page_count=3,
        )


def test_atom_serializer_emits_opensearch_and_pse_contract() -> None:
    now = datetime(2026, 8, 3, 8, 30, tzinfo=UTC)
    feed = OpdsFeedDto(
        id="urn:shuku:catalog",
        title="Shuku",
        updated_at=now,
        kind="acquisition",
        self_url="https://books.test/opds/v1.2/catalog",
        start_url="https://books.test/opds/v1.2/catalog",
        search_url_template="https://books.test/opds/v1.2/search?q={searchTerms}",
        entries=(
            OpdsEntryDto(
                id="urn:shuku:resource:1",
                title="Resource & One",
                updated_at=now,
                authors=(OpdsAuthorDto(name="Author <One>"),),
                links=(
                    OpdsLinkDto(
                        href="https://books.test/files/1.cbz",
                        rel=OPDS_ACQUISITION_REL,
                        media_type="application/zip",
                    ),
                ),
                pse_stream=PseStreamDto(
                    href_template="https://books.test/pages/{pageNumber}?maxWidth={maxWidth}",
                    media_type="image/jpeg",
                    page_count=12,
                    last_read=4,
                    last_read_date=now,
                ),
            ),
        ),
        total_results=1,
        start_index=0,
        items_per_page=50,
    )

    payload = serialize_opds_feed(feed)
    root = ET.fromstring(payload)
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "pse": "http://vaemendis.net/opds-pse/ns",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    }
    assert root.findtext("opensearch:totalResults", namespaces=namespaces) == "1"
    assert (
        root.findtext("atom:entry/atom:title", namespaces=namespaces) == "Resource & One"
    )
    pse = root.find(
        "atom:entry/atom:link[@rel='http://vaemendis.net/opds-pse/stream']",
        namespaces,
    )
    assert pse is not None
    assert pse.attrib["type"] == "image/jpeg"
    assert pse.attrib["{http://vaemendis.net/opds-pse/ns}count"] == "12"
    assert pse.attrib["{http://vaemendis.net/opds-pse/ns}lastRead"] == "4"


def test_basic_authorization_is_utf8_and_splits_only_first_colon() -> None:
    encoded = base64.b64encode(b"reader@example.com:p:a:ss").decode()

    credentials = parse_basic_authorization(f"Basic {encoded}")

    assert credentials.username == "reader@example.com"
    assert credentials.password == "p:a:ss"
    assert "p:a:ss" not in repr(credentials)


@pytest.mark.parametrize("value", [None, "Bearer token", "Basic !!!", "Basic dXNlcg=="])
def test_invalid_basic_authorization_is_one_named_error(value: str | None) -> None:
    with pytest.raises(OpdsAuthenticationRequired):
        parse_basic_authorization(value)


def test_progression_schema_requires_timezone_uri_and_unit_interval() -> None:
    valid = OpdsProgressionDocument.model_validate(
        {
            "modified": "2026-08-03T10:00:00+08:00",
            "device": {"id": "urn:uuid:device-1", "name": "Panels"},
            "progression": 0.5,
            "references": ["pages/4"],
        }
    )
    assert valid.to_dto().references == ("pages/4",)

    for changed in (
        {"modified": "2026-08-03T10:00:00"},
        {"device": {"id": "device-1", "name": "Panels"}},
        {"progression": 1.1},
    ):
        payload = {
            "modified": "2026-08-03T10:00:00Z",
            "device": {"id": "urn:uuid:device-1", "name": "Panels"},
            "progression": 0.5,
        }
        payload.update(changed)
        with pytest.raises(ValidationError):
            OpdsProgressionDocument.model_validate(payload)
