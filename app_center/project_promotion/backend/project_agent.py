"""One native Agent session, with read-only command tools and verified citations."""
import json

from django.conf import settings
from apps.enterprise.services import enforce_member_token_quota, record_usage
from core.llm.application import GenerationError, engine_failure
from core.llm.factory import build_agent_engine


def run_project_agent(task, *, working_directory, instruction, content, tools, handlers, progress, check, on_activity=None):
    check()
    enforce_member_token_quota(task.organization, task.owner)
    engine = build_agent_engine(working_directory=working_directory)
    if engine.adapter_name != 'codex' or settings.CODEX_TRANSPORT != 'app-server':
        raise GenerationError('项目自主探索需要支持原生工具与只读沙箱的 Codex app-server 引擎。', code='unsupported_agent')
    mode = task.snapshot['request'].get('exploration_mode', 'overview')
    timeout_seconds = (settings.PROJECT_PROMOTION_DEEP_TIMEOUT_SECONDS if mode == 'deep'
                       else settings.PROJECT_PROMOTION_OVERVIEW_TIMEOUT_SECONDS)

    def cancelled():
        try:
            check()
        except InterruptedError:
            return True
        return False

    def event(kind, payload):
        check()
        if on_activity:
            on_activity(kind, payload)
        elif kind == 'tool.started':
            progress('Agent 正在自主查找和阅读项目文件')
        elif kind == 'tool.completed':
            progress('Agent 正在整理文件内容与素材依据')

    try:
        if on_activity:
            on_activity('session.started', {})
        response = engine.complete([
            {'role': 'system', 'content': instruction},
            {'role': 'user', 'content': json.dumps(content, ensure_ascii=False)},
        ], permission_mode='default', read_only_paths=[working_directory],
            read_only_full_disk=settings.PROJECT_PROMOTION_ALLOW_FULL_DISK_READ,
            dynamic_tools=tools, tool_handlers=handlers, on_event=event, cancelled=cancelled,
            final_response_only=True, timeout_seconds=timeout_seconds)
    except InterruptedError:
        raise
    except TimeoutError:
        check()
        label = '指定方向深挖' if mode == 'deep' else '全面概览'
        raise GenerationError(f'项目{label}超时（本次时限 {timeout_seconds} 秒）。请查看执行过程，确认是否仍在读取资料或等待模型；'
            '可重试，或由管理员调整此模式的探索时限。已保存素材不受影响。', code='timeout') from None
    except GenerationError:
        raise
    except Exception as exc:
        check()
        detail = str(exc).lower()
        if 'requires effective `:root` read access' in detail or 'cannot enforce split filesystem read restrictions' in detail:
            raise GenerationError('当前 Windows 沙箱不支持仅项目目录可读。请使用支持目录隔离的执行环境，或由部署管理员明确授权全盘只读模式后重试。',
                code='sandbox_read_scope_unsupported') from None
        if any(term in detail for term in ('cryptunprotectdata', 'failed to prepare fs sandbox',
                                           'cannot enforce split filesystem read restrictions')):
            raise GenerationError('系统只读沙箱无法启动。请修复执行机器的 Codex 沙箱配置后重试；Windows 沙箱凭据异常需在执行账号下重新初始化。已保存内容不受影响。',
                code='sandbox_unavailable') from None
        if 'permissions profile' in detail or ('unknown' in detail and 'permissions' in detail):
            raise GenerationError('当前 Codex app-server 不支持受限只读权限配置，请更新执行引擎后重试。',
                code='unsupported_agent') from None
        raise engine_failure(exc) from None
    check()
    success = response.success and not response.input_request
    record_usage(organization=task.organization, user=task.owner, resource_type='promotion_generation',
        resource_id=task.pk, usage=response.usage.model_dump(), provider=engine.adapter_name,
        model=response.model, status='success' if success else 'error')
    if not success:
        raise engine_failure(response.error, requires_input=bool(response.input_request))
    return response.thread_id
