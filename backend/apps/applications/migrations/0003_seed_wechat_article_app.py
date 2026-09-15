"""Seed a guided chat application backed by write-wechat-article."""
from django.db import migrations


AGENT_SYSTEM_PROMPT = """你是微信公众号文章创作助手。

每次写作必须先使用 write-wechat-article Skill，并严格遵循其中的文章类型、写作标准、输出格式和事实边界。根据用户提供的主题、目标读者、写作目的、素材及限制，交付可以直接编辑发布的完整文章包。不得虚构数据、来源、案例、经历或效果。只有缺失信息会显著改变文章方向或事实准确性时，才提出一个最关键的问题。"""


PROMPT_TEMPLATE = """请使用 write-wechat-article Skill 编写一篇微信公众号文章。

主题：{topic}
目标读者：{audience}
写作目的：{goal}
文章类型：{article_type}
期望语气：{tone}
可用素材或必须保留的信息：{source_material}
其他要求或禁区：{requirements}

请遵循 Skill 的默认发布包格式，输出标题候选、推荐标题及理由、摘要、完整正文和结尾互动。没有提供真实素材时，不要虚构数据、来源、人物或案例。"""


def seed_wechat_article_app(apps, schema_editor):
    User = apps.get_model('users', 'User')
    AgentCategory = apps.get_model('agents', 'AgentCategory')
    Agent = apps.get_model('agents', 'Agent')
    ApplicationCategory = apps.get_model(
        'applications', 'ApplicationCategory')
    Application = apps.get_model('applications', 'Application')
    Skill = apps.get_model('applications', 'Skill')
    ChatApplicationProfile = apps.get_model(
        'applications', 'ChatApplicationProfile')
    ApplicationAgentBinding = apps.get_model(
        'applications', 'ApplicationAgentBinding')
    ApplicationSkillBinding = apps.get_model(
        'applications', 'ApplicationSkillBinding')
    GuidedPrompt = apps.get_model('applications', 'GuidedPrompt')
    GuidedQuestion = apps.get_model('applications', 'GuidedQuestion')
    GuidedOption = apps.get_model('applications', 'GuidedOption')

    owner = (User.objects.filter(is_superuser=True).first()
             or User.objects.filter(username='creator').first()
             or User.objects.filter(username='system').first())
    if owner is None:
        owner = User.objects.create(username='system')

    skill = Skill.objects.filter(
        slug='write-wechat-article', is_active=True).first()
    if skill is None:
        skill = Skill.objects.create(
            slug='write-wechat-article',
            name='write-wechat-article',
            description=(
                '根据主题、受众和目标编写可发布的微信公众号文章包。'),
            visibility='public',
            owner=owner,
            source_type='bundled',
            source_uri='.graphflow/skills/write-wechat-article/SKILL.md',
            artifact_key='.graphflow/skills/write-wechat-article',
            manifest={'entrypoint': 'SKILL.md'},
            is_active=True,
        )

    agent_category, _ = AgentCategory.objects.get_or_create(
        slug='copywriting', defaults={'name': '文案创作', 'order': 1})
    agent, _ = Agent.objects.update_or_create(
        slug='wechat-article-writer',
        defaults={
            'name': '公众号文章写作助手',
            'description': '使用专业写作规范生成可直接发布的公众号文章。',
            'system_prompt': AGENT_SYSTEM_PROMPT,
            'category': agent_category,
            'created_by': owner,
            'organization_id': skill.organization_id,
            'is_public': True,
        },
    )

    app_category, _ = ApplicationCategory.objects.get_or_create(
        slug='creative',
        defaults={
            'name': '内容创作',
            'description': '文章、文案和创意内容生成',
            'icon': 'edit',
            'order': 1,
        },
    )
    application, _ = Application.objects.update_or_create(
        slug='wechat-article-writer',
        defaults={
            'category': app_category,
            'name': '微信公众号文章生成',
            'description': '填写主题、受众和目标，生成可直接编辑发布的公众号文章。',
            'icon': '📝',
            'color': '#07c160',
            'tags': ['公众号', '文章写作', '内容创作'],
            'developer': 'Agent Studio',
            'is_public': True,
            'created_by': owner,
            'organization_id': skill.organization_id,
            'kind': 'chat',
            'renderer_key': 'chat',
            'default_config': {
                'guided_entry_prompt_key': 'article-brief',
            },
        },
    )
    ChatApplicationProfile.objects.update_or_create(
        application=application,
        defaults={
            'welcome_message': '填写文章需求，我会生成提示词并开始创作。',
            'input_placeholder': '继续补充要求或修改文章…',
            'empty_state_title': '创作一篇微信公众号文章',
            'allow_agent_selection': False,
            'allow_skill_selection': False,
            'allow_extra_skills': False,
            'conversation_policy': 'choose_history',
            'starter_layout': 'cards',
        },
    )
    ApplicationAgentBinding.objects.filter(
        application=application).exclude(agent=agent).delete()
    ApplicationAgentBinding.objects.update_or_create(
        application=application,
        agent=agent,
        defaults={
            'label': agent.name,
            'is_default': True,
            'order': 0,
        },
    )
    ApplicationSkillBinding.objects.filter(application=application).exclude(
        skill=skill).delete()
    ApplicationSkillBinding.objects.update_or_create(
        application=application,
        skill=skill,
        defaults={'mode': 'required', 'config': {}, 'order': 0},
    )

    prompt, _ = GuidedPrompt.objects.update_or_create(
        application=application,
        key='article-brief',
        defaults={
            'title': '填写文章需求',
            'description': '说明主题、读者和写作目的，其余选项可以交给助手判断。',
            'icon': '📝',
            'prompt_template': PROMPT_TEMPLATE,
            'action': 'preview',
            'is_featured': True,
            'order': 0,
        },
    )

    questions = [
        {
            'key': 'topic', 'label': '文章主题', 'type': 'text',
            'placeholder': '例如：普通人如何建立自己的知识管理系统',
            'help_text': '说明文章要解决的核心问题。', 'required': True,
            'default_value': None, 'order': 0, 'options': [],
        },
        {
            'key': 'audience', 'label': '目标读者', 'type': 'text',
            'placeholder': '例如：刚开始工作的职场新人',
            'help_text': '读者身份会影响内容深度、案例和表达方式。',
            'required': True, 'default_value': None, 'order': 1, 'options': [],
        },
        {
            'key': 'goal', 'label': '写作目的', 'type': 'single_choice',
            'placeholder': '请选择文章目标', 'help_text': '',
            'required': True, 'default_value': 'share_knowledge', 'order': 2,
            'options': [
                ('share_knowledge', '科普知识'),
                ('teach_method', '提供方法'),
                ('express_opinion', '表达观点'),
                ('build_trust', '建立专业信任'),
                ('emotional_resonance', '引发情绪共鸣'),
                ('product_conversion', '产品或服务转化'),
            ],
        },
        {
            'key': 'article_type', 'label': '文章类型',
            'type': 'single_choice', 'placeholder': '自动选择最合适的结构',
            'help_text': '', 'required': False, 'default_value': 'auto',
            'order': 3,
            'options': [
                ('auto', '由助手自动选择'),
                ('knowledge', '知识科普型'),
                ('tutorial', '教程方法型'),
                ('opinion', '观点评论型'),
                ('story', '故事案例型'),
                ('list', '清单盘点型'),
                ('hot_topic', '热点解读型'),
                ('emotion', '情绪共鸣型'),
                ('conversion', '产品转化型'),
            ],
        },
        {
            'key': 'tone', 'label': '期望语气', 'type': 'single_choice',
            'placeholder': '自动匹配主题和读者', 'help_text': '',
            'required': False, 'default_value': 'auto', 'order': 4,
            'options': [
                ('auto', '由助手自动判断'),
                ('professional', '专业克制'),
                ('natural', '自然亲切'),
                ('warm', '温暖共情'),
                ('sharp', '鲜明犀利'),
                ('relaxed', '轻松易读'),
            ],
        },
        {
            'key': 'source_material', 'label': '可用素材', 'type': 'text',
            'placeholder': '粘贴事实、观点、产品信息或真实案例；没有可留空',
            'help_text': '助手不会虚构你未提供的数据、来源或经历。',
            'required': False, 'default_value': '', 'order': 5, 'options': [],
        },
        {
            'key': 'requirements', 'label': '其他要求或禁区', 'type': 'text',
            'placeholder': '例如：约 2000 字；不要使用网络流行语',
            'help_text': '', 'required': False, 'default_value': '',
            'order': 6, 'options': [],
        },
    ]
    keep_question_keys = [item['key'] for item in questions]
    prompt.questions.exclude(key__in=keep_question_keys).delete()
    for item in questions:
        values = dict(item)
        options = values.pop('options')
        question, _ = GuidedQuestion.objects.update_or_create(
            guided_prompt=prompt,
            key=values.pop('key'),
            defaults=values,
        )
        keep_values = [value for value, _ in options]
        question.options.exclude(value__in=keep_values).delete()
        for order, (value, label) in enumerate(options):
            GuidedOption.objects.update_or_create(
                question=question,
                value=value,
                defaults={'label': label, 'order': order},
            )


class Migration(migrations.Migration):
    dependencies = [
        ('applications', '0002_seed_default_chat'),
        ('agents', '0003_seed_general_agent'),
    ]
    operations = [migrations.RunPython(
        seed_wechat_article_app, migrations.RunPython.noop)]
