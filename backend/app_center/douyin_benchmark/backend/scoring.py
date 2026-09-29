from datetime import timedelta
from statistics import median
from django.utils.dateparse import parse_datetime
from django.utils import timezone


def rank(items, captured_at):
    eligible = []
    for item in items:
        try:
            published = parse_datetime(item.get("published_at") or "")
        except (ValueError, TypeError):
            published = None
        valid = published and timezone.is_aware(published) and published <= captured_at - timedelta(hours=48)
        if valid and type(item.get("likes")) is int and item["likes"] >= 0:
            eligible.append(item)
    baseline = median([i["likes"] for i in eligible]) if len(eligible) >= 10 else None
    usable = baseline is not None and baseline > 0
    eligible_ids = {i["platform_id"] for i in eligible}
    results = []
    for item in items:
        ratio = round(item["likes"] / baseline, 3) if usable and item["platform_id"] in eligible_ids else None
        results.append({**item, "ratio": ratio, "outstanding": ratio is not None and ratio >= 3})
    return {"items": results, "sample_size": len(eligible), "median_likes": baseline,
            "explanation": "同账号、同次采集、发布满48小时的有效点赞样本；不表示未来爆款概率。" if usable else "样本不足10条或点赞中位数为零，暂不计算突出倍数。"}
