from __future__ import annotations

from dataclasses import dataclass

from app.modules.library.application.source_node_metadata_recognition import (
    RecognizeSourceNodeMetadata,
    SourceNodeMetadataRecognitionResult,
)


@dataclass
class FakeRecognitionPort:
    call: tuple[str, str, str, str | None] | None = None

    def search(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
    ) -> SourceNodeMetadataRecognitionResult | None:
        self.call = (book_id, source_node_id, provider_id, query)
        return SourceNodeMetadataRecognitionResult(
            source_node_id=source_node_id,
            provider_id=provider_id,
            query=query or "版本",
            message=None,
            candidates=(),
        )


def test_recognition_uses_metadata_provider_port_not_import_pipeline() -> None:
    port = FakeRecognitionPort()
    result = RecognizeSourceNodeMetadata(port).execute(
        book_id="book-1",
        source_node_id="version-node",
        provider_id=" douban ",
        query=" 版本标题 ",
    )

    assert result is not None
    assert port.call == ("book-1", "version-node", "douban", "版本标题")
