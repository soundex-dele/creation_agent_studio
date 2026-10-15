"""Small, explicit subset shared with the Tiptap editor. Never store arbitrary HTML."""
import json
from urllib.parse import urlsplit

from rest_framework.exceptions import ValidationError

BLOCKS = {"paragraph", "heading", "bulletList", "orderedList", "blockquote", "codeBlock", "horizontalRule", "table"}
CHILDREN = {
    "doc": BLOCKS,
    "paragraph": {"text", "hardBreak"}, "heading": {"text", "hardBreak"},
    "bulletList": {"listItem"}, "orderedList": {"listItem"},
    "listItem": BLOCKS, "blockquote": BLOCKS, "codeBlock": {"text"},
    "table": {"tableRow"}, "tableRow": {"tableCell", "tableHeader"},
    "tableCell": BLOCKS, "tableHeader": BLOCKS,
    "text": set(), "hardBreak": set(), "horizontalRule": set(),
}


def validate_content(value):
    if not isinstance(value, dict) or value.get("type") != "doc":
        raise ValidationError("正文必须是富文本文档。")
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        byte_length = len(encoded.encode("utf-8"))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValidationError("正文结构无效。")
    if byte_length > 1_000_000:
        raise ValidationError("正文过大，请拆分文档（上限 1 MB）。")
    count = 0

    def visit(node, depth=0):
        nonlocal count
        count += 1
        if depth > 30 or count > 20000 or not isinstance(node, dict):
            raise ValidationError("正文结构过于复杂。")
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in CHILDREN or set(node) - {"type", "attrs", "marks", "content", "text"}:
            raise ValidationError("正文包含不支持的节点。")
        attrs = node.get("attrs", {})
        allowed_attrs = {"heading": {"level"}, "orderedList": {"start", "type"}, "codeBlock": {"language"},
                         "tableCell": {"colspan", "rowspan", "colwidth", "align"}, "tableHeader": {"colspan", "rowspan", "colwidth", "align"}}.get(kind, set())
        if not isinstance(attrs, dict) or set(attrs) - allowed_attrs:
            raise ValidationError("节点属性不受支持。")
        if kind == "heading" and (type(attrs.get("level", 1)) is not int or attrs.get("level", 1) not in range(1, 7)):
            raise ValidationError("标题级别无效。")
        if attrs.get("align") not in (None, "left", "center", "right"):
            raise ValidationError("表格对齐方式无效。")
        if kind == "orderedList" and attrs.get("type") not in (None, "1", "a", "A", "i", "I"):
            raise ValidationError("编号列表样式无效。")
        for key in ("start", "colspan", "rowspan"):
            if key in attrs and (type(attrs[key]) is not int or not 1 <= attrs[key] <= (10000 if key == "start" else 200)):
                raise ValidationError("列表或表格属性无效。")
        if attrs.get("language") is not None and (not isinstance(attrs["language"], str) or len(attrs["language"]) > 50):
            raise ValidationError("代码语言无效。")
        widths = attrs.get("colwidth")
        if widths is not None and (not isinstance(widths, list) or len(widths) > 100 or any(type(w) is not int or not 1 <= w <= 10000 for w in widths)):
            raise ValidationError("表格列宽无效。")
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ValidationError("正文子节点无效。")
        if kind == "doc" and not children:
            raise ValidationError("文档至少需要一个段落。")
        if kind in {"bulletList", "orderedList", "listItem", "blockquote", "table", "tableRow", "tableCell", "tableHeader"} and not children:
            raise ValidationError("结构节点不能为空。")
        if kind == "listItem" and (not isinstance(children[0], dict) or children[0].get("type") != "paragraph"):
            raise ValidationError("列表项必须以段落开始。")
        if kind == "text":
            if not isinstance(node.get("text"), str) or not node["text"]:
                raise ValidationError("文本节点不能为空。")
        elif "text" in node:
            raise ValidationError("非文本节点不能含文本属性。")
        marks = node.get("marks", [])
        if not isinstance(marks, list) or (marks and kind != "text"):
            raise ValidationError("文本格式无效。")
        for mark in marks:
            if not isinstance(mark, dict) or not isinstance(mark.get("type"), str) or mark.get("type") not in {"bold", "italic", "strike", "code", "link"} or set(mark) - {"type", "attrs"}:
                raise ValidationError("不支持的文本格式。")
            ma = mark.get("attrs", {})
            if not isinstance(ma, dict):
                raise ValidationError("文本格式属性无效。")
            if mark["type"] == "link":
                href = ma.get("href", "")
                if set(ma) - {"href", "target", "rel", "class", "title"} or not isinstance(href, str) or len(href) > 2048:
                    raise ValidationError("链接无效。")
                try:
                    scheme = urlsplit(href).scheme.lower()
                except ValueError:
                    scheme = ""
                if scheme not in {"https", "http", "mailto"} or any(ord(c) < 32 for c in href):
                    raise ValidationError("链接仅支持 http、https 和 mailto。")
                mark["attrs"] = {"href": href, "target": "_blank", "rel": "noopener noreferrer nofollow"}
            elif ma:
                raise ValidationError("文本格式属性不受支持。")
        for child in children:
            if not isinstance(child, dict) or not isinstance(child.get("type"), str) or child.get("type") not in CHILDREN[kind]:
                raise ValidationError("节点嵌套无效。")
            visit(child, depth + 1)
        if kind == "table" and len(children) > 200:
            raise ValidationError("表格最多支持 200 行。")
        if kind == "tableRow" and sum(cell.get("attrs", {}).get("colspan", 1) for cell in children) > 50:
            raise ValidationError("表格最多支持 50 列。")
    visit(value)
    return value


def plain_text(node):
    if node["type"] == "text":
        return node["text"]
    if node["type"] in {"hardBreak", "horizontalRule"}:
        return "\n"
    separator = "" if node["type"] in {"paragraph", "heading", "codeBlock"} else "\n"
    return separator.join(plain_text(child) for child in node.get("content", []))
