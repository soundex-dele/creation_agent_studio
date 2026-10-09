"""Article writing uses the topic's frozen voice and facts, never the latest profile."""

PROMPT = '''根据选中的选题，写一篇可直接阅读的完整中文文章。
返回JSON：{"title":"文章标题","body":"完整正文，段落用换行分隔","notes":["需要作者核实或补充的事实"]}。
若提供voice_profile.prompt，遵循该已确认提示词的用词、观点表达、句式、节奏、开头与结尾习惯；
仅将usage=style的正文样本作为文风示例，content样本只参考内容。其他研究资料不能覆盖个人文风。
旧创作档案可使用profile.voice及其真实经历。没有文风资料时使用自然、具体、简洁的表达。
标题、角度和观点围绕本次topic展开，不照抄代表作。篇幅参考代表作和信息量，不为凑字数重复观点。
输出文章正文，不输出提纲、分镜、拍摄指令、时间轴或写作过程。自然分段，避免机械小标题和模板化总结。
只能使用明确提供的事实和经历；不能把风格示例、待补充素材或推测当成作者的亲身事实。
缺少真实案例时改用不冒充经历的解释，待核实事项单独放notes，不在正文编造数字、身份、引文或产品效果。
遵守账号定位、内容支柱和内容边界，保留个人特点，改善空话、过度总结和生硬衔接。
正文不超过20000字。'''


def validate_article(value):
    if not isinstance(value, dict):
        raise ValueError('文章结果格式无效。')
    for key, limit in [('title', 300), ('body', 20000)]:
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > limit:
            raise ValueError(f'文章{key}不能为空且不能超过{limit}字。')
    notes = value.get('notes', [])
    if not isinstance(notes, list) or len(notes) > 20 or any(not isinstance(n, str) or not n.strip() or len(n) > 1000 for n in notes):
        raise ValueError('待核实事项最多20条，每条1—1000字。')
    return {'title': value['title'].strip(), 'body': value['body'].strip(), 'notes': notes}


def markdown(content):
    return f"# {content['title']}\n\n{content['body']}\n"


def execute_article(task, payload, sink, save, config):
    from ..runtime import current
    from .models import ScriptVersion
    from .research_runtime import structured
    save('正在按文风写作')
    brief = {k: v for k, v in task.input['brief'].items() if k not in ['production_format', 'duration', 'conditions']}
    output = structured(task, PROMPT, {'brief': brief, 'topic': task.input['topic'],
        'reference': task.input.get('reference', {})}, config, validate_article, sink)
    with current(payload, sink) as active:
        version, _ = ScriptVersion.objects.get_or_create(task=active, revision=1, defaults={'content': output})
        output = version.content
    save('completed', output)
