from __future__ import annotations

import base64
import binascii
import hashlib
import html
import mimetypes
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ebooklib import epub
from lxml import etree


INTERNAL_CONVERTER_VERSION = "shuku-internal-epub/2"
MAX_TXT_CHAPTER_CHARS = 80_000
MAX_CHAPTERS = 2_000

_CHAPTER_PATTERNS = (
    re.compile(
        r"^\s*(?:第[零〇一二三四五六七八九十百千万两\d]{1,12}[章节卷回部篇集]|"
        r"序章|序言|楔子|引子|前言|后记|尾声|番外(?:\s*[零〇一二三四五六七八九十百千万两\d]+)?)"
        r"(?:[\s:：、.．-]+.{0,50})?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:chapter|book|part|volume)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"(?:[\s:：.\-]+.{0,50})?\s*$",
        re.IGNORECASE,
    ),
)

_STYLESHEET = """
body { line-height: 1.75; margin: 5%; }
h1, h2, h3 { line-height: 1.35; }
p { margin: 0.65em 0; text-indent: 2em; }
img { height: auto; max-width: 100%; }
blockquote { margin: 1em 1.5em; }
.text-author { text-align: right; }
.empty-line { min-height: 1em; }
""".strip()


class InternalConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class InternalConversionResult:
    title: str
    author: str | None
    language: str
    chapter_count: int
    resource_count: int


def convert_txt_to_epub(source: Path, output: Path, *, encoding: str) -> InternalConversionResult:
    try:
        raw_text = source.read_text(encoding=encoding, errors="strict")
    except (OSError, UnicodeError) as exc:
        raise InternalConversionError("TXT 内容读取失败") from exc
    normalized = _normalize_text(raw_text)
    if not normalized.strip():
        raise InternalConversionError("TXT 文件为空")

    chapters = _split_txt_chapters(normalized)
    title = _clean_title(source.stem) or "未命名图书"
    book = _new_book(title=title, author=None, language="zh-CN")
    _add_stylesheet(book)
    epub_chapters: list[epub.EpubHtml] = []
    for index, (chapter_title, chapter_text) in enumerate(chapters, start=1):
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=f"chapters/chapter-{index:04d}.xhtml",
            lang="zh-CN",
        )
        chapter.content = _txt_chapter_xhtml(chapter_title, chapter_text)
        chapter.add_link(href="../styles/main.css", rel="stylesheet", type="text/css")
        book.add_item(chapter)
        epub_chapters.append(chapter)
    _finish_book(book, epub_chapters, output)
    return InternalConversionResult(title, None, "zh-CN", len(epub_chapters), 0)


def convert_fb2_to_epub(source: Path, output: Path) -> InternalConversionResult:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, remove_comments=True, huge_tree=True)
    try:
        root = etree.parse(str(source), parser).getroot()
    except (OSError, etree.XMLSyntaxError) as exc:
        raise InternalConversionError("FB2 文件结构无效") from exc
    if _local_name(root) != "FictionBook":
        raise InternalConversionError("FB2 文件结构无效")

    title_info = _first_descendant(root, "title-info")
    title = _element_text(_first_descendant(title_info, "book-title")) if title_info is not None else ""
    title = _clean_title(title) or _clean_title(source.stem) or "未命名图书"
    language = _element_text(_first_descendant(title_info, "lang")) if title_info is not None else ""
    language = language.strip() or "zh-CN"
    author = _fb2_author(title_info)

    book = _new_book(title=title, author=author, language=language)
    _add_stylesheet(book)
    image_hrefs, resource_count = _add_fb2_images(book, root, title_info)
    chapter_nodes = _fb2_chapter_nodes(root)
    if not chapter_nodes:
        raise InternalConversionError("FB2 不包含可阅读正文")
    internal_links = _fb2_internal_links(chapter_nodes)

    epub_chapters: list[epub.EpubHtml] = []
    used_titles: dict[str, int] = {}
    for index, (fallback_title, node) in enumerate(chapter_nodes, start=1):
        chapter_title = _fb2_node_title(node) or fallback_title or f"第 {index} 章"
        chapter_title = _unique_title(chapter_title, used_titles)
        content = _render_fb2_children(node, image_hrefs, internal_links)
        if not _has_readable_html(content):
            continue
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=f"chapters/chapter-{index:04d}.xhtml",
            lang=language,
        )
        chapter.content = f"<h1>{html.escape(chapter_title)}</h1>{content}"
        chapter.add_link(href="../styles/main.css", rel="stylesheet", type="text/css")
        book.add_item(chapter)
        epub_chapters.append(chapter)
    if not epub_chapters:
        raise InternalConversionError("FB2 不包含可阅读正文")
    _finish_book(book, epub_chapters, output)
    return InternalConversionResult(title, author, language, len(epub_chapters), resource_count)


def _new_book(*, title: str, author: str | None, language: str) -> epub.EpubBook:
    book = epub.EpubBook()
    identity = hashlib.sha256(f"{title}\0{author or ''}\0{language}".encode("utf-8")).hexdigest()
    book.set_identifier(f"shuku-{identity[:32]}")
    book.set_title(title)
    book.set_language(language)
    if author:
        book.add_author(author)
    return book


def _add_stylesheet(book: epub.EpubBook) -> epub.EpubItem:
    style = epub.EpubItem(
        uid="style-main",
        file_name="styles/main.css",
        media_type="text/css",
        content=_STYLESHEET.encode("utf-8"),
    )
    book.add_item(style)
    return style


def _finish_book(book: epub.EpubBook, chapters: list[epub.EpubHtml], output: Path) -> None:
    book.toc = tuple(chapters)
    # EPUB 3 navigation belongs in the manifest but not in the linear reading
    # order. Keeping it out also prevents large tables of contents from being
    # paginated and included in location generation.
    book.spine = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        epub.write_epub(str(output), book, {"raise_exceptions": True})
    except Exception as exc:  # EbookLib exposes backend-specific write errors.
        raise InternalConversionError("EPUB 生成失败") from exc


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    return "".join(character for character in value if character in "\n\t" or unicodedata.category(character) != "Cc")


def _is_chapter_heading(line: str) -> bool:
    candidate = line.strip()
    return bool(candidate and len(candidate) <= 80 and any(pattern.fullmatch(candidate) for pattern in _CHAPTER_PATTERNS))


def _split_txt_chapters(value: str) -> list[tuple[str, str]]:
    lines = value.split("\n")
    headings = [index for index, line in enumerate(lines) if _is_chapter_heading(line)]
    chapters: list[tuple[str, str]] = []
    if headings:
        if any(line.strip() for line in lines[: headings[0]]):
            chapters.extend(_split_long_txt("正文", "\n".join(lines[: headings[0]])))
        for position, start in enumerate(headings):
            end = headings[position + 1] if position + 1 < len(headings) else len(lines)
            title = lines[start].strip()
            chapters.extend(_split_long_txt(title, "\n".join(lines[start + 1 : end])))
    else:
        chapters.extend(_split_long_txt("正文", value))
    if len(chapters) > MAX_CHAPTERS:
        retained = chapters[: MAX_CHAPTERS - 1]
        overflow = chapters[MAX_CHAPTERS - 1 :]
        overflow_text = "\n\n".join(f"{title}\n\n{text}" for title, text in overflow)
        chapters = [*retained, ("其余章节", overflow_text)]
    return chapters or [("正文", value)]


def _split_long_txt(title: str, value: str) -> list[tuple[str, str]]:
    value = value.strip()
    if len(value) <= MAX_TXT_CHAPTER_CHARS:
        return [(title, value)]
    paragraphs = re.split(r"\n\s*\n", value)
    parts: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if current and current_length + len(paragraph) > MAX_TXT_CHAPTER_CHARS:
            parts.append("\n\n".join(current))
            current = []
            current_length = 0
        if len(paragraph) > MAX_TXT_CHAPTER_CHARS:
            if current:
                parts.append("\n\n".join(current))
                current = []
                current_length = 0
            parts.extend(paragraph[offset : offset + MAX_TXT_CHAPTER_CHARS] for offset in range(0, len(paragraph), MAX_TXT_CHAPTER_CHARS))
        else:
            current.append(paragraph)
            current_length += len(paragraph) + 2
    if current:
        parts.append("\n\n".join(current))
    if len(parts) == 1:
        return [(title, parts[0])]
    return [(f"{title}（{index}）", part) for index, part in enumerate(parts, start=1)]


def _txt_chapter_xhtml(title: str, value: str) -> str:
    body = []
    # Chinese novel TXT files conventionally store one natural paragraph per
    # non-empty line. Treating only blank lines as paragraph separators turns
    # an entire chapter into one huge block and makes column pagination costly.
    for line in value.splitlines():
        paragraph = line.strip()
        if paragraph:
            body.append(f"<p>{html.escape(paragraph)}</p>")
    if not body:
        body.append('<p class="empty-line">&#160;</p>')
    return f"<h1>{html.escape(title)}</h1>{''.join(body)}"


def _local_name(node: etree._Element | None) -> str:
    if node is None or not isinstance(node.tag, str):
        return ""
    return etree.QName(node).localname


def _first_descendant(node: etree._Element | None, name: str) -> etree._Element | None:
    if node is None:
        return None
    return next((candidate for candidate in node.iter() if _local_name(candidate) == name), None)


def _element_text(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part.strip()).strip()


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:240]


def _fb2_author(title_info: etree._Element | None) -> str | None:
    author_node = _first_descendant(title_info, "author")
    if author_node is None:
        return None
    parts = []
    for field in ("first-name", "middle-name", "last-name", "nickname"):
        text_value = _element_text(_first_descendant(author_node, field))
        if text_value:
            parts.append(text_value)
    return " ".join(parts)[:240] or None


def _attribute(node: etree._Element, name: str) -> str:
    return next((value for key, value in node.attrib.items() if key == name or key.endswith(f"}}{name}")), "")


def _safe_resource_name(resource_id: str, media_type: str, index: int) -> str:
    suffix = mimetypes.guess_extension(media_type) or ".bin"
    if suffix == ".jpe":
        suffix = ".jpg"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", resource_id).strip(".-") or f"resource-{index:04d}"
    if not Path(stem).suffix:
        stem += suffix
    return stem[:180]


def _add_fb2_images(
    book: epub.EpubBook,
    root: etree._Element,
    title_info: etree._Element | None,
) -> tuple[dict[str, str], int]:
    cover_id = ""
    coverpage = _first_descendant(title_info, "coverpage")
    cover_image = _first_descendant(coverpage, "image")
    if cover_image is not None:
        cover_id = _attribute(cover_image, "href").lstrip("#")
    hrefs: dict[str, str] = {}
    count = 0
    for index, binary in enumerate((node for node in root.iter() if _local_name(node) == "binary"), start=1):
        resource_id = _attribute(binary, "id").strip()
        media_type = _attribute(binary, "content-type").strip().lower() or "application/octet-stream"
        if not resource_id or not media_type.startswith("image/"):
            continue
        try:
            data = base64.b64decode(re.sub(rb"\s+", b"", (binary.text or "").encode("ascii")), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            continue
        if not data:
            continue
        name = _safe_resource_name(resource_id, media_type, index)
        file_name = f"images/{name}"
        if resource_id == cover_id:
            book.set_cover(file_name, data, create_page=False)
        else:
            book.add_item(
                epub.EpubItem(
                    uid=f"image-{index:04d}",
                    file_name=file_name,
                    media_type=media_type,
                    content=data,
                )
            )
        hrefs[resource_id] = f"../{file_name}"
        count += 1
    return hrefs, count


def _fb2_chapter_nodes(root: etree._Element) -> list[tuple[str, etree._Element]]:
    result: list[tuple[str, etree._Element]] = []
    bodies = [node for node in root if _local_name(node) == "body"]
    for body_index, body in enumerate(bodies, start=1):
        body_title = _fb2_node_title(body) or ("正文" if body_index == 1 else f"附录 {body_index - 1}")
        sections = [node for node in body if _local_name(node) == "section"]
        if sections:
            result.extend((body_title, section) for section in sections)
        else:
            result.append((body_title, body))
    return result


def _fb2_node_title(node: etree._Element) -> str:
    title_node = next((child for child in node if _local_name(child) == "title"), None)
    return _clean_title(_element_text(title_node))


def _node_id_attribute(node: etree._Element) -> str:
    raw = _attribute(node, "id")
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw)[:100] if raw else ""


def _safe_link(value: str, internal_links: dict[str, str]) -> str:
    value = value.strip()
    if value.startswith("#"):
        target_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value[1:])[:100]
        return internal_links.get(target_id, f"#{target_id}")
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https", "mailto"} else ""


def _fb2_internal_links(chapter_nodes: list[tuple[str, etree._Element]]) -> dict[str, str]:
    links: dict[str, str] = {}
    for index, (_fallback_title, chapter) in enumerate(chapter_nodes, start=1):
        file_name = f"chapter-{index:04d}.xhtml"
        for node in chapter.iter():
            node_id = _node_id_attribute(node)
            if node_id:
                links.setdefault(node_id, f"{file_name}#{node_id}")
    return links


def _render_fb2_children(
    node: etree._Element,
    image_hrefs: dict[str, str],
    internal_links: dict[str, str],
) -> str:
    pieces: list[str] = []
    if node.text and node.text.strip():
        pieces.append(html.escape(node.text.strip()))
    for child in node:
        pieces.append(_render_fb2_node(child, image_hrefs, internal_links))
        if child.tail and child.tail.strip():
            pieces.append(html.escape(child.tail.strip()))
    return "".join(pieces)


def _render_fb2_node(
    node: etree._Element,
    image_hrefs: dict[str, str],
    internal_links: dict[str, str],
) -> str:
    name = _local_name(node)
    node_id = _node_id_attribute(node)
    id_attr = f' id="{html.escape(node_id, quote=True)}"' if node_id else ""
    if name == "image":
        resource_id = _attribute(node, "href").lstrip("#")
        href = image_hrefs.get(resource_id)
        return f'<p{id_attr}><img src="{html.escape(href, quote=True)}" alt=""/></p>' if href else ""
    if name == "empty-line":
        return f'<p{id_attr} class="empty-line">&#160;</p>'
    if name == "title":
        return f"<h2{id_attr}>{html.escape(_element_text(node))}</h2>"
    if name == "subtitle":
        return f"<h3{id_attr}>{_render_fb2_children(node, image_hrefs, internal_links)}</h3>"
    content = _render_fb2_children(node, image_hrefs, internal_links)
    wrappers = {
        "section": "section",
        "p": "p",
        "emphasis": "em",
        "strong": "strong",
        "strikethrough": "s",
        "code": "code",
        "poem": "blockquote",
        "epigraph": "blockquote",
        "cite": "blockquote",
        "stanza": "div",
        "v": "p",
        "date": "p",
    }
    if name == "text-author":
        return f'<p{id_attr} class="text-author">{content}</p>'
    if name == "a":
        href = _safe_link(_attribute(node, "href"), internal_links)
        return f'<a{id_attr} href="{html.escape(href, quote=True)}">{content}</a>' if href else content
    tag = wrappers.get(name)
    return f"<{tag}{id_attr}>{content}</{tag}>" if tag else content


def _has_readable_html(value: str) -> bool:
    text_value = re.sub(r"<[^>]+>", "", value)
    return bool(html.unescape(text_value).strip() or "<img " in value)


def _unique_title(title: str, used: dict[str, int]) -> str:
    title = _clean_title(title) or "未命名章节"
    used[title] = used.get(title, 0) + 1
    return title if used[title] == 1 else f"{title}（{used[title]}）"
