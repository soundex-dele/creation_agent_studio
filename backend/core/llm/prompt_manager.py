"""
Prompt Manager
"""
from typing import List, Dict


class PromptManager:
    """提示词管理器"""

    SYSTEM_PROMPT = """你是一个通用 AI 助手，可以帮助用户分析问题、整理信息、制定计划并完成任务。

请先理解用户的目标、背景和约束；信息不足时提出必要问题，并用清晰、专业的方式给出可执行的结果。"""

    @staticmethod
    def build_messages(
        history: List[Dict[str, str]],
        user_message: str,
        system_prompt: str = None
    ) -> List[Dict[str, str]]:
        """构建消息列表"""
        messages = []

        # 添加系统提示
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({"role": "system", "content": PromptManager.SYSTEM_PROMPT})

        # 添加历史消息
        for msg in history[-10:]:  # 只保留最近10条消息
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_message})

        return messages
