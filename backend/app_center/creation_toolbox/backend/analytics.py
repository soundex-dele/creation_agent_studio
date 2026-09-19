from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import quantiles

from django.db.models import Count, Min
from django.utils import timezone

from .models import CreationProject, Platform, Publication


def _rate(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def _snapshot_payload(snapshot):
    engagement = snapshot.likes + snapshot.comments + snapshot.shares + snapshot.saves
    return {
        "impressions": snapshot.impressions,
        "views": snapshot.views,
        "completions": snapshot.completions,
        "likes": snapshot.likes,
        "comments": snapshot.comments,
        "shares": snapshot.shares,
        "saves": snapshot.saves,
        "followers_gained": snapshot.followers_gained,
        "conversions": snapshot.conversions,
        "play_rate": _rate(snapshot.views, snapshot.impressions),
        "completion_rate": _rate(snapshot.completions, snapshot.views),
        "engagement_rate": _rate(engagement, snapshot.views),
        "follow_rate": _rate(snapshot.followers_gained, snapshot.views),
        "conversion_rate": _rate(snapshot.conversions, snapshot.views),
    }


def build_analytics(workspace, *, start: date | None = None, end: date | None = None,
                    platform: str = ""):
    publications = Publication.objects.filter(workspace=workspace).select_related(
        "project", "project__topic"
    ).prefetch_related("metric_snapshots")
    if start:
        publications = publications.filter(published_at__date__gte=start)
    if end:
        publications = publications.filter(published_at__date__lte=end)
    if platform:
        publications = publications.filter(platform=platform)

    totals = defaultdict(int)
    platform_rows = defaultdict(lambda: defaultdict(int))
    trend_rows = defaultdict(lambda: defaultdict(int))
    topic_rows = defaultdict(lambda: defaultdict(int))
    engagement_by_platform = defaultdict(list)
    insights = []
    publication_count = 0
    missing_metrics = 0

    for publication in publications:
        publication_count += 1
        snapshots = list(publication.metric_snapshots.order_by("observed_on", "created_at"))
        eligible = [item for item in snapshots if not end or item.observed_on <= end]
        latest = eligible[-1] if eligible else None
        if latest is None:
            missing_metrics += 1
            if publication.published_at <= timezone.now() - timedelta(days=1):
                insights.append({
                    "kind": "missing_metrics",
                    "level": "warning",
                    "title": f"“{publication.project.name}”尚未补充发布数据",
                    "detail": "作品发布已超过 24 小时，但没有指标快照。",
                    "resource_id": str(publication.id),
                })
            continue

        payload = _snapshot_payload(latest)
        for key in (
            "impressions", "views", "completions", "likes", "comments", "shares",
            "saves", "followers_gained", "conversions",
        ):
            totals[key] += payload[key]
            platform_rows[publication.platform][key] += payload[key]
            if publication.project.topic_id:
                topic_rows[str(publication.project.topic_id)][key] += payload[key]
        platform_rows[publication.platform]["publication_count"] += 1
        if payload["engagement_rate"] is not None:
            engagement_by_platform[publication.platform].append(
                (payload["engagement_rate"], publication)
            )

        previous = None
        for snapshot in snapshots:
            if end and snapshot.observed_on > end:
                break
            if previous is not None:
                fields = ("impressions", "views", "completions", "likes", "comments",
                          "shares", "saves", "followers_gained", "conversions")
                deltas = {field: getattr(snapshot, field) - getattr(previous, field) for field in fields}
                if any(value < 0 for value in deltas.values()):
                    insights.append({
                        "kind": "metric_rollback",
                        "level": "warning",
                        "title": f"“{publication.project.name}”存在累计指标回退",
                        "detail": f"{snapshot.observed_on.isoformat()} 的累计数据小于前一快照，请核对导入值。",
                        "resource_id": str(publication.id),
                    })
                if not start or snapshot.observed_on >= start:
                    for field, value in deltas.items():
                        trend_rows[snapshot.observed_on][field] += max(value, 0)
            previous = snapshot

    totals_payload = dict(totals)
    engagement_total = totals["likes"] + totals["comments"] + totals["shares"] + totals["saves"]
    totals_payload.update({
        "publication_count": publication_count,
        "missing_metrics_count": missing_metrics,
        "play_rate": _rate(totals["views"], totals["impressions"]),
        "completion_rate": _rate(totals["completions"], totals["views"]),
        "engagement_rate": _rate(engagement_total, totals["views"]),
        "follow_rate": _rate(totals["followers_gained"], totals["views"]),
        "conversion_rate": _rate(totals["conversions"], totals["views"]),
    })

    for platform_key, rows in engagement_by_platform.items():
        if len(rows) < 4:
            continue
        values = [value for value, _publication in rows]
        lower, _median, upper = quantiles(values, n=4, method="inclusive")
        for value, publication in rows:
            if value <= lower or value >= upper:
                insights.append({
                    "kind": "performance_quartile",
                    "level": "success" if value >= upper else "info",
                    "title": f"“{publication.project.name}”互动率位于同平台{'前' if value >= upper else '后'}四分位",
                    "detail": f"互动率 {value:.2%}，比较范围为当前筛选内的同平台作品。",
                    "resource_id": str(publication.id),
                })

    today = timezone.localdate()
    overdue = CreationProject.objects.filter(
        workspace=workspace,
        archived_at__isnull=True,
        planned_publish_at__date__lt=today,
    ).exclude(stage__in=[CreationProject.Stage.PUBLISHED, CreationProject.Stage.RETROSPECTIVE])
    for project in overdue[:20]:
        insights.append({
            "kind": "overdue_project", "level": "warning",
            "title": f"“{project.name}”已超过计划发布日期",
            "detail": f"当前阶段：{project.get_stage_display()}。",
            "resource_id": str(project.id),
        })

    stalled_before = timezone.now() - timedelta(days=14)
    stalled = CreationProject.objects.filter(
        workspace=workspace,
        archived_at__isnull=True,
        stage_changed_at__lt=stalled_before,
    ).exclude(stage__in=[CreationProject.Stage.PUBLISHED, CreationProject.Stage.RETROSPECTIVE])
    for project in stalled[:20]:
        days = (timezone.now() - project.stage_changed_at).days
        insights.append({
            "kind": "stage_duration",
            "level": "info",
            "title": f"“{project.name}”在{project.get_stage_display()}阶段停留较久",
            "detail": f"已停留 {days} 天，超过当前透明规则阈值 14 天。",
            "resource_id": str(project.id),
        })

    stages = dict(CreationProject.Stage.choices)
    stage_distribution = [
        {"stage": row["stage"], "label": stages[row["stage"]], "count": row["count"]}
        for row in CreationProject.objects.filter(
            workspace=workspace, archived_at__isnull=True
        ).values("stage").annotate(count=Count("id")).order_by("stage")
    ]

    topics = workspace.topics.annotate(
        project_count=Count("projects", distinct=True),
        first_project_at=Min("projects__created_at"),
    )
    topic_count = topics.count()
    adopted_count = topics.filter(project_count__gt=0).count()
    topic_performance = []
    for topic in topics.filter(project_count__gt=0):
        data = topic_rows.get(str(topic.id), {})
        topic_performance.append({
            "topic_id": str(topic.id), "title": topic.title,
            "project_count": topic.project_count,
            "first_project_hours": round(
                (topic.first_project_at - topic.created_at).total_seconds() / 3600, 2
            ) if topic.first_project_at else None,
            "views": data.get("views", 0),
            "engagement_rate": _rate(
                data.get("likes", 0) + data.get("comments", 0)
                + data.get("shares", 0) + data.get("saves", 0),
                data.get("views", 0),
            ),
            "tags": topic.tags,
            "source_name": topic.source_name,
        })
    topic_performance.sort(key=lambda item: item["views"], reverse=True)

    tag_rows = defaultdict(lambda: {"topic_count": 0, "project_count": 0, "views": 0,
                                    "likes": 0, "comments": 0, "shares": 0, "saves": 0})
    source_rows = defaultdict(lambda: {"topic_count": 0, "project_count": 0, "views": 0,
                                       "likes": 0, "comments": 0, "shares": 0, "saves": 0})
    for topic in topics:
        performance = topic_rows.get(str(topic.id), {})
        groups = [(tag_rows, tag) for tag in topic.tags]
        groups.append((source_rows, topic.source_name or "未记录来源"))
        for rows, key in groups:
            rows[key]["topic_count"] += 1
            rows[key]["project_count"] += topic.project_count
            for metric in ("views", "likes", "comments", "shares", "saves"):
                rows[key][metric] += performance.get(metric, 0)

    def grouped_performance(rows, label_key):
        result = []
        for label, values in rows.items():
            result.append({
                label_key: label,
                "topic_count": values["topic_count"],
                "project_count": values["project_count"],
                "views": values["views"],
                "engagement_rate": _rate(
                    values["likes"] + values["comments"] + values["shares"] + values["saves"],
                    values["views"],
                ),
            })
        return sorted(result, key=lambda item: item["views"], reverse=True)[:20]

    platform_labels = dict(Platform.choices)
    return {
        "summary": totals_payload,
        "stage_distribution": stage_distribution,
        "trend": [
            {"date": day.isoformat(), **values}
            for day, values in sorted(trend_rows.items())
        ],
        "platforms": [
            {
                "platform": key,
                "label": platform_labels.get(key, key),
                **values,
                "engagement_rate": _rate(
                    values["likes"] + values["comments"] + values["shares"] + values["saves"],
                    values["views"],
                ),
            }
            for key, values in platform_rows.items()
        ],
        "topics": {
            "total": topic_count,
            "adopted": adopted_count,
            "adoption_rate": _rate(adopted_count, topic_count),
            "performance": topic_performance[:20],
            "tag_performance": grouped_performance(tag_rows, "tag"),
            "source_performance": grouped_performance(source_rows, "source_name"),
        },
        "insights": insights[:50],
        "formulas": {
            "play_rate": "播放 / 曝光",
            "completion_rate": "完播 / 播放",
            "engagement_rate": "(点赞 + 评论 + 分享 + 收藏) / 播放",
            "follow_rate": "涨粉 / 播放",
            "conversion_rate": "转化 / 播放",
        },
    }
