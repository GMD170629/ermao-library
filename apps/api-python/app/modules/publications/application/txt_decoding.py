"""TXT decoding policy shared by bounded import inspection and publication readers."""

import codecs
from dataclasses import dataclass

from app.core.exception_diagnostics import capture_exception


@dataclass(frozen=True, slots=True)
class DecodedTxt:
    text: str
    encoding: str


def decode_txt_bytes(content: bytes, *, final: bool = True) -> DecodedTxt:
    """Preserve readable text; an unfinished inspection sample is not file EOF."""
    if content.startswith(codecs.BOM_UTF8):
        encoding, codec, payload = "utf-8-sig", "utf-8", content[3:]
    elif content.startswith(codecs.BOM_UTF16_LE):
        encoding, codec, payload = "utf-16-le", "utf-16-le", content[2:]
    elif content.startswith(codecs.BOM_UTF16_BE):
        encoding, codec, payload = "utf-16-be", "utf-16-be", content[2:]
    else:
        try:
            text = codecs.getincrementaldecoder("utf-8")(errors="strict").decode(
                content, final=final,
            )
            return DecodedTxt(text, "utf-8")
        except UnicodeDecodeError as error:
            capture_exception(error, level="debug")
        encoding, codec, payload = "gb18030", "gb18030", content
    text = codecs.getincrementaldecoder(codec)(errors="replace").decode(
        payload, final=final,
    )
    return DecodedTxt(text, encoding)
