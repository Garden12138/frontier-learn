"""Parse public semantic HTML or pasted text, without executing page scripts or code."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from pydantic import ValidationError

from app.core.errors import Problem
from app.domain.conversation_types import (
    ConversationDocument,
    ConversationMessage,
    ConversationPart,
)


def part_chunks(kind: str, text: str) -> list[ConversationPart]:
    return [
        ConversationPart(kind=kind, text=text[start : start + 4000])
        for start in range(0, len(text), 4000)
        if text[start : start + 4000].strip()
    ]


def document(
    title: str, values: list[tuple[str, list[ConversationPart]]], warnings: list[str]
) -> ConversationDocument:
    try:
        return ConversationDocument(
            title=title[:200] or "导入对话",
            warnings=warnings[:5],
            messages=[
                ConversationMessage(id=f"m{index}", role=role, parts=parts)
                for index, (role, parts) in enumerate(values)
                if parts
            ],
        )
    except ValidationError:
        raise Problem(
            400, "CONVERSATION_LIMIT", "对话为空、过短或超出解析限制，请只粘贴需要学习的片段。"
        ) from None


def parse_pasted(text: str) -> ConversationDocument:
    if not 20 <= len(text) <= 30000:
        raise Problem(400, "CONVERSATION_LIMIT", "请提供 20–30,000 字符的对话材料。")
    roles = {
        "user": "USER",
        "human": "USER",
        "用户": "USER",
        "你": "USER",
        "assistant": "ASSISTANT",
        "chatgpt": "ASSISTANT",
        "助手": "ASSISTANT",
        "ai": "ASSISTANT",
    }
    messages: list[tuple[str, list[ConversationPart]]] = []
    role = "UNKNOWN"
    parts: list[ConversationPart] = []
    lines: list[str] = []
    fence = ""
    warnings = ["手工材料的角色标签由提交内容提供，作者身份和回答真实性未经核验。"]

    def flush(kind: str) -> None:
        nonlocal lines
        value = "\n".join(lines)
        parts.extend(part_chunks(kind, value))
        lines = []

    for line in text.splitlines():
        if fence:
            if re.fullmatch(r"\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                flush("CODE")
                fence = ""
            else:
                lines.append(line)
            continue
        opener = re.fullmatch(r"\s*(`{3,}|~{3,})[^`~]*", line)
        if opener:
            flush("TEXT")
            fence = opener[1]
            continue
        marker = re.fullmatch(
            r"\s*(?:#{1,3}\s+)?(User|Human|用户|你|Assistant|ChatGPT|助手|AI)\s*[:：]\s*(.*)",
            line,
            re.IGNORECASE,
        )
        if marker:
            flush("TEXT")
            if parts:
                messages.append((role, parts))
                parts = []
            role = roles[marker[1].casefold()]
            if marker[2]:
                lines.append(marker[2])
        else:
            lines.append(line)
    flush("CODE" if fence else "TEXT")
    if parts:
        messages.append((role, parts))
    if fence:
        warnings.append("代码围栏未闭合，剩余内容保留为代码文本，未执行。")
    if any(value[0] == "UNKNOWN" for value in messages):
        warnings.append("部分材料未标明 USER / ASSISTANT，保留 UNKNOWN，请按原对话核对。")
    return document("手工导入对话", messages, warnings)


@dataclass
class Frame:
    tag: str
    ignored: bool
    message: int | None
    code: bool


@dataclass
class ParsedMessage:
    role: str
    # One entry per transition between text and code; never raw markup.
    segments: list[tuple[str, list[str]]] = field(default_factory=list)


class ShareHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[Frame] = []
        self.messages: list[ParsedMessage] = []
        self.title: list[str] = []
        self.nodes = 0
        self.characters = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > 20000 or len(self.stack) >= 256:
            raise Problem(400, "SHARE_STRUCTURE_LIMIT", "分享页结构超出解析限制，请粘贴必要片段。")
        attributes = dict(attrs)
        parent = self.stack[-1] if self.stack else None
        ignored = (
            bool(parent and parent.ignored)
            or tag
            in {
                "script",
                "style",
                "noscript",
                "template",
                "iframe",
                "object",
                "embed",
                "svg",
                "nav",
                "header",
                "footer",
                "form",
                "input",
                "textarea",
                "button",
                "select",
            }
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
        )
        style = re.sub(r"\s+", "", attributes.get("style") or "").lower()
        classes = (attributes.get("class") or "").split()
        ignored = (
            ignored
            or "display:none" in style
            or "visibility:hidden" in style
            or any(value in {"hidden", "sr-only"} for value in classes)
        )
        message = parent.message if parent else None
        role = attributes.get("data-message-author-role")
        if role in {"user", "assistant"} and not ignored:
            if message is not None:
                raise Problem(
                    400, "SHARE_STRUCTURE_UNSUPPORTED", "对话节点嵌套不明确，请手工粘贴。"
                )
            if len(self.messages) >= 40:
                raise Problem(400, "CONVERSATION_LIMIT", "对话超过 40 条消息，请粘贴必要片段。")
            message = len(self.messages)
            self.messages.append(ParsedMessage(role.upper()))
        code = tag in {"pre", "code"} or bool(parent and parent.code)
        frame = Frame(tag, ignored, message, code)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(frame)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "pre"}:
            self.append(frame, "\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        before = len(self.stack)
        self.handle_starttag(tag, attrs)
        if len(self.stack) > before:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        index = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].tag == tag), None
        )
        if index is not None:
            frame = self.stack[index]
            if tag in {"p", "div", "li", "pre", "h1", "h2", "h3"}:
                self.append(frame, "\n")
            del self.stack[index:]

    def append(self, frame: Frame, value: str) -> None:
        if frame.ignored or frame.message is None:
            return
        self.characters += len(value)
        if self.characters > 32000:
            raise Problem(400, "CONVERSATION_LIMIT", "正文超过 30,000 字符预算，请粘贴必要片段。")
        message = self.messages[frame.message]
        kind = "CODE" if frame.code else "TEXT"
        if not message.segments or message.segments[-1][0] != kind:
            if len(message.segments) >= 30:
                raise Problem(400, "CONVERSATION_LIMIT", "消息分段过多，请缩小材料。")
            message.segments.append((kind, []))
        message.segments[-1][1].append(value)

    def handle_data(self, data: str) -> None:
        if not self.stack:
            return
        frame = self.stack[-1]
        if frame.tag == "title" and not frame.ignored and sum(map(len, self.title)) < 200:
            self.title.append(data[:200])
        self.append(frame, data)


def parse_share_html(html: str) -> ConversationDocument:
    if len(html.encode()) > 1_000_000:
        raise Problem(413, "RESPONSE_TOO_LARGE", "分享页超过导入大小限制。")
    parser = ShareHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except (RecursionError, ValueError):
        raise Problem(400, "SHARE_PARSE_FAILED", "分享页暂时无法解析，请手工粘贴。") from None
    values: list[tuple[str, list[ConversationPart]]] = []
    for message in parser.messages:
        parts = [
            part for kind, pieces in message.segments for part in part_chunks(kind, "".join(pieces))
        ]
        if parts:
            values.append((message.role, parts))
    if not values:
        raise Problem(
            400, "SHARE_PARSE_FAILED", "未找到可读取的公开对话；不会执行页面脚本，请手工粘贴。"
        )
    return document(
        "".join(parser.title).strip() or "ChatGPT 分享对话",
        values,
        ["AI 回答、代码和角色标签均是待核实材料，不证明事实或掌握；附件未导入。"],
    )
