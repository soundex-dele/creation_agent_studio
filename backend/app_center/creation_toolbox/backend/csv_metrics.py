from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from django.utils import timezone

from .models import CreationProject, MetricSnapshot, Platform, ProjectStageEvent, Publication


CSV_FIELDS = [
    "project_name", "platform", "platform_name", "account_name", "title",
    "external_post_id", "post_url", "published_at", "observed_on", "impressions",
    "views", "completions", "likes", "comments", "shares", "saves",
    "followers_gained", "conversions", "average_watch_seconds",
]

PLATFORM_ALIASES = {
    "抖音": Platform.DOUYIN,
    "快手": Platform.KUAISHOU,
    "视频号": Platform.WECHAT_CHANNELS,
    "小红书": Platform.XIAOHONGSHU,
    "b站": Platform.BILIBILI,
    "哔哩哔哩": Platform.BILIBILI,
    "其他": Platform.OTHER,
}


def csv_template_text():
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerow({
        "project_name": "示例工程", "platform": "douyin", "account_name": "示例账号",
        "external_post_id": "123456", "post_url": "https://example.com/video/123456",
        "published_at": "2026-09-20 18:00:00", "observed_on": "2026-09-21",
        "impressions": 10000, "views": 8000, "completions": 3200, "likes": 520,
        "comments": 60, "shares": 80, "saves": 100, "followers_gained": 35,
        "conversions": 8, "average_watch_seconds": "18.50",
    })
    return buffer.getvalue()


def _normalize_url(value):
    value = value.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _nonnegative_int(row, field):
    raw = str(row.get(field, "") or "0").strip()
    value = int(raw)
    if value < 0:
        raise ValueError(f"{field} 不能为负数")
    return value


def parse_metrics_csv(uploaded, workspace):
    try:
        content = uploaded.read().decode("utf-8-sig")
    except (AttributeError, UnicodeDecodeError):
        return [], [{"row": 0, "message": "CSV 必须使用 UTF-8 编码。"}]
    reader = csv.DictReader(io.StringIO(content))
    missing = [field for field in CSV_FIELDS if field not in (reader.fieldnames or [])]
    if missing:
        return [], [{"row": 1, "message": f"缺少列：{', '.join(missing)}"}]

    projects = {item.name: item for item in workspace.projects.all()}
    normalized = []
    errors = []
    for number, row in enumerate(reader, start=2):
        try:
            project_name = str(row.get("project_name") or "").strip()
            project = projects.get(project_name)
            if project is None:
                raise ValueError(f"工程不存在：{project_name or '空'}")
            platform_raw = str(row.get("platform") or "").strip()
            platform = PLATFORM_ALIASES.get(platform_raw.lower(), platform_raw)
            if platform not in Platform.values:
                raise ValueError(f"不支持的平台：{platform_raw}")
            platform_name = str(row.get("platform_name") or "").strip()
            if platform == Platform.OTHER and not platform_name:
                raise ValueError("其他平台必须填写 platform_name")
            account_name = str(row.get("account_name") or "").strip()
            if not account_name:
                raise ValueError("account_name 不能为空")
            external_post_id = str(row.get("external_post_id") or "").strip()
            post_url = _normalize_url(str(row.get("post_url") or ""))
            if not external_post_id and not post_url:
                raise ValueError("external_post_id 和 post_url 至少填写一项")
            published_at = datetime.fromisoformat(str(row.get("published_at") or "").strip())
            if timezone.is_naive(published_at):
                published_at = timezone.make_aware(published_at)
            observed_on = date.fromisoformat(str(row.get("observed_on") or "").strip())
            average_watch = str(row.get("average_watch_seconds") or "").strip()
            if average_watch:
                try:
                    average_watch = Decimal(average_watch)
                except InvalidOperation as exc:
                    raise ValueError("average_watch_seconds 必须是数字") from exc
                if average_watch < 0:
                    raise ValueError("average_watch_seconds 不能为负数")
            values = {field: _nonnegative_int(row, field) for field in CSV_FIELDS[9:18]}
            normalized.append({
                "row": number, "project": project, "project_name": project_name,
                "platform": platform,
                "platform_name": platform_name,
                "account_name": account_name, "title": str(row.get("title") or "").strip(),
                "external_post_id": external_post_id, "post_url": post_url,
                "published_at": published_at, "observed_on": observed_on,
                "average_watch_seconds": average_watch or None, **values,
            })
        except (ValueError, TypeError) as exc:
            errors.append({"row": number, "message": str(exc)})
    return normalized, errors


@transaction.atomic
def commit_metrics_rows(rows, *, workspace, organization, user):
    publication_ids = set()
    snapshot_ids = set()
    for row in rows:
        lookup = {
            "workspace": workspace,
            "platform": row["platform"],
            "account_name": row["account_name"],
        }
        if row["external_post_id"]:
            lookup["external_post_id"] = row["external_post_id"]
        else:
            lookup["post_url"] = row["post_url"]
        publication = Publication.objects.filter(**lookup).first()
        defaults = {
            "project": row["project"], "platform_name": row["platform_name"],
            "title": row["title"], "external_post_id": row["external_post_id"],
            "post_url": row["post_url"], "published_at": row["published_at"],
        }
        if publication is None:
            publication = Publication.objects.create(
                organization=organization, workspace=workspace, account_name=row["account_name"],
                created_by=user, **defaults, **{"platform": row["platform"]},
            )
        else:
            for key, value in defaults.items():
                setattr(publication, key, value)
            publication.save(update_fields=[*defaults.keys(), "updated_at"])
        publication_ids.add(publication.id)
        project = row["project"]
        if project.stage not in {
            CreationProject.Stage.PUBLISHED, CreationProject.Stage.RETROSPECTIVE
        }:
            previous = project.stage
            project.stage = CreationProject.Stage.PUBLISHED
            project.stage_changed_at = timezone.now()
            project.save(update_fields=["stage", "stage_changed_at", "updated_at"])
            ProjectStageEvent.objects.create(
                organization=organization,
                project=project,
                from_stage=previous,
                to_stage=CreationProject.Stage.PUBLISHED,
                note="CSV 导入首条发布记录后自动更新",
                changed_by=user,
            )
        snapshot_defaults = {
            key: row[key] for key in (
                "impressions", "views", "completions", "likes", "comments", "shares",
                "saves", "followers_gained", "conversions", "average_watch_seconds",
            )
        }
        snapshot, _created = MetricSnapshot.objects.update_or_create(
            publication=publication,
            observed_on=row["observed_on"],
            defaults={
                "organization": organization, "created_by": user, **snapshot_defaults,
            },
        )
        snapshot_ids.add(snapshot.id)
    return {"publication_count": len(publication_ids), "snapshot_count": len(snapshot_ids)}
