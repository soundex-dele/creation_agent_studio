"""Opt-in, real-model smoke evaluation; never runs in the unit test suite.

Run via backend/manage.py shell with the project virtual environment:
from app_center.topic_explorer.evaluate import run; run()
Outputs are review evidence, not automatically scored behavioral guarantees.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from core.llm.factory import build_agent_engine
from core.llm.application import engine_failure
from modules.catalog.guided_prompts import compose_guided_prompt
from .provision import SYSTEM_PROMPT


SCENARIOS = [
    ('vague', {'source': '我想聊 AI，但不知道讲什么，之前选题都很泛。'}, [],
     '应先理解困惑并问1—3个关键问题，不立即批量给标题。'),
    ('complete', dict(source='我的工具能把文章转成可编辑的多页图文，有实际操作录像，没有效率实测数据。',
        platform='xiaohongshu', content_type='carousel', goal='trust', audience='独立创作者',
        direction='从操作体验看可编辑交付', requirements='不写功能清单、不编造效率数字'), [],
     '已知范围不重复问，若足够则给不同切口并注明证据边界。'),
    ('platform_only', {'source': '我想分享工作经验', 'platform': 'wechat'}, [],
     '不再询问发布平台，澄清读者、经历或目的。'),
    ('conflict', dict(source='给完全不懂技术的普通读者讲底层内核代码，必须深入源码，不解释任何术语。',
        platform='moments', content_type='article', audience='完全不懂技术的人'), [],
     '优先澄清受众与表达深度矛盾，不直接覆盖用户选择。'),
    ('unknown', {'source': '我做了一个内容创作工具，但不知道怎么宣传。'}, [
        {'role': 'assistant', 'content': '你最想吸引哪类人？希望他们看完做什么？'},
        {'role': 'user', 'content': '不知道，你帮我想想。'}],
     '给2—3个具体方向帮助比较，不把建议当成已确认偏好。'),
    ('rejection', {'source': '给独立创作者介绍我的排版工具'}, [
        {'role': 'assistant', 'content': '可以从功能介绍、快速上手、开发复盘切入。'},
        {'role': 'user', 'content': '都不是我要的。'},
        {'role': 'assistant', 'content': '那讲AI排版教程或开发心得？'},
        {'role': 'user', 'content': '还是不对，不要继续换标题。'}],
     '诊断偏差并提供具体对比，不再重复批量生成标题。'),
    ('change', dict(source='介绍排版工具', platform='wechat', content_type='article', goal='conversion'), [
        {'role': 'assistant', 'content': '你希望通过公众号介绍产品，获得咨询。'},
        {'role': 'user', 'content': '改主意了，只想做一条抖音操作演示，分享经验，不要推销。'}],
     '以最新平台、形式、目标为准，保留产品素材，不继续按公众号转化文案规划。'),
    ('immediate', {'source': '我有一个文章转图文工具。请现在直接给3个暂定选题，不用先问。'}, [],
     '给标明假设的候选，不强迫访谈，不虚构效果。'),
]


def run(output='artifacts/topic-explorer-evaluation.json'):
    prompt = yaml.safe_load(Path(__file__).with_name('application.yaml').read_text(encoding='utf-8'))['spec']['definition']['guided_prompts'][0]
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for name, answers, history, expected in SCENARIOS:
        with TemporaryDirectory(prefix='topic-explorer-eval-', ignore_cleanup_errors=True) as directory:
            engine = build_agent_engine(working_directory=directory)
            messages = [{'role': 'system', 'content': SYSTEM_PROMPT + '\n本次仅根据给定资料对话，只使用 request_user_input 提问工具，不读写文件，不联网。'},
                {'role': 'user', 'content': compose_guided_prompt(prompt, answers, application_id=1)['prompt']}, *history]
            try:
                response = engine.complete(messages, permission_mode='default', require_tool_approval=True,
                    timeout_seconds=120, collaboration_mode='default')
                question = response.input_request or {}
                tool_question = question.get('kind') == 'question' and 1 <= len(question.get('questions', [])) <= 3
                succeeded = tool_question or (name in {'complete', 'immediate'} and response.success)
                record = dict(name=name, expected=expected, adapter=engine.adapter_name, model=response.model,
                    success=succeeded, content=response.content if succeeded else '',
                    interaction='question_tool' if tool_question else 'text', questions=question.get('questions', []),
                    error='' if succeeded else '没有产生预期的提问工具请求。' if response.success else str(engine_failure(response.error)))
            except Exception as exc:
                record = dict(name=name, expected=expected, success=False, error=str(engine_failure(exc)))
        records.append(record)
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{name}: {"completed" if record["success"] else record["error"]}', flush=True)
        if not record['success']:
            break  # Do not repeat unavailable-provider calls.
    return records


def run_interactive(output='artifacts/topic-explorer-interactive.json'):
    """Exercise real tool requests and synthetic answers on the same live turn."""
    interactions = []
    stopped = False

    def answer(request, *, is_pending):
        nonlocal stopped
        questions = request.get('questions') or []
        if request.get('kind') != 'question' or not 1 <= len(questions) <= 3 or len(interactions) >= 3:
            stopped = True
            return None
        if not is_pending():
            return None
        answers = {}
        for question in questions:
            if not interactions:
                value = ('我是独立创作者，做了文章转图文工具，能在网页逐页改文字和分页，再导出图片。'
                    '想在小红书用多页图文帮助其他独立创作者，建立专业信任。'
                    '痛点是生成完图片后改一句话就得重做。我有亲自操作和修改的录屏，没有用户或效率数据。'
                    '不要功能清单，不夸大效果。请根据这些信息给三个不同切入点，让我选择。')
            else:
                options = question.get('options') or []
                value = options[0]['label'] if options else '选第一个实操切口，请交付选题说明和提纲，不再追问。'
            answers[question['id']] = {'answers': [value]}
        interactions.append({'questions': questions, 'synthetic_answers': answers})
        return {'type': 'answer', 'payload': {'answers': answers}}

    with TemporaryDirectory(prefix='topic-explorer-interactive-', ignore_cleanup_errors=True) as directory:
        engine = build_agent_engine(working_directory=directory)
        response = engine.complete([
            {'role': 'system', 'content': SYSTEM_PROMPT + '\n仅使用提问工具，不使用其他工具，不读写文件。'},
            {'role': 'user', 'content': '我做了一个内容创作工具，之前选题太泛。请先用提问工具了解我，再一起找到合适的选题。'},
        ], permission_mode='default', require_tool_approval=True, collaboration_mode='default',
            on_input_request=answer, cancelled=lambda: stopped, timeout_seconds=180)
    result = dict(success=bool(interactions) and response.success and not stopped and not response.input_request,
        interactions=interactions, content=response.content, adapter=engine.adapter_name, model=response.model)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({'success': result['success'], 'question_rounds': len(interactions)}, flush=True)
    return result
