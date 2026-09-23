"""Deterministic text controls, dispatched under the incoming-message transaction."""
from datetime import timedelta
import re

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.agents.models import Agent
from apps.conversations.execution import ensure_supervisor_access
from core.resource_access import accessible_resources
from .entry_commands import ENTRY_MENU, dispatch_entries

PAGE_SIZE = 10
SHORTCUT = re.compile(r"菜单[ \t]*([0-9]+)")
MAIN_MENU = """微信助手 · 功能菜单

1. 切换智能体
2. 新建会话
3. 查看最近任务
4. 查看当前状态
5. 使用帮助
6. 添加想法
7. 添加待办
8. 查询想法
9. 查询待办
0. 返回聊天

请回复编号；发送普通文字可退出菜单并继续聊天。
也可直接发送“菜单6”，换行后填写想法，一行一条。
菜单 5 分钟内有效，回复 0 或“退出菜单”返回聊天。"""
CHAT_HINT = "\n已返回聊天，发送“菜单”可再次打开。"
TASK_LABELS = {
    "queued": "排队中", "running": "执行中", "waiting_input": "等待操作",
    "waiting_children": "等待子任务", "succeeded": "已完成", "failed": "失败",
    "cancelling": "取消中", "cancelled": "已取消",
}
STATUS_LABELS = {
    "unbound": "未绑定", "qr_pending": "正在获取二维码", "wait": "等待扫码",
    "scaned": "已扫码", "need_verifycode": "等待验证码", "connecting": "正在连接",
    "connected": "已连接", "reconnecting": "正在重连", "expired": "登录已失效",
    "blocked": "需要检查配置",
}


def clear_menu(binding):
    binding.menu_state = ""
    binding.menu_expires_at = None
    binding.menu_data = {}
    binding.save(update_fields=["menu_state", "menu_expires_at", "menu_data"])


def save_menu(binding):
    binding.save(update_fields=["menu_state", "menu_expires_at", "menu_data"])


def agent_options(binding):
    agents = accessible_resources(
        Agent.objects.filter(Q(organization=binding.organization) | Q(organization__isnull=True), is_active=True),
        binding.user, operation="run",
    ).order_by("name", "id")
    options = []
    for agent in agents:
        try:
            ensure_supervisor_access(agent, binding.user)
        except (ValidationError, PermissionDenied, DjangoPermissionDenied):
            continue
        options.append({"id": agent.pk, "name": " ".join(agent.name.split())[:60]})
    return options


def agent_page(binding):
    options, page = binding.menu_data["agents"], binding.menu_data["page"]
    start = page * PAGE_SIZE
    lines = [f"选择智能体（第 {page + 1}/{(len(options) + PAGE_SIZE - 1) // PAGE_SIZE} 页）"]
    for number, agent in enumerate(options[start:start + PAGE_SIZE], 1):
        suffix = "（当前）" if agent["id"] == binding.agent_id else ""
        lines.append(f"{number}. {agent['name']}{suffix}")
    lines.append("回复本页编号选择；发送“上一页”或“下一页”翻页，0 返回聊天。")
    return "\n".join(lines)


def recent_tasks(binding):
    from .services import conversation_hint

    tasks = list(binding.incoming.filter(run__isnull=False).select_related("run").order_by("-created_at", "-id")[:5])
    if not tasks:
        return "还没有微信发起的任务。"
    lines = ["最近微信任务（最多 5 条）"]
    for number, task in enumerate(tasks, 1):
        summary = " ".join(task.text.split())
        summary = summary[:80] + ("…" if len(summary) > 80 else "")
        timestamp = timezone.localtime(task.created_at).strftime("%m-%d %H:%M")
        lines.append(f"\n{number}. {summary}\n{timestamp} · {TASK_LABELS.get(task.run.status, '未知状态')}")
        if task.conversation_id:
            lines.append(conversation_hint(task))
    return "\n".join(lines)


def dispatch_menu(binding, incoming):
    """Return True when a control consumed the message; never create model Runs."""
    from .services import BUSY, configure, enqueue, is_busy

    text = incoming.text.strip()

    def reply(body, *, done=False):
        if done:
            clear_menu(binding)
            body += CHAT_HINT
        enqueue(incoming, "menu", body)
        return True

    def select_agent(value):
        if value == "0":
            return reply("菜单已关闭。", done=True)
        options = binding.menu_data["agents"]
        page = binding.menu_data["page"]
        if value in ("上一页", "下一页"):
            target = page + (1 if value == "下一页" else -1)
            if not 0 <= target * PAGE_SIZE < len(options):
                return reply("已经是第一页或最后一页。\n" + agent_page(binding))
            binding.menu_data["page"] = target
            save_menu(binding)
            return reply(agent_page(binding))
        choices = {str(i): agent for i, agent in enumerate(options[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], 1)}
        if value in choices:
            if is_busy(binding):
                return reply(BUSY, done=True)
            try:
                updated = configure(binding, choices[value]["id"])
            except (ValidationError, PermissionDenied, DjangoPermissionDenied):
                return reply("该智能体已不可用或当前无权使用，请重新打开菜单选择。", done=True)
            return reply(f"当前智能体：{updated.agent.name}。", done=True)
        return False

    first_line, *remaining = text.splitlines()
    shortcut = SHORTCUT.fullmatch(first_line.strip())
    inline_input = ""
    if shortcut:
        text = shortcut.group(1)
        if text not in {str(i) for i in range(10)}:
            return reply("快捷菜单编号无效，请使用菜单0～菜单9，发送“菜单”查看功能列表。")
        # Always target the main menu, independent of a previous submenu/capture.
        # The rest is data for this action, never another command or chat turn.
        inline_input = "\n".join(remaining).strip()
        binding.menu_state = "main"
        binding.menu_expires_at = timezone.now() + timedelta(minutes=5)
        binding.menu_data = {}
        save_menu(binding)

    if text in ("菜单", "/menu"):
        binding.menu_state = "main"
        binding.menu_expires_at = timezone.now() + timedelta(minutes=5)
        binding.menu_data = {}
        save_menu(binding)
        return reply(MAIN_MENU)
    if text == "退出菜单":
        return reply("菜单已关闭。", done=True)
    if not shortcut and dispatch_entries(binding, incoming):
        return True
    if not binding.menu_state:
        return False
    if text == "0":
        return reply("菜单已关闭。", done=True)
    numeric = text.isdecimal()
    if not binding.menu_expires_at or binding.menu_expires_at <= timezone.now():
        clear_menu(binding)
        if numeric or text in ("上一页", "下一页"):
            return reply("菜单已过期，请重新发送“菜单”。")
        return False

    if binding.menu_state == "agents":
        if select_agent(text):
            return True
    elif text in ("1", "2"):
        if is_busy(binding):
            return reply(BUSY, done=True)
        if text == "1":
            options = agent_options(binding)
            if not options:
                return reply("当前没有可用的智能体，请在项目中检查配置。", done=True)
            binding.menu_state = "agents"
            binding.menu_data = {"agents": options, "page": 0}
            save_menu(binding)
            if inline_input:
                return select_agent(inline_input) or reply("智能体选择无效，请回复本页编号。\n" + agent_page(binding))
            return reply(agent_page(binding))
        try:
            updated = configure(binding, reset=True)
        except (ValidationError, PermissionDenied, DjangoPermissionDenied):
            return reply("当前智能体不可用，请通过菜单切换智能体。", done=True)
        return reply(f"已新建会话 {updated.conversation_id}，历史会话已保留。", done=True)
    elif text == "3":
        return reply(recent_tasks(binding), done=True)
    elif text == "4":
        return reply("\n".join([
            f"当前智能体：{binding.agent.name if binding.agent else '未选择'}",
            f"会话编号：{binding.conversation_id or '尚未创建'}",
            f"未完成任务：{'有' if is_busy(binding) else '无'}",
            f"连接状态：{STATUS_LABELS.get(binding.status, '未知状态')}",
        ]), done=True)
    elif text in ENTRY_MENU:
        command = ENTRY_MENU[text]
        if text in ("6", "7") and inline_input:
            command += "\n" + inline_input
        return dispatch_entries(binding, incoming, command)
    elif text == "5":
        return reply(
            "发送“菜单”或 /menu 打开功能菜单，5 分钟内回复编号选择。\n"
            "快捷用法：发送“菜单1”直接选择智能体，换行可填写智能体编号；发送“菜单6”或“菜单7”，换行后每行填写一条内容。\n"
            "无需输入的菜单忽略附带内容；查询翻页仍使用“查询想法 2”或“查询待办 2”。\n"
            "完成操作后自动恢复聊天；回复 0 或“退出菜单”也可返回聊天。\n"
            "菜单内发送普通文字会退出菜单并继续聊天；未打开菜单时数字也作为聊天内容。\n"
            "任务运行期间可查询状态，结束后才能切换智能体或新建会话。\n"
            "可直接发送“添加想法”或“添加待办”，下一条消息每个非空行保存一条；也可在指令后换行附上内容。\n"
            "发送“查询想法”或“查询待办”查看，每页 10 条；例如“查询想法 2”查看第 2 页，待办默认仅显示未完成事项。\n"
            "任务执行中的补充信息、待办与审批仍需进入项目会话处理。", done=True,
        )
    if numeric:
        return reply("编号无效，请按当前菜单重新选择，或回复 0 返回聊天。")
    clear_menu(binding)
    return False
