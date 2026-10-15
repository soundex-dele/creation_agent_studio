"""Account reports use frozen analysis evidence, never the current work library."""

import html
import re
from urllib.parse import quote, urlsplit

from .provider import work_web_url


LABELS = {"observation": "观察事实", "inference": "初步推测", "suggestion": "创作建议"}


def text(value):
    value = "未获取" if value is None or value == "" else str(value)
    value = html.escape(value, quote=False).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", value).replace("\n", "  \n")


def link(value, label):
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            return "未获取有效来源链接"
    except ValueError:
        return "未获取有效来源链接"
    return f"[{label}](<{quote(value, safe=':/?=&%+@,;#')}>)"


def account_report_filename(account, task):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', account.name or '未命名账号')[:80]
    return f"{name}-账号分析-{task.created_at.date().isoformat()}-{str(task.pk)[:8]}.md"


def account_analysis_markdown(account, task):
    output, frozen = task.output, task.input
    stats = output.get("statistics") or {}
    claims = output.get("claims") or []
    evidence = {str(row["id"]): row for row in frozen.get("evidence", [])}
    breakdowns = {str(row["id"]): row for row in frozen.get("breakdowns", [])}
    refs = list(dict.fromkeys(ref for claim in claims for ref in claim.get("refs", [])))
    numbers = {ref: i + 1 for i, ref in enumerate(refs)}
    lines = [f"# {text(account.name or '未命名账号')} · 对标账号分析", "",
             f"- 账号主页：{link(account.source_url, '打开账号主页')}",
             f"- 分析任务 ID：{text(task.pk)}",
             f"- 任务创建时间：{text(task.created_at.isoformat())}",
             f"- 采集批次 ID：{text(frozen.get('batch_id'))}", "",
             "> 分析仅覆盖本次采集样本，不代表账号全部作品或未来表现。标题语义判断属于初步推测。",
             "> 统计、结论及出处使用分析任务保存的快照；账号名称与主页链接使用导出时的当前信息。", "",
             "## 样本统计", ""]
    for key, label in [("sample_count", "本次样本"), ("observed_days", "样本跨度（天）"),
                       ("posts_per_week", "样本内每周发布")]:
        lines.append(f"- {label}：{text(stats.get(key))}")
    lines += ["", "### 时长分布", ""]
    for key, label in [("under_30", "不足 30 秒"), ("30_to_60", "30 秒至不足 60 秒"),
                       ("60_to_180", "60 秒至不足 180 秒"), ("180_plus", "180 秒及以上")]:
        lines.append(f"- {label}：{text((stats.get('duration_buckets') or {}).get(key))}")
    lines += ["", "## 分析结论", ""]
    for index, claim in enumerate(claims, 1):
        lines += [f"### {index}. {LABELS.get(claim.get('type'), '分析结论')}", "", text(claim.get("text")), "",
                  "出处：" + ("、".join(f"[出处 {numbers[ref]}](#source-{numbers[ref]})" for ref in dict.fromkeys(claim.get("refs", []))) or "未提供"), ""]
    lines += ["## 出处", ""]

    def work_lines(work):
        return [f"- 作品标题：{text(work.get('title'))}", f"- 作品 ID：{text(work.get('id'))}",
                f"- 来源：{link(work_web_url(work), '打开来源作品')}",
                *[f"- {label}：{text(work.get(key))}" for key, label in
                  [("published_at", "发布时间"), ("duration", "时长（秒）"), ("likes", "点赞"),
                   ("comments", "评论"), ("collects", "收藏"), ("shares", "分享")]]]

    for ref in refs:
        lines += [f'<a id="source-{numbers[ref]}"></a>', "", f"### 出处 {numbers[ref]}", "",
                  f"- 引用 ID：{text(ref)}"]
        if ref in evidence:
            lines += work_lines(evidence[ref])
        elif ref in breakdowns:
            source = breakdowns[ref]
            work_id = str(source.get("work_id") or "")
            lines += ["- 来源类型：视频拆解快照", f"- 关联作品 ID：{text(work_id)}"]
            if work_id in evidence:
                lines += work_lines(evidence[work_id])
            else:
                lines += ["- 关联作品详情：未保存在本次样本快照中。"]
            lines += ["", "保存的拆解结论：", ""]
            for claim in source.get("claims", []):
                lines += [f"- {LABELS.get(claim.get('type'), '分析结论')}：{text(claim.get('text'))}",
                          f"  原始出处 ID：{text('、'.join(claim.get('refs', [])))}"]
        else:
            lines += ["- 出处缺失：本次分析快照中未找到此引用，已保留原始 ID。"]
        lines.append("")
    return "\n".join(lines)
