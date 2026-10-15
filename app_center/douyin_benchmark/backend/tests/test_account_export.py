import copy
from urllib.parse import unquote

import pytest

from ..account_export import account_analysis_markdown, text
from ..models import Account, Work
from .test_douyin import ctx  # noqa: F401


@pytest.fixture
def report(ctx):
    work = Work.objects.create(account=ctx.account, platform_id="7300000000000000001", metadata={"title": "最新作品标题"})
    task = ctx.task
    task.kind = "account"
    task.input = {
        "batch_id": "frozen-batch",
        "evidence": [{"id": str(work.pk), "platform_id": work.platform_id, "title": "分析时的标题",
                      "url": "https://www.douyin.com/video/7300000000000000001", "likes": 0, "comments": None,
                      "collects": 12, "shares": 5, "duration": 60, "published_at": "2026-10-01T08:00:00+08:00"}],
        "breakdowns": [{"id": "breakdown-1", "work_id": str(work.pk), "claims": [
            {"type": "observation", "text": "保存的拆解结论", "refs": ["s1"]}]}],
    }
    task.output = {"statistics": {"sample_count": 1, "observed_days": 0, "posts_per_week": None,
                                  "duration_buckets": {"under_30": 0, "30_to_60": 0, "60_to_180": 1, "180_plus": 0}},
                   "claims": [{"type": "observation", "text": "第一条事实", "refs": [str(work.pk)]},
                              {"type": "inference", "text": "第二条推测", "refs": ["breakdown-1", str(work.pk)]},
                              {"type": "suggestion", "text": "第三条建议", "refs": ["missing-ref"]}]}
    task.save()
    task.run.status = "succeeded"
    task.run.save(update_fields=["status"])
    ctx.account.name = '知识/账号:*'
    ctx.account.save(update_fields=["name"])
    return ctx, task, work, ctx.url + f"/tasks/{task.pk}/download"


def test_download_complete_frozen_report(report):
    ctx, task, work, url = report
    response = ctx.client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown; charset=utf-8"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert f"知识_账号__-账号分析-{task.created_at.date()}-{str(task.pk)[:8]}.md" in unquote(response["Content-Disposition"])
    body = response.content.decode("utf-8")
    for value in ["分析时的标题", "本次样本：1", "样本跨度（天）：0", "样本内每周发布：未获取",
                  "不足 30 秒：0", "点赞：0", "评论：未获取", "保存的拆解结论", "关联作品 ID", "原始出处 ID：s1",
                  "出处缺失", text("missing-ref"), text(task.pk), text("frozen-batch"), "不代表账号全部作品"]:
        assert value in body
    assert body.index("第一条事实") < body.index("第二条推测") < body.index("第三条建议")
    assert body.count('<a id="source-1"></a>') == 1
    assert body.count("[出处 1](#source-1)") == 2
    assert "https://www.douyin.com/" in body
    work.metadata = {"title": "重新采集后的标题", "likes": 99999}
    work.save()
    assert ctx.client.get(url).content == response.content
    assert "重新采集后的标题" not in body


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled"])
def test_reject_unfinished_analysis(report, status):
    ctx, task, _, url = report
    task.run.status = status
    task.run.save(update_fields=["status"])
    assert ctx.client.get(url).status_code == 400


@pytest.mark.parametrize("change", ["kind", "claims", "run"])
def test_reject_non_analysis_or_missing_result(report, change):
    ctx, task, _, url = report
    if change == "kind":
        task.kind = "breakdown"
    elif change == "claims":
        task.output = {"claims": []}
    else:
        task.run = None
    task.save()
    response = ctx.client.get(url)
    assert response.status_code == 400
    assert "已完成且有分析结论" in str(response.data)


def test_download_is_private_and_account_scoped(report):
    ctx, task, _, url = report
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    other = Account.objects.create(application=ctx.app, owner=ctx.owner, organization=ctx.org, source_url="https://www.douyin.com/user/OTHER")
    assert ctx.client.get(f"{ctx.root}/accounts/{other.pk}/tasks/{task.pk}/download").status_code == 404


def test_report_handles_missing_data_and_markdown_characters(report):
    ctx, task, _, _ = report
    task.output.pop("statistics")
    task.input["evidence"][0].update(title="标题 [链接](javascript:alert(1))\n# 新标题 <script>", url="javascript:alert(1)", platform_id="")
    task.input["breakdowns"][0]["work_id"] = "unknown-work"
    task.output["claims"][0]["text"] = "多行内容\n**特殊字符** | <img>"
    original = copy.deepcopy(task.input)
    body = account_analysis_markdown(ctx.account, task)
    assert "本次样本：未获取" in body
    assert "多行内容  \n\\*\\*特殊字符\\*\\* \\| &lt;img&gt;" in body
    assert "\\# 新标题 &lt;script&gt;" in body
    assert "未获取有效来源链接" in body
    assert "关联作品详情：未保存在本次样本快照中" in body
    assert task.input == original
