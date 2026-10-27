import bisect
import re
from dataclasses import dataclass

from app.core.errors import Problem
from app.core.security import MAX_INPUT_BYTES


@dataclass(frozen=True)
class ParsedChunk:
    text: str
    start: int
    end: int
    line_start: int
    line_end: int
    content_type: str


def parse_text(content: bytes, *, code: bool = False) -> tuple[str, list[ParsedChunk]]:
    if len(content) > MAX_INPUT_BYTES:
        raise Problem(413, "FILE_TOO_LARGE", "文件超过大小限制。")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise Problem(400, "UNSUPPORTED_ENCODING", "文件不是受支持的 UTF-8 文本。") from None
    if "\0" in text:
        raise Problem(400, "BINARY_CONTENT", "文件包含二进制内容，未抽取知识证据。")
    starts = [0] + [match.end() for match in re.finditer("\n", text)]
    chunks: list[ParsedChunk] = []
    block_start = 0
    offset = 0
    fenced = code

    def emit(start: int, end: int, content_type: str) -> None:
        for segment in range(start, end, 4000):
            finish = min(segment + 4000, end)
            part = text[segment:finish]
            if not part.strip():
                continue
            chunks.append(
                ParsedChunk(
                    part,
                    segment,
                    finish,
                    bisect.bisect_right(starts, segment),
                    bisect.bisect_right(starts, max(segment, finish - 1)),
                    content_type,
                )
            )
            if len(chunks) > 1000:
                raise Problem(413, "CHUNK_LIMIT", "文件段落数量超过解析上限。")

    for line in text.splitlines(keepends=True):
        is_fence = bool(re.match(r"^\s*(```|~~~)", line)) and not code
        if is_fence:
            emit(block_start, offset, "CODE" if fenced else "TEXT")
            block_start = offset
            fenced = not fenced
        elif not fenced and (not line.strip() or re.match(r"^#{1,6}\s", line)):
            heading_only = bool(re.fullmatch(r"#{1,6}\s+[^\r\n]+[\r\n]*", text[block_start:offset]))
            if line.strip() or not heading_only:
                emit(block_start, offset, "TEXT")
                block_start = offset
        offset += len(line)
        if is_fence and not fenced:
            emit(block_start, offset, "CODE")
            block_start = offset
    emit(block_start, len(text), "CODE" if fenced else "TEXT")
    return text, chunks
