"""One validated structure renders to web, Markdown and the document editor."""
import re

KINDS = {"report": "研究报告", "comparison": "观点对照", "writing_pack": "写作资料包"}
SECTIONS = {
    "report": ["摘要", "关键结论", "主题分析", "分歧与局限"],
    "comparison": ["议题与各方观点", "共识", "分歧", "未涉及与局限"],
    "writing_pack": ["可用角度", "写作提纲", "事实与数据卡片", "原文摘录", "待核实问题"],
}
LABELS = {"fact": "事实", "quote": "摘录", "inference": "推断", "gap": "待核实", "suggestion": "建议"}


def validate_output(value, evidence, kind, sources=None):
    if not isinstance(value, dict) or not isinstance(value.get("sections"), list):
        raise ValueError("成果结构不完整。")
    if [s.get("heading") if isinstance(s, dict) else None for s in value["sections"]] != SECTIONS[kind]:
        raise ValueError("成果章节不完整。")
    used, sections = [], []
    source_titles = {s["source_id"]: s["title"] for s in sources or []}
    compared = set()
    for section in value["sections"]:
        items = section.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 40:
            raise ValueError("成果条目不完整。")
        clean = []
        for item in items:
            if not isinstance(item, dict) or item.get("type") not in LABELS:
                raise ValueError("事实与推断必须明确区分。")
            permitted = {"原文摘录": {"quote", "gap"}, "事实与数据卡片": {"fact", "gap"},
                         "关键结论": {"fact", "inference", "gap"}}
            if section["heading"] in permitted and item["type"] not in permitted[section["heading"]]:
                raise ValueError(f"{section['heading']}中的内容类型不符合要求。")
            text = item.get("text")
            refs = item.get("evidence_ids", [])
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError("成果内容无效。")
            if not isinstance(refs, list) or any(not isinstance(r, str) or r not in evidence for r in refs):
                raise ValueError("引用包含不属于本次资料的证据。")
            if item["type"] in {"fact", "quote", "inference"} and not refs:
                raise ValueError("关键结论缺少原文依据。")
            if item["type"] == "quote" and not all(text.strip() in evidence[r]["quote"] for r in refs):
                raise ValueError("原文摘录与资料不符。")
            for ref in refs:
                if ref not in used:
                    used.append(ref)
            cleaned = {"type": item["type"], "text": text.strip(), "evidence_ids": list(dict.fromkeys(refs))}
            if kind == "comparison" and section["heading"] == SECTIONS[kind][0] and sources is not None:
                source_id = item.get("source_id")
                if not isinstance(source_id, str) or source_id not in source_titles:
                    raise ValueError("观点对照缺少资料身份。")
                if any(evidence[r]["source_id"] != source_id for r in refs):
                    raise ValueError("观点引用与该行资料不符。")
                if not refs and item["type"] != "gap":
                    raise ValueError("未涉及的资料必须标明证据缺口。")
                compared.add(source_id)
                cleaned.update(source_id=source_id, source_title=source_titles[source_id])
            clean.append(cleaned)
        sections.append({"heading": section["heading"], "items": clean})
    if kind == "comparison" and sources is not None and compared != set(source_titles):
        raise ValueError("观点对照必须列出每份资料的观点或未涉及。")
    citations = [{**evidence[key], "id": key, "number": index} for index, key in enumerate(used, 1)]
    return {"sections": sections, "citations": citations}


def location(citation):
    if citation.get("page_number"):
        return f"第 {citation['page_number']} 页"
    parts = list(citation.get("section_path") or [])
    if citation.get("paragraph_number"):
        parts.append(f"第 {citation['paragraph_number']} 段")
    return " / ".join(parts) or f"片段 {citation.get('position', 0) + 1}"


def md_escape(text):
    # Source/model text is literal prose, never arbitrary Markdown links or HTML.
    return re.sub(r"([\\`*_{}\[\]<>#!|])", r"\\\1", str(text)).replace("\r", "")


def result_url(origin, project, result, citation=None):
    url = f"{origin.rstrip('/')}/applications/{project.application_id}/research-assistant?project={project.id}&result={result.id}"
    return url + (f"&citation={citation}" if citation else "")


def markdown(output, origin, project, result):
    refs = {c["id"]: c for c in output["citations"]}
    lines = [f"# {md_escape(output['title'])}", ""]
    for section in output["sections"]:
        lines += [f"## {section['heading']}", ""]
        for item in section["items"]:
            links = " ".join(f"[{refs[r]['number']}]({result_url(origin, project, result, r)})" for r in item["evidence_ids"])
            source_label = f"{item['source_title']}：" if item.get("source_title") else ""
            lines += [f"- **{LABELS[item['type']]}**：{md_escape(source_label + item['text'])} {links}", ""]
    lines += ["## 参考资料", ""]
    for citation in output["citations"]:
        lines += [f"{citation['number']}. {md_escape(citation['title'])} · {md_escape(location(citation))}",
                  f"   > {md_escape(citation['quote']).replace(chr(10), chr(10) + '   > ')}", ""]
    lines += ["引用已核对原文位置；引用有效不等同于事实已经独立验证。", "",
              f"[回到研究项目]({result_url(origin, project, result)})"]
    return "\n".join(lines)


def document_content(output, origin, project, result):
    def text(value, marks=None):
        return {"type": "text", "text": value, **({"marks": marks} if marks else {})}
    def paragraph(value):
        return {"type": "paragraph", "content": [text(value)]}
    refs = {c["id"]: c for c in output["citations"]}
    nodes = [{"type": "heading", "attrs": {"level": 1}, "content": [text(output["title"])]}]
    for section in output["sections"]:
        nodes.append({"type": "heading", "attrs": {"level": 2}, "content": [text(section["heading"])]})
        for item in section["items"]:
            source_label = f"{item['source_title']}：" if item.get("source_title") else ""
            p = paragraph(f"{LABELS[item['type']]}：{source_label}{item['text']}")
            p["content"].extend(text(f" [{refs[r]['number']}]", [{"type": "link", "attrs": {
                "href": result_url(origin, project, result, r)}}]) for r in item["evidence_ids"])
            nodes.append(p)
    nodes.append({"type": "heading", "attrs": {"level": 2}, "content": [text("参考资料")]})
    for citation in output["citations"]:
        nodes.append(paragraph(f"[{citation['number']}] {citation['title']} · {location(citation)}\n{citation['quote']}"))
    nodes.append(paragraph("引用已核对原文位置；引用有效不等同于事实已经独立验证。"))
    return {"type": "doc", "content": nodes}


def editor_markdown(node):
    """Snapshot supported editor structures without fetching links or embedding HTML."""
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    children = node.get("content", [])
    values = [editor_markdown(child) for child in children]
    if kind == "heading":
        return "#" * node.get("attrs", {}).get("level", 1) + " " + "".join(values) + "\n\n"
    if kind == "tableRow":
        return " | ".join(value.strip() for value in values) + "\n"
    if kind in {"paragraph", "codeBlock"}:
        return "".join(values) + "\n\n"
    if kind == "hardBreak":
        return "\n"
    return "".join(values)
