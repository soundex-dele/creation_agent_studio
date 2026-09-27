"""Translate interactive requests without changing their identity or scope."""
import json

from jsonschema import ValidationError, SchemaError
from jsonschema.validators import validator_for

APPROVALS = {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}
QUESTIONS = {"item/tool/requestUserInput", "tool/requestUserInput"}
PERMISSIONS = "item/permissions/requestApproval"
ELICITATION = "mcpServer/elicitation/request"
INTERACTIVE_METHODS = APPROVALS | QUESTIONS | {PERMISSIONS, ELICITATION}


def approval_choices(params):
    return params.get("availableDecisions") or ["accept", "acceptForSession", "decline", "cancel"]


def input_request(message):
    from .codex import _normalize_user_input_questions
    method, params = message["method"], message.get("params") or {}
    request = {"codex_request": message, "input_kind": "answer", "kind": "question"}
    if method in QUESTIONS:
        questions = _normalize_user_input_questions(params.get("questions"))
        request.update(questions[0], questions=questions)
    elif method in APPROVALS or method == PERMISSIONS:
        labels = {"accept": "允许本次", "acceptForSession": "本会话允许", "decline": "拒绝", "cancel": "取消此操作"}
        choices = approval_choices(params) if method in APPROVALS else ["accept", "acceptForSession", "decline"]
        options = []
        for index, decision in enumerate(choices):
            label = labels.get(decision, decision) if isinstance(decision, str) else "应用指定规则"
            options.append({"label": label, "value": decision if isinstance(decision, str) else f"rule:{index}",
                            "description": json.dumps(decision, ensure_ascii=False) if isinstance(decision, dict) else ""})
        network = params.get("networkApprovalContext")
        request.update(input_kind="permission", kind="permission", header="网络权限确认" if network else "Codex 权限确认",
                       question=params.get("reason") or params.get("command") or "是否允许以下操作？",
                       options=options, details={key: params[key] for key in
                           ("command", "cwd", "grantRoot", "permissions", "additionalPermissions", "networkApprovalContext")
                           if params.get(key) is not None})
    elif method == ELICITATION:
        request.update(header=str(params.get("serverName") or "工具") + " · 需要补充信息",
                       question=params.get("message") or "请完成工具请求", options=[],
                       form_schema=params.get("requestedSchema"), url=params.get("url"),
                       elicitation=True)
    else:
        raise ValueError("Unsupported interactive request")
    return request


def response_for_request(message, command):
    method, params = message["method"], message.get("params") or {}
    payload = command.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("回复必须是对象")
    if method in QUESTIONS:
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            questions = params.get("questions") or []
            if len(questions) != 1:
                raise ValueError("请回答全部问题")
            answers = {questions[0]["id"]: {"answers": payload.get("selections") or [payload.get("text", "")]}}
        result = {}
        for question in params.get("questions") or []:
            entry = answers.get(question["id"], {})
            value = entry.get("answers") if isinstance(entry, dict) else None
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError("请回答全部问题")
            result[question["id"]] = {"answers": value}
        return {"answers": result}
    if method in APPROVALS or method == PERMISSIONS:
        choices = approval_choices(params) if method in APPROVALS else ["accept", "acceptForSession", "decline"]
        selections = payload.get("selections") or []
        if not isinstance(selections, list) or any(not isinstance(value, str) for value in selections):
            raise ValueError("审批选项格式不正确")
        selected = (selections or [""])[0]
        if command.get("type") == "deny_permission":
            decision = "cancel" if selected == "cancel" else "decline"
        elif selected in choices and isinstance(selected, str):
            decision = selected
        else:
            try:
                if not selected.startswith("rule:"):
                    raise ValueError()
                index = int(str(selected).removeprefix("rule:"))
                if index < 0:
                    raise ValueError()
                decision = choices[index]
                if not isinstance(decision, dict):
                    raise ValueError()
            except (ValueError, TypeError, IndexError):
                raise ValueError("请选择本次请求提供的审批选项") from None
        if method in APPROVALS:
            if decision not in choices:
                raise ValueError("当前请求不接受此审批选项")
            return {"decision": decision}
        # Never take permissions from the client: grant only the displayed request.
        return {"permissions": params.get("permissions", {}) if decision in {"accept", "acceptForSession"} else {},
                "scope": "session" if decision == "acceptForSession" else "turn"}
    if method == ELICITATION:
        action = payload.get("action", "accept")
        if not isinstance(action, str) or action not in {"accept", "decline", "cancel"}:
            raise ValueError("无效的工具请求操作")
        content = payload.get("content") if action == "accept" else None
        if action == "accept" and params.get("requestedSchema"):
            schema = params["requestedSchema"]
            # Disallow remote reference resolution from an external tool schema.
            if any(key in json.dumps(schema) for key in ('"$ref"', '"$dynamicRef"', '"$recursiveRef"')):
                raise ValueError("此表单包含不支持的引用，请取消请求")
            try:
                validator = validator_for(schema)
                validator.check_schema(schema)
                validator(schema).validate(content)
            except (ValidationError, SchemaError) as exc:
                raise ValueError("表单内容不符合工具要求，请检查字段类型和必填项") from exc
        return {"action": action, "content": content, "_meta": None}
    raise ValueError("Unsupported interactive request")
