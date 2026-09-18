from __future__ import annotations

import os
from functools import lru_cache

from .models import Copywriting


COPY_TEMPLATES = {
    Copywriting.Style.FUNNY: """开场：你以为“{topic}”只是件普通小事？\n\n反转来了——真正让人上头的，往往不是结果，而是过程里那些意想不到的瞬间。把最有戏剧性的细节放在前 3 秒，再用一个反差把观众留住。\n\n结尾：如果是你，会怎么选？评论区告诉我。""",
    Copywriting.Style.EMOTIONAL: """有些时刻，只有经历过“{topic}”的人才懂。\n\n我们总以为成长是变得无坚不摧，后来才明白，真正的成长，是允许自己慢一点，也愿意再次出发。\n\n愿你在每一次选择里，都更靠近真正想成为的自己。""",
    Copywriting.Style.INFORMATIVE: """关于“{topic}”，记住这 3 点：\n\n1. 先明确目标，避免一开始就堆砌信息；\n2. 把复杂步骤拆成可执行的小动作；\n3. 用结果复盘流程，保留有效方法。\n\n收藏这条，下次需要时直接照着做。""",
    Copywriting.Style.SCIENCE: """为什么“{topic}”值得认真了解？\n\n先看原理：一个现象通常由多个条件共同作用，单一结论很容易忽略边界。理解关键变量、对照条件和可验证证据，才能避免被表象误导。\n\n关注我，用更简单的方式看懂复杂知识。""",
    Copywriting.Style.MARKETING: """如果你正在关注“{topic}”，这条内容能帮你少走弯路。\n\n核心价值不是堆功能，而是更快完成目标：步骤更少、反馈更清晰、结果更稳定。现在开始体验，把时间留给真正重要的创作。\n\n点击了解详情，立即开启高效工作流。""",
}


def generate_copywriting(topic: str, style: str) -> str:
    return COPY_TEMPLATES[style].format(topic=topic)


@lru_cache(maxsize=2)
def _whisper_model(model_name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_audio(path: str, language: str) -> str:
    model_name = os.environ.get("CREATION_TOOLBOX_WHISPER_MODEL", "tiny")
    model = _whisper_model(model_name)
    normalized_language = (language or "zh").split("-", 1)[0]
    segments, _info = model.transcribe(path, language=normalized_language)
    return "".join(segment.text for segment in segments).strip()

