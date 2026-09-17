"""Versioned subject-specific tutoring behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import MistakeRecord, Subject


class SubjectStrategy(Protocol):
    subject: str
    version: int

    def detect_topic(self, problem: str) -> str: ...

    def hint(self, problem: str, level: int, student_thought: str = "") -> dict: ...

    def normalize_answer(self, answer: str) -> str: ...


_REGISTRY: dict[str, SubjectStrategy] = {}


def register_subject_strategy(strategy: SubjectStrategy) -> None:
    if not strategy.subject:
        raise ValueError("Subject strategy must declare a subject")
    _REGISTRY[strategy.subject] = strategy


def unregister_subject_strategy(subject: str) -> None:
    _REGISTRY.pop(subject, None)


def get_subject_strategy(subject: str) -> SubjectStrategy:
    try:
        return _REGISTRY[subject]
    except KeyError as exc:
        raise ValueError(f"学科 {subject!r} 尚未开放。") from exc


def registered_subjects() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


@dataclass(frozen=True)
class MathStrategy:
    subject: str = Subject.MATH
    version: int = 1

    _TOPICS = (
        (("单调", "最值"), "math.function.monotonicity"),
        (("函数", "定义域", "值域"), "math.function.basics"),
        (("导数", "切线"), "math.calculus.derivative"),
        (("数列", "等差", "等比"), "math.sequence.basics"),
        (("向量",), "math.vector.basics"),
        (("直线", "圆", "椭圆", "双曲线", "抛物线"), "math.geometry.analytic"),
        (("概率", "随机", "排列", "组合"), "math.probability.basics"),
        (("三角", "sin", "cos", "tan"), "math.trigonometry.basics"),
    )

    def detect_topic(self, problem: str) -> str:
        lowered = problem.casefold()
        for keywords, code in self._TOPICS:
            if any(keyword.casefold() in lowered for keyword in keywords):
                return code
        return "math.foundation.general"

    def hint(self, problem: str, level: int, student_thought: str = "") -> dict:
        level = max(1, min(int(level), 4))
        topic = self.detect_topic(problem)
        prompts = {
            1: "先圈出已知量和所求量，再判断它们分别属于哪个知识点。你准备从哪条已知条件开始？",
            2: "把题目条件写成数学表达式，优先寻找能直接连接已知量与所求量的定义、公式或性质。",
            3: "按“列出条件 → 选择关系式 → 代入或变形 → 检查适用范围”的顺序逐步书写，不要跳步。",
            4: "现在可以查看完整解析。若智能解析尚未完成，请先保留你的演算过程，并请老师确认最终答案。",
        }
        if student_thought.strip():
            prefix = "我看到了你的思路。先检查这一步是否同时使用了题目给出的全部限制条件。"
        else:
            prefix = "先自己写下一步，不急着看答案。"
        return {
            "subject": self.subject,
            "strategy_version": self.version,
            "knowledge_point": topic,
            "hint_level": level,
            "hint": f"{prefix}{prompts[level]}",
            "solution_revealed": level == 4,
        }

    def normalize_answer(self, answer: str) -> str:
        return "".join(answer.split()).replace("，", ",").casefold()

    @property
    def mistake_causes(self) -> tuple[str, ...]:
        return tuple(value for value, _label in MistakeRecord.Cause.choices)


register_subject_strategy(MathStrategy())
