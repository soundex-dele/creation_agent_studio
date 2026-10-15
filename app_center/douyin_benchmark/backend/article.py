"""Article writing uses the topic's frozen voice and facts, never the latest profile."""

PROMPT = '''根据选中的选题，写一篇可直接阅读的完整中文文章。
topic也可以是作者本次直接输入的主题；遵循brief.writing_requirements中的角度与交付要求，brief.factual_material是本次明确提供的真实素材。
返回JSON：{"title":"文章标题","body":"完整正文，段落用换行分隔","notes":["需要作者核实或补充的事实"]}。
若提供voice_profile.prompt，遵循该已确认提示词的用词、观点表达、句式、节奏、开头与结尾习惯；
仅将usage=style的正文样本作为文风示例，content样本只参考内容。其他研究资料不能覆盖个人文风。
旧创作档案可使用profile.voice及其真实经历。没有文风资料时使用自然、具体、简洁的表达。
标题、角度和观点围绕本次topic展开，不照抄代表作。篇幅参考代表作和信息量，不为凑字数重复观点。
输出文章正文，不输出提纲、分镜、拍摄指令、时间轴或写作过程。分段、小标题与结尾方式服从已确认文风，不套用模板。
只能使用明确提供的事实和经历；不能把风格示例、待补充素材或推测当成作者的亲身事实。
缺少真实案例时改用不冒充经历的解释，待核实事项单独放notes，不在正文编造数字、身份、引文或产品效果。
遵守账号定位、内容支柱和内容边界，优先还原个人表达，仅清理明显错误。
保留有意重复、跳跃转折和留白，不强制添加钩子、金句、小标题、总结或互动结尾。
仅使用与个人文风兼容的通用写作技巧；改善建议不自动执行。
正文不超过20000字。'''

REVIEW_PROMPT = '''对提供的文章初稿进行一次个人文风校对，并在本次返回必要修订后的完整文章。
保留本次brief.writing_requirements中的角度与交付要求，以brief.factual_material及已确认素材核对事实；写作要求本身不是事实证据。
执行顺序：事实约束、内容边界和本次明确要求 > 已确认voice_profile.prompt（旧档案用profile.voice） > usage=style原文示范 > 通用写作技巧。
对照已确认规则的适用条件，检查语气、句式、推进逻辑、节奏和结尾的具体偏离。
只修订有规则或原文依据的偏离，符合规则的段落保留，不能为了显示校对成果而改写。
单篇候选不强制使用；证据不足处不补造习惯。content样本只参考内容，改善建议不自动执行。
保留有意重复、跳跃转折和留白，不强制加入钩子、金句、小标题、总结或互动结尾。
不新增事实、经历、数字、身份、引文或产品效果，不复制样本段落，不能把初稿或风格示例当作事实来源。
对照原始事实素材，删除初稿中无依据的事实陈述或移入notes待核实，保留原有待核实事项。
返回JSON：{"article":{"title":"标题","body":"最终完整正文","notes":["待核实事项"]},
"summary":"简短说明具体偏离、对应规则或样本依据及必要修订；无需修改时如实说明"}。
若初稿有cover则保留或据文风修订。不要输出相似度百分比、评分、校验通过保证或思考过程。
'''


def has_style(brief):
    from .voice_style import make_prompt
    profile = brief.get('voice_profile') or {}
    if any(str(profile.get(k, '')).strip() for k in ('rules', 'examples', 'avoid')):
        return True
    if profile.get('prompt', '').strip() and profile['prompt'] != make_prompt(profile):
        return True  # Hand-written or legacy confirmed prompts remain supported.
    return bool((brief.get('profile') or {}).get('voice', '').strip() or any(
        row.get('usage') == 'style' and row.get('text', '').strip() for row in brief.get('voice_evidence', [])))


def validate_review(value, draft):
    if not isinstance(value, dict) or not isinstance(value.get('summary'), str) or not 0 < len(value['summary'].strip()) <= 2000:
        raise ValueError('文风校对缺少有效修订说明。')
    article = validate_article(value.get('article'))
    article['notes'] = list(dict.fromkeys(draft['notes'] + article['notes']))
    if 'cover' in draft and 'cover' not in article:
        article['cover'] = draft['cover']
    return validate_article(article), value['summary'].strip()


def validate_article(value):
    if not isinstance(value, dict):
        raise ValueError('文章结果格式无效。')
    for key, limit in [('title', 300), ('body', 20000)]:
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > limit:
            raise ValueError(f'文章{key}不能为空且不能超过{limit}字。')
    notes = value.get('notes', [])
    if not isinstance(notes, list) or len(notes) > 20 or any(not isinstance(n, str) or not n.strip() or len(n) > 1000 for n in notes):
        raise ValueError('待核实事项最多20条，每条1—1000字。')
    result = {'title': value['title'].strip(), 'body': value['body'].strip(), 'notes': notes}
    if 'cover' in value:
        if not isinstance(value['cover'], str) or len(value['cover']) > 300:
            raise ValueError('封面短句不能超过300字。')
        result['cover'] = value['cover'].strip()
    return result


def markdown(content):
    return f"# {content['title']}\n\n{content['body']}\n"


def execute_article(task, payload, sink, save, config):
    from ..runtime import current
    from .models import ScriptVersion
    from .research_runtime import structured
    # A retried lease must not attach a new review to an already saved article.
    with current(payload, sink) as active:
        existing = active.versions.filter(revision=1).first()
        saved = {**existing.content, **({'style_review': active.output['style_review']}
            if 'style_review' in active.output else {})} if existing else None
    if saved is not None:
        save('completed', saved)
        return
    save('正在按文风写作')
    brief = {k: v for k, v in task.input['brief'].items() if k not in ['production_format', 'duration', 'conditions']}
    data = {'brief': brief, 'topic': task.input['topic'], 'reference': task.input.get('reference', {})}
    output = structured(task, PROMPT, data, config, validate_article, sink)
    review = {'status': 'not_applicable', 'summary': '未提供文风资料，未进行文风校对。', 'revision': 1}
    if has_style(brief):
        save('正在校对个人文风')
        try:
            output, summary = structured(task, REVIEW_PROMPT, {**data, 'draft': output}, config,
                lambda value: validate_review(value, output), sink, writing_skill=False)
            review = {'status': 'completed', 'summary': summary, 'revision': 1}
        except ValueError:
            # Model/service and result-validation errors can fall back; cancellation,
            # permission errors and expired leases must still abort through current().
            review = {'status': 'unavailable', 'summary': '文风校对未完成，已保留初稿，请人工核对。', 'revision': 1}
    with current(payload, sink) as active:
        version = ScriptVersion.objects.create(task=active, revision=1, content=output)
        output = {**version.content, 'style_review': review}
        active.output = output
        active.save(update_fields=['output'])
    save('completed', output)
