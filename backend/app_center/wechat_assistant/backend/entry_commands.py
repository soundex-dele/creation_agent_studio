"""WeChat commands backed by the existing private ideas/todos application."""
import re
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from apps.applications.models import Application
from core.resource_access import accessible_resources

ENTRY_MENU = {"6": "添加想法", "7": "添加待办", "8": "查询想法", "9": "查询待办"}
INPUT_STATES = {"add_idea": "添加想法", "add_todo": "添加待办"}
COMMAND = re.compile(r"(添加想法|添加待办|查询想法|查询待办)(?:[\s:：]+(.*))?", re.DOTALL)
PAGE_SIZE = 10
MAX_BATCH = 100


def dispatch_entries(binding, incoming, text=None):
    from .menu import CHAT_HINT, clear_menu, save_menu
    from .services import enqueue

    text = incoming.text.strip() if text is None else text
    match = COMMAND.fullmatch(text)
    collecting = binding.menu_state in INPUT_STATES
    if not match and (not collecting or text == "0"):
        return False

    def reply(body, *, done=True):
        if done:
            clear_menu(binding)
            body += CHAT_HINT
        enqueue(incoming, "entries", body)
        return True

    if match:
        command, payload = match.group(1), (match.group(2) or "").strip()
    else:
        if not binding.menu_expires_at or binding.menu_expires_at <= timezone.now():
            return reply("添加输入已过期，本次内容未保存，请重新发送添加指令和内容。")
        command, payload = INPUT_STATES[binding.menu_state], text

    application = accessible_resources(
        Application.objects.for_organization(binding.organization_id).filter(
            slug="ideas-todos", kind=Application.Kind.CUSTOM, is_active=True,
        ), binding.user, operation="run",
    ).first()
    if application is None:
        return reply("“想法&待办”应用尚未启用或你没有使用权限，请在应用中心检查。")

    from app_center.ideas_todos.backend.serializers import IdeaSerializer, TodoSerializer

    is_idea = command.endswith("想法")
    label = "想法" if is_idea else "待办"
    serializer_class = IdeaSerializer if is_idea else TodoSerializer
    if command.startswith("添加"):
        if not payload:
            binding.menu_state = "add_idea" if is_idea else "add_todo"
            binding.menu_expires_at = timezone.now() + timedelta(minutes=5)
            binding.menu_data = {}
            save_menu(binding)
            return reply(
                f"请发送{label}内容，每个非空行保存一条。每行最多 200 字，一次最多 {MAX_BATCH} 条。\n"
                "请在 5 分钟内发送；回复 0 或“退出菜单”取消。", done=False,
            )
        rows = [line.strip() for line in payload.splitlines() if line.strip()]
        if not rows or len(rows) > MAX_BATCH:
            return reply(f"本次未保存：请提供 1–{MAX_BATCH} 行非空内容。", done=match is not None)
        serializer = serializer_class(data=[{"title": row} for row in rows], many=True)
        if not serializer.is_valid():
            invalid = [str(i) for i, errors in enumerate(serializer.errors, 1) if errors]
            return reply(
                f"本次未保存：第 {'、'.join(invalid)} 条内容不符合要求，每行最多 200 字且不能包含空字符。请修改后重发。",
                done=match is not None,
            )
        # The caller holds the binding/incoming transaction. Validate the entire
        # batch before saving; replaying a handled message cannot insert again.
        serializer.save(application=application, organization_id=binding.organization_id, owner=binding.user)
        return reply(f"已添加 {len(rows)} 条{label}，可发送“查询{label}”查看，也可在“想法&待办”应用中管理。")

    if payload and (not payload.isascii() or not payload.isdecimal() or len(payload) > 9 or int(payload) < 1):
        return reply(f"查询格式：{command}，或“{command} 2”查看第 2 页。")
    page = int(payload) if payload else 1
    entries = serializer_class.Meta.model.objects.for_organization(binding.organization_id).filter(
        application=application, owner=binding.user,
    )
    if not is_idea:
        entries = entries.filter(is_completed=False).order_by(
            F("due_date").asc(nulls_last=True), "-priority", "-created_at", "id",
        )
    total = entries.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        return reply(f"页码超出范围，共 {pages} 页。发送“{command}”返回第 1 页。")
    if not total:
        return reply("还没有想法。" if is_idea else "暂无未完成待办。")
    start = (page - 1) * PAGE_SIZE
    heading = "我的想法" if is_idea else "我的未完成待办"
    lines = [f"{heading}（共 {total} 条，第 {page}/{pages} 页）"]
    for index, entry in enumerate(entries[start:start + PAGE_SIZE], start + 1):
        lines.append(f"{index}. {' '.join(entry.title.split())}")
    if page < pages:
        lines.append(f"发送“{command} {page + 1}”查看下一页。")
    return reply("\n".join(lines))
