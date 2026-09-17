from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter
from django.utils import timezone


class ScheduleValidationError(ValueError):
    pass


def get_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(timezone_name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError("请输入有效的 IANA 时区。") from exc


def validate_cron(expression: str) -> str:
    value = " ".join(str(expression or "").split())
    if len(value.split()) != 5:
        raise ScheduleValidationError("Cron 必须包含五个字段。")
    try:
        croniter(value, timezone.now())
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise ScheduleValidationError("Cron 表达式无效。") from exc
    return value


def _aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, datetime_timezone.utc)
    return value


def next_fire_time(*, kind: str, expression: str, run_at, timezone_name: str, after=None):
    after = _aware(after or timezone.now())
    zone = get_zone(timezone_name)
    if kind == "once":
        if run_at is None:
            raise ScheduleValidationError("单次任务必须设置执行时间。")
        return _aware(run_at).astimezone(datetime_timezone.utc)
    if kind != "cron":
        raise ScheduleValidationError("请选择单次或周期调度。")
    expression = validate_cron(expression)
    local_after = after.astimezone(zone)
    return croniter(expression, local_after).get_next(datetime).astimezone(
        datetime_timezone.utc
    )


def latest_due_time(automation, now=None):
    now = _aware(now or timezone.now())
    if automation.schedule_kind == "once":
        return _aware(automation.run_at or automation.next_run_at)
    expression = validate_cron(automation.schedule)
    zone = get_zone(automation.timezone)
    return croniter(expression, now.astimezone(zone)).get_prev(datetime).astimezone(
        datetime_timezone.utc
    )


def advance_after_due(automation, now=None):
    now = _aware(now or timezone.now())
    if automation.schedule_kind == "once":
        return None
    return next_fire_time(
        kind="cron",
        expression=automation.schedule,
        run_at=None,
        timezone_name=automation.timezone,
        after=now,
    )


def preview_schedule(*, kind, expression="", run_at=None, timezone_name, count=5, after=None):
    cursor = _aware(after or timezone.now())
    if kind == "once":
        return [next_fire_time(
            kind=kind,
            expression=expression,
            run_at=run_at,
            timezone_name=timezone_name,
            after=cursor,
        )]
    results = []
    for _ in range(count):
        cursor = next_fire_time(
            kind=kind,
            expression=expression,
            run_at=run_at,
            timezone_name=timezone_name,
            after=cursor,
        )
        results.append(cursor)
    return results
