"""The bounded title/author result shared by manual and queued recognition."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetadataIdentity:
    title: str | None
    author: str | None
    needs_review: bool
    reason: str

    def payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "author": self.author,
            "needsReview": self.needs_review,
            "reason": self.reason,
        }

    def candidate(self) -> dict[str, object]:
        return {
            "id": "ai-identity",
            "source": "ai",
            "title": self.title,
            "author": self.author,
            "confidence": 0.0,
            "tags": [],
            "identity": self.payload(),
        }
