"""Publication security policy shared by adapters and delivery."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicationSecurityProfile:
    identifier: str
    content_security_policy: str


WEB_SECURITY_PROFILE = PublicationSecurityProfile(
    identifier="web-v2",
    content_security_policy=(
        "default-src 'none'; base-uri 'none'; connect-src 'none'; "
        "form-action 'none'; frame-src 'none'; child-src 'none'; "
        "object-src 'none'; script-src blob:; "
        "style-src 'self' blob: 'unsafe-inline'; "
        "img-src 'self' blob: data:; font-src 'self' blob: data:; "
        "media-src 'self' blob: data:"
    ),
)
