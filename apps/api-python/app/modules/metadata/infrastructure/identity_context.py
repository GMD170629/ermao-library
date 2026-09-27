"""Read only the selected target's bounded, already-imported identity clues."""

from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.local_metadata_snapshot import decode_observations
from app.models import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)


def identity_clues(
    db: Session, book_id: str, source_node_id: str | None
) -> dict[str, object]:
    book = db.get(LibraryBook, book_id)
    node = (
        db.get(LibrarySourceNode, source_node_id or book.source_node_id)
        if book
        else None
    )
    if node is None:
        return {"fileNames": [], "directories": [], "embeddedMetadata": []}
    rows = db.execute(
        select(
            LibrarySourceNode.relative_path,
            LibraryResourceAsset.local_metadata_candidates,
        )
        .join(
            LibraryResourceAsset,
            LibraryResourceAsset.source_node_id == LibrarySourceNode.id,
        )
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryResourceAsset.resource_id,
        )
        .where(
            LibraryReadableResource.book_id == book_id,
            LibrarySourceNode.library_id == node.library_id,
            (LibrarySourceNode.id == node.id)
            | LibrarySourceNode.relative_path.startswith(
                f"{node.relative_path.rstrip('/')}/", autoescape=True
            ),
        )
        .order_by(LibrarySourceNode.relative_path)
        .limit(8)
    ).all()
    embedded: list[dict[str, object]] = []
    for _, raw in rows:
        for item in decode_observations(raw):
            if item.source == "EMBEDDED":
                embedded.append(
                    {
                        "title": (item.metadata.title or "")[:500],
                        "author": (item.metadata.author or "")[:500],
                    }
                )
    paths = [PurePosixPath(str(path)) for path, _ in rows]
    target = PurePosixPath(node.relative_path)
    directories = [target.name] if node.physical_kind == "DIRECTORY" else []
    directories.extend(
        part for part in target.parent.parts[-2:] if part not in {".", "/"}
    )
    return {
        "fileNames": [path.name[:500] for path in paths] or [node.name[:500]],
        "directories": [part[:500] for part in directories],
        "embeddedMetadata": embedded[:8],
    }
