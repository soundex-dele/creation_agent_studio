"""
Seed mock data for Creation Agent Studio.

Usage:
    python manage.py seed_mock_data
"""
import json
import os
import secrets
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from apps.agents.models import AgentCategory, Agent
from apps.applications.models import (
    Application, ApplicationCategory, ChatApplication,
)
from modules.catalog.models import AgentDraft, ApplicationDraft
from apps.templates.models import Template, TemplateAnalysisSection, TemplateCategory
from apps.conversations.models import Conversation, Message

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed the database with mock data for development'

    def add_arguments(self, parser):
        parser.add_argument(
            '--catalog-only', action='store_true',
            help='只导入智能体、应用和模板目录，不创建演示用户与会话。')

    def handle(self, *args, **options):
        self.stdout.write('[Seed] Seeding mock data...\n')

        catalog_only = options['catalog_only']
        if catalog_only:
            owner = (
                User.objects.filter(is_superuser=True).first()
                or User.objects.exclude(username='system').first()
                or User.objects.first()
            )
            if owner is None:
                raise CommandError('数据库中没有用户，无法设置目录数据的创建者。')
            users = [owner]
        else:
            # ─── Users ───
            users = self._seed_users()
            self.stdout.write(f'  [OK] Users: {len(users)}')

        # ─── Agent Categories ───
        agent_cats = self._seed_agent_categories()
        self.stdout.write(f'  [OK] Agent Categories: {len(agent_cats)}')

        # ─── Agents ───
        agents = self._seed_agents(users, agent_cats)
        self.stdout.write(f'  [OK] Agents: {len(agents)}')

        # ─── Application Categories ───
        app_cats = self._seed_application_categories()
        self.stdout.write(f'  [OK] Application Categories: {len(app_cats)}')

        # ─── Applications ───
        apps = self._seed_applications(users, app_cats, agents)
        self.stdout.write(f'  [OK] Applications: {len(apps)}')

        # ─── Template Categories ───
        template_cats = self._seed_template_categories()
        self.stdout.write(f'  [OK] Template Categories: {len(template_cats)}')

        # ─── Templates ───
        templates = self._seed_templates(users, template_cats)
        self.stdout.write(f'  [OK] Templates: {len(templates)}')

        if not catalog_only:
            # ─── Conversations + Messages ───
            convos = self._seed_conversations(users, agents)
            self.stdout.write(f'  [OK] Conversations: {len(convos)} with messages')

        self.stdout.write(self.style.SUCCESS('\n[Done] Mock data seeded successfully!'))

    # ──────────────────────────────────────────────
    def _seed_users(self):
        password = os.environ.get('DEMO_USER_PASSWORD')
        if not password:
            password = secrets.token_urlsafe(24)
            self.stdout.write(self.style.WARNING(
                f'  [Seed] DEMO_USER_PASSWORD is unset; generated demo password: {password}'
            ))
        data = [
            {'username': 'creator', 'email': 'creator@example.com', 'password': password,
             'role': 'creator', 'bio': '全职创作者，擅长短视频和直播'},
            {'username': 'designer', 'email': 'designer@example.com', 'password': password,
             'role': 'professional', 'bio': '视觉设计师，精通品牌设计'},
            {'username': 'admin', 'email': 'admin@example.com', 'password': password,
             'role': 'admin', 'bio': '平台管理员'},
        ]
        users = []
        for d in data:
            user, _ = User.objects.get_or_create(
                username=d['username'],
                defaults={
                    'email': d['email'],
                    'role': d['role'],
                    'bio': d['bio'],
                    'is_active': True,
                }
            )
            user.set_password(d['password'])
            user.save()
            users.append(user)
        return users

    # ──────────────────────────────────────────────
    def _seed_agent_categories(self):
        data = [
            {'name': '文案创作', 'slug': 'copywriting', 'description': '各类文案创作智能体',
             'icon': '✍️', 'order': 1},
            {'name': '视频制作', 'slug': 'video', 'description': '视频脚本和剪辑辅助',
             'icon': '🎬', 'order': 2},
            {'name': '视觉设计', 'slug': 'design', 'description': '图文排版和视觉设计',
             'icon': '🎨', 'order': 3},
            {'name': '音频配乐', 'slug': 'audio', 'description': '配乐和音效推荐',
             'icon': '🎵', 'order': 4},
            {'name': '数据分析', 'slug': 'analytics', 'description': '内容数据分析和优化建议',
             'icon': '📊', 'order': 5},
            {'name': '直播运营', 'slug': 'livestream', 'description': '直播策划和运营指导',
             'icon': '🎙️', 'order': 6},
        ]
        cats = []
        for d in data:
            cat, _ = AgentCategory.objects.get_or_create(
                slug=d['slug'], defaults=d
            )
            cats.append(cat)
        return cats

    # ──────────────────────────────────────────────
    def _seed_agents(self, users, cats):
        cat_map = {c.slug: c for c in cats}
        creator = users[0]

        data = [
            {
                'name': '视频脚本生成器', 'slug': 'video-script-generator',
                'category_slug': 'video', 'icon': '🎬',
                'description': '根据主题和风格自动生成短视频脚本，包含分镜、台词和画面描述。',
                'system_prompt': '你是一个专业的短视频脚本编剧。根据用户提供的主题、目标受众和风格要求，生成包含分镜描述、台词和拍摄建议的完整脚本。脚本结构应包括：开场钩子、主体内容、互动环节和结尾引导。每个分镜需要标注时长、画面描述、配音文案和字幕建议。',
            },
            {
                'name': '文案润色专家', 'slug': 'copywriting-polisher',
                'category_slug': 'copywriting', 'icon': '✍️',
                'description': '优化你的营销文案、社交媒体帖子和产品描述，让文字更有感染力。',
                'system_prompt': '你是一位资深文案编辑，擅长优化各类营销文案。在保持原意的基础上，提升文案的吸引力、可读性和转化效果。你会根据不同平台特性（小红书、抖音、微信等）调整文案风格和长度。',
            },
            {
                'name': '直播话术顾问', 'slug': 'livestream-script-advisor',
                'category_slug': 'livestream', 'icon': '🎙️',
                'description': '为直播场景设计互动话术、产品介绍流程和观众引导策略。',
                'system_prompt': '你是一名经验丰富的直播策划师。帮助用户设计直播流程、编写产品介绍话术、设计互动环节，提升直播间活跃度和转化率。你需要考虑直播的节奏把控、情绪调动和促单技巧。',
            },
            {
                'name': '短视频剪辑助手', 'slug': 'video-editing-assistant',
                'category_slug': 'video', 'icon': '✂️',
                'description': '分析视频素材并提供剪辑建议，包括节奏把控、转场方案和配乐推荐。',
                'system_prompt': '你是一个视频剪辑指导专家。根据用户提供的素材描述和目标风格，给出专业的剪辑建议，包括片段取舍、节奏设计、转场方式和配乐搭配。关注热门视频的剪辑趋势和技巧。',
            },
            {
                'name': '图文排版设计师', 'slug': 'graphic-layout-designer',
                'category_slug': 'design', 'icon': '🎨',
                'description': '为小红书、微信公众号等平台设计图文排版方案和视觉风格指导。',
                'system_prompt': '你是一名专业的平面设计师，专注于社交媒体图文内容的排版设计。根据内容主题和平台特性，提供配色方案、字体选择、版式布局等设计建议。你的设计建议需要兼顾美观性和信息传达效率。',
            },
            {
                'name': '音乐配乐推荐', 'slug': 'music-bgm-advisor',
                'category_slug': 'audio', 'icon': '🎵',
                'description': '根据视频风格和情感氛围，推荐合适的背景音乐和音效方案。',
                'system_prompt': '你是一位音乐顾问，专精于视频配乐。根据用户描述的视频类型、节奏和情感氛围，推荐匹配的背景音乐风格、具体曲目建议和音效设计方案。你会考虑版权问题和免费音乐资源。',
            },
            {
                'name': '爆款标题生成器', 'slug': 'viral-title-generator',
                'category_slug': 'copywriting', 'icon': '💡',
                'description': '根据内容主题生成吸引眼球的标题，提升点击率和曝光量。',
                'system_prompt': '你是一位精通内容营销的标题专家。根据用户提供的内容摘要和目标平台，生成多个具有吸引力的标题方案。你了解各平台的标题规律和用户心理，能够平衡标题的吸引力和内容的相关性。',
            },
            {
                'name': '内容数据分析师', 'slug': 'content-data-analyst',
                'category_slug': 'analytics', 'icon': '📊',
                'description': '分析内容数据表现，提供优化建议和策略调整方案。',
                'system_prompt': '你是一位内容数据分析师。根据用户提供的内容发布数据（播放量、点赞数、评论数、转化率等），分析内容表现，找出优化空间，并给出具体可执行的改进建议。你熟悉各平台的数据分析工具和指标体系。',
            },
        ]

        agents = []
        for d in data:
            cat_slug = d.pop('category_slug')
            system_prompt = d.pop('system_prompt')
            organization = creator.organization_memberships.get().organization
            agent, _ = Agent.objects.get_or_create(
                slug=d['slug'],
                defaults={
                    **d,
                    'category': cat_map[cat_slug],
                    'created_by': creator,
                    'organization': organization,
                    'is_public': True,
                }
            )
            AgentDraft.objects.update_or_create(
                agent=agent,
                defaults={
                    'organization': organization, 'updated_by': creator,
                    'content': {
                        'system_prompt': system_prompt,
                        'model_config': {}, 'tool_config': [],
                        'knowledge_config': [], 'guardrail_config': {},
                        'workflow_config': {}, 'skill_bindings': [],
                    },
                })
            agents.append(agent)
        return agents

    # ──────────────────────────────────────────────
    def _seed_application_categories(self):
        data = [
            {'name': '创作工具', 'slug': 'creative', 'description': '内容创作类工具',
             'icon': '🎨', 'order': 1},
            {'name': '视频编辑', 'slug': 'video', 'description': '视频录制与编辑工具',
             'icon': '🎬', 'order': 2},
            {'name': 'AI 能力', 'slug': 'ai', 'description': 'AI 驱动的创作能力',
             'icon': '✨', 'order': 3},
            {'name': '效率工具', 'slug': 'productivity', 'description': '提升创作效率的工具',
             'icon': '⚡', 'order': 4},
            {'name': '媒体处理', 'slug': 'media', 'description': '音频、素材等媒体处理工具',
             'icon': '🎵', 'order': 5},
        ]
        cats = []
        for d in data:
            cat, _ = ApplicationCategory.objects.get_or_create(
                slug=d['slug'], defaults=d
            )
            cats.append(cat)
        return cats

    # ──────────────────────────────────────────────
    def _seed_applications(self, users, cats, agents):
        cat_map = {c.slug: c for c in cats}
        agent_map = {agent.slug: agent for agent in agents}
        creator = users[0]

        data = [
            {
                'slug': 'screen-recorder', 'name': '录屏工作台',
                'category_slug': 'video', 'icon': '🎥', 'color': '#2e1a1a',
                'tags': ['录屏', '标注', '直播'],
                'developer': 'Creation Studio',
                'description': '一键录制屏幕、摄像头与系统声音，支持实时标注与高光片段标记。',
            },
            {
                'slug': 'subtitle-studio', 'name': '智能字幕',
                'category_slug': 'ai', 'icon': '💬', 'color': '#1a2e3e',
                'tags': ['ASR', '双语', '字幕'],
                'developer': 'Creation Studio',
                'description': '语音转字幕、双语对齐、样式模板与时间轴微调，自动断句更自然。',
            },
            {
                'slug': 'video-composer', 'name': '视频合成器',
                'category_slug': 'video', 'icon': '🎞️', 'color': '#1a1a2e',
                'tags': ['合成', '画中画', '转场'],
                'developer': 'Creation Studio',
                'description': '多源视频画中画合成、布局模板与转场，实时预览最终成片效果。',
            },
            {
                'slug': 'image-genie', 'name': 'AI 绘画',
                'category_slug': 'ai', 'icon': '🖼️', 'color': '#2e1a2e',
                'tags': ['文生图', '风格迁移', '提示词'],
                'developer': 'Creation Studio',
                'description': '文生图、图生图与风格迁移，内置提示词库与一致角色生成能力。',
            },
            {
                'slug': 'xiaohongshu-cover', 'name': '小红书封面生成',
                'category_slug': 'creative', 'icon': '📕', 'color': '#ff2442',
                'tags': ['小红书', '封面', 'AI 绘画'],
                'developer': 'Creation Studio',
                'description': '根据笔记主题生成醒目、清晰、适合小红书发布的封面图片。',
                'renderer_key': 'image-genie',
                'executor_key': 'image-generation',
                'default_config': {
                    'empty_state_title': '生成吸睛的小红书封面',
                    'input_placeholder': '描述笔记主题、标题、风格和配色…',
                    'input_hint': '输入封面需求，Enter 生成',
                    'prompt_prefix': (
                        '请生成一张适合小红书笔记使用的封面图片。'
                        '画面应有清晰的视觉焦点、醒目的标题排版空间和适合移动端浏览的构图，'
                        '避免水印、平台 Logo 和无关小字。用户需求：'
                    ),
                    'suggestions': [
                        '美食探店封面，标题“周末宝藏咖啡馆”，暖橙色，杂志拼贴风',
                        '一周穿搭分享封面，奶油白和浅粉配色，简约时尚风',
                        '云南旅行攻略封面，标题“第一次去云南必看”，清新明亮',
                        '平价好物推荐封面，红白撞色，大标题，高点击率电商风',
                    ],
                },
            },
            {
                'slug': 'xiaohongshu-copy', 'name': '小红书文案生成',
                'category_slug': 'creative', 'icon': '📝', 'color': '#ff5a76',
                'tags': ['小红书', '种草文案', '标题'],
                'developer': 'Creation Studio',
                'description': '根据内容主题生成小红书标题、正文和话题标签。',
                'kind': Application.Kind.CHAT,
                'renderer_key': 'chat',
                'executor_key': 'agent-chat',
            },
            {
                'slug': 'script-writer', 'name': '剧本创作',
                'category_slug': 'creative', 'icon': '✍️', 'color': '#1a2e1a',
                'tags': ['剧本', '分镜', '对白'],
                'developer': 'Creation Studio',
                'description': '从大纲到分镜，结构化剧本写作与角色对白润色，输出可直接配音的稿件。',
            },
            {
                'slug': 'voiceover-mixer', 'name': '配音混音',
                'category_slug': 'media', 'icon': '🎙️', 'color': '#1a2e2e',
                'tags': ['TTS', '混音', '配音'],
                'developer': 'Creation Studio',
                'description': 'TTS 语音合成、多角色音色切换与背景音乐混音，一键导出配音轨。',
            },
            {
                'slug': 'template-hub', 'name': '模板套用',
                'category_slug': 'creative', 'icon': '📐', 'color': '#2e2e1a',
                'tags': ['模板', '批量', '快速'],
                'developer': 'Creation Studio',
                'description': '从模板库一键套用，替换素材即可成片，适合批量、快速的内容生产。',
            },
            {
                'slug': 'project-manager', 'name': '项目管理',
                'category_slug': 'productivity', 'icon': '📋', 'color': '#213e3e',
                'tags': ['看板', '协作'],
                'developer': 'Creation Studio',
                'description': '创作项目看板、版本管理与团队协作，跟踪每个作品从草稿到发布。',
            },
            {
                'slug': 'asset-library', 'name': '素材库',
                'category_slug': 'media', 'icon': '🗂️', 'color': '#3e2e1a',
                'tags': ['素材', '检索', '打标'],
                'developer': 'Creation Studio',
                'description': '图片、视频、音频与字体素材集中管理，智能打标与快速检索。',
            },
            {
                'slug': 'auto-clipper', 'name': '智能剪辑',
                'category_slug': 'ai', 'icon': '⚡', 'color': '#16213e',
                'tags': ['自动剪辑', '高光', '短视频'],
                'developer': 'Creation Studio',
                'description': '基于脚本与高光识别自动剪辑长视频，输出短视频矩阵分发素材。',
            },
        ]

        apps = []
        for d in data:
            cat_slug = d.pop('category_slug')
            kind = d.pop('kind', Application.Kind.TASK)
            renderer_key = d.pop(
                'renderer_key',
                'image-genie' if d['slug'] == 'image-genie' else 'generic-task')
            executor_key = d.pop('executor_key', 'catalog-task')
            default_config = d.pop('default_config', {})
            organization = creator.organization_memberships.get().organization
            app, _ = Application.objects.get_or_create(
                slug=d['slug'],
                defaults={
                    **d,
                    'category': cat_map[cat_slug],
                    'created_by': creator,
                    'organization': organization,
                    'is_public': True,
                    'kind': kind,
                }
            )
            if kind == Application.Kind.CHAT:
                ChatApplication.objects.get_or_create(application=app)
            ApplicationDraft.objects.update_or_create(
                application=app,
                defaults={
                    'organization': organization, 'updated_by': creator,
                    'content': {
                        'kind': kind, 'executor_kind': (
                            'agent' if kind == Application.Kind.CHAT else 'media'),
                        'executor_key': executor_key,
                        'renderer_key': renderer_key,
                        'default_config': default_config,
                        **({'chat_profile': {}, 'agent_bindings': [],
                            'skill_bindings': [], 'guided_prompts': []}
                           if kind == Application.Kind.CHAT else {}),
                    },
                })
            if app.slug == 'xiaohongshu-copy':
                self._configure_xiaohongshu_copy_app(
                    app, agent_map['copywriting-polisher'], creator)
            apps.append(app)
        return apps

    def _configure_xiaohongshu_copy_app(self, app, agent, creator):
        """Create the runnable chat configuration for the copywriting app."""
        if app.created_by.username == 'system' and creator.username != 'system':
            app.created_by = creator
            app.save(update_fields=['created_by'])
        draft = app.draft
        definition = {
            **draft.content,
            'kind': 'chat', 'executor_kind': 'agent',
            'executor_key': 'agent-chat', 'renderer_key': 'chat',
            'default_config': {'guided_entry_prompt_key': 'generate-copy'},
            'chat_profile': {
                'welcome_message': '告诉我笔记主题，我会生成标题、正文和话题标签。',
                'input_placeholder': '描述你想创作的小红书笔记…',
                'empty_state_title': '生成一篇小红书种草文案',
                'allow_agent_selection': False,
                'allow_skill_selection': False,
                'allow_extra_skills': False,
                'conversation_policy': 'new_each_open',
                'starter_layout': 'cards',
            },
            'agent_bindings': [{
                'agent_id': agent.id,
                'label': '小红书文案助手',
                'is_default': True,
                'order': 0,
            }],
            'skill_bindings': [],
            'guided_prompts': [{
                'key': 'generate-copy',
                'title': '生成小红书文案',
                'description': '生成吸睛标题、种草正文和相关话题标签。',
                'icon': '✍️',
                'prompt_template': (
                    '请为一条小红书笔记撰写种草文案，包含吸睛标题、正文与话题标签。\n'
                    '主题：{topic}\n语气：{tone}\n字数：约 {length}\n补充要求：{extra}'),
                'action': 'preview',
                'is_featured': True,
                'order': 0,
                'questions': [
            {
                'key': 'topic', 'label': '内容主题',
                'type': 'text', 'required': True,
                'placeholder': '例如：周末探店·胡同咖啡馆',
                'options': [],
            },
            {
                'key': 'tone', 'label': '文案语气',
                'type': 'single_choice', 'required': False,
                'options': [
                    {'value': 'friendly', 'label': '亲切种草'},
                    {'value': 'professional', 'label': '专业客观'},
                    {'value': 'playful', 'label': '活泼俏皮'},
                    {'value': 'literary', 'label': '文艺走心'},
                ],
            },
            {
                'key': 'length', 'label': '正文长度',
                'type': 'single_choice', 'required': False,
                'options': [
                    {'value': '100', 'label': '100字'},
                    {'value': '200', 'label': '200字'},
                    {'value': '300', 'label': '300字'},
                ],
            },
            {
                'key': 'extra', 'label': '补充说明',
                'type': 'text', 'required': False,
                'placeholder': '例如：突出性价比和氛围感',
                'options': [],
            },
                ],
            }],
        }
        draft.content = definition
        draft.version += 1
        draft.updated_by = creator
        draft.save(update_fields=['content', 'version', 'updated_by', 'updated_at'])

    # ──────────────────────────────────────────────
    def _seed_template_categories(self):
        data = [
            {'name': '公众号文章', 'slug': 'articles', 'description': '长文与公众号案例',
             'order': 1},
            {'name': '社交图文', 'slug': 'social-posts', 'description': '小红书等社交平台图文案例',
             'order': 2},
            {'name': '视频脚本', 'slug': 'video-scripts', 'description': '短视频与知识视频脚本案例',
             'order': 3},
            {'name': '品牌内容', 'slug': 'brand-content', 'description': '品牌故事与营销内容案例',
             'order': 4},
            {'name': '播客访谈', 'slug': 'podcasts', 'description': '播客文稿与人物访谈案例',
             'order': 5},
        ]
        cats = []
        for d in data:
            cat, _ = TemplateCategory.objects.get_or_create(
                slug=d['slug'], defaults=d
            )
            cats.append(cat)
        return cats

    # ──────────────────────────────────────────────
    def _seed_templates(self, users, cats):
        cat_map = {c.slug: c for c in cats}
        creator = users[0]

        data = [
            {
                'title': '我用一套简单系统，重新整理了每天的信息输入',
                'category_slug': 'articles',
                'summary': '一个典型的“真实困扰—亲身尝试—可复用方法”案例。',
                'content_type': 'article',
                'source_title': '我用一套简单系统，重新整理了每天的信息输入',
                'source_url': 'https://example.com/cases/information-system',
                'source_author': '林间笔记',
                'source_platform': '少数派',
                'source_published_at': '2026-08-12',
                'source_excerpt': '每天早上，我都会在三个稍后读应用、两个聊天软件和一堆浏览器标签页之间来回切换。真正让我焦虑的并不是信息太多，而是我从来不知道哪些值得留下。',
                'source_content': (
                    '每天早上，我都会在三个稍后读应用、两个聊天软件和一堆浏览器标签页之间来回切换。\n\n'
                    '真正让我焦虑的并不是信息太多，而是我从来不知道哪些值得留下。收藏越多，我反而越不愿意回看。\n\n'
                    '我最先尝试的是寻找一个功能更完整的工具。迁移花了整个周末，两天后，新的收件箱再次堆满。那时我才意识到，问题不在工具，而在于我没有决定什么信息根本不需要进入系统。\n\n'
                    '于是我把输入过程缩减成三个动作：当场删除、带着问题阅读、只保存能够支持当前项目的内容。两周以后，待读数量从三百多条降到了二十条以内。\n\n'
                    '这套方法并不适合需要长期追踪大量资料的研究工作，但对日常阅读和内容创作来说，少保存一点，反而让我真正用上了留下的信息。'
                ),
                'recommended_reason': '从具体困扰切入，以试错建立可信度，再把个人经验收束为清晰方法。',
                'reusable_patterns': [
                    '用一个具体而混乱的日常场景开头',
                    '展示失败尝试及其代价',
                    '在中段重新定义真正的问题',
                    '将解决方案控制在三到五步',
                    '结尾同时给出结果与适用边界',
                ],
                'copyright_mode': 'owned',
                'word_count': 2800,
                'reading_time_minutes': 9,
                'tags': ['第一人称', '方法论', '效率'],
                'status': 'published',
                'is_featured': True,
                'analysis_sections': [
                    ('hook', '开头钩子', '用可感知的混乱场景制造共鸣，不先讲方法。', '每天早上，我都会在三个稍后读应用……'),
                    ('conflict', '核心冲突', '表面问题是工具太多，深层问题是缺少筛选标准。', '真正让我焦虑的并不是信息太多。'),
                    ('structure', '内容结构', '痛点场景 → 错误尝试 → 认知转折 → 三步方法 → 结果 → 边界。', ''),
                    ('technique', '表达技巧', '每个抽象原则后都补一个生活细节，关键句独立成段。', ''),
                    ('reusable_pattern', '可复用点', '保留叙事骨架和证据结构，替换个人问题、试错过程和结果数据。', ''),
                ],
            },
            {
                'title': '新手写作最容易忽略的 7 个标题细节',
                'category_slug': 'social-posts',
                'summary': '结论前置、条目平行，每一点都配有反例和修改示范。',
                'content_type': 'social_post',
                'source_title': '新手写作最容易忽略的 7 个标题细节',
                'source_url': 'https://example.com/cases/title-details',
                'source_author': '写作实验室',
                'source_platform': '小红书',
                'source_excerpt': '好标题不是堆叠情绪词，而是让读者立刻知道：这和我有什么关系。',
                'recommended_reason': '清单结构稳定，反例和修改示范让抽象规则立刻可验证。',
                'reusable_patterns': ['首屏直接交付结论', '所有条目使用平行结构', '每条规则配一个反例和改写'],
                'copyright_mode': 'excerpt',
                'word_count': 1400,
                'reading_time_minutes': 5,
                'tags': ['清单', '教程', '标题'],
                'status': 'published',
                'analysis_sections': [
                    ('hook', '价值承诺', '标题直接说明目标人群、问题数量和预期收益。', ''),
                    ('structure', '清单结构', '总论点之后展开七个并列细节，阅读路径没有分叉。', ''),
                    ('evidence', '示例设计', '每个观点都用错误标题与修改版本形成对照。', ''),
                    ('limitations', '适用边界', '适合教程和经验总结，不适合依赖悬念推进的故事内容。', ''),
                ],
            },
            {
                'title': '为什么我们总会怀念十年前的互联网',
                'category_slug': 'video-scripts',
                'summary': '从共同记忆开场，经由三个论点推进，最后回到个人选择。',
                'content_type': 'video_script',
                'source_title': '为什么我们总会怀念十年前的互联网',
                'source_url': 'https://example.com/cases/old-internet',
                'source_author': '影像观察局',
                'source_platform': 'Bilibili',
                'source_excerpt': '我们怀念的也许不是某一个网站，而是那个还愿意漫无目的地闲逛的自己。',
                'recommended_reason': '个人记忆与公共议题交替出现，让抽象观点始终落在可见的生活细节上。',
                'reusable_patterns': ['共同记忆开场', '三段式观点推进', '每个论点配置具体画面', '结尾回到个人选择'],
                'copyright_mode': 'excerpt',
                'word_count': 3200,
                'reading_time_minutes': 12,
                'tags': ['观点', '怀旧', '视频脚本'],
                'status': 'published',
                'analysis_sections': [
                    ('hook', '共同记忆', '用拨号音、论坛签名档等细节快速建立群体记忆。', ''),
                    ('structure', '观点推进', '体验变化、关系变化、商业变化三个论点逐层放大。', ''),
                    ('rhythm', '画面节奏', '抽象论述与具体旧画面交替，避免连续口播造成疲劳。', ''),
                    ('reusable_pattern', '结尾回收', '不判断过去更好，而是把问题交还给观众今天的选择。', ''),
                ],
            },
        ]

        templates = []
        for d in data:
            cat_slug = d.pop('category_slug')
            sections = d.pop('analysis_sections')
            tmpl, _ = Template.objects.update_or_create(
                title=d['title'],
                defaults={
                    **d,
                    'category': cat_map[cat_slug],
                    'created_by': creator,
                }
            )
            tmpl.analysis_sections.all().delete()
            TemplateAnalysisSection.objects.bulk_create([
                TemplateAnalysisSection(
                    template=tmpl,
                    section_type=section_type,
                    title=title,
                    content=content,
                    evidence_quote=evidence_quote,
                    order=order,
                )
                for order, (section_type, title, content, evidence_quote)
                in enumerate(sections)
            ])
            templates.append(tmpl)
        return templates

    # ──────────────────────────────────────────────
    def _seed_conversations(self, users, agents):
        creator = users[0]
        agent = agents[0] if agents else None  # 视频脚本生成器

        conversations_data = [
            {
                'title': '短视频脚本：咖啡店探店',
                'messages': [
                    {'role': 'user', 'content': '帮我写一个咖啡店探店的短视频脚本，目标受众是 20-30 岁的年轻人，风格要轻松有趣。'},
                    {'role': 'assistant', 'content': '好的，我来为你设计一个轻松有趣的咖啡店探店短视频脚本。\n\n**主题：** 隐藏在老巷子里的宝藏咖啡馆\n\n**时长：** 45-60秒\n\n**风格：** Vlog + 解说，轻快节奏\n\n---\n\n**分镜 1 — 开场钩子 (0-3s)**\n画面：推门进入的慢动作，暖色灯光洒落\n配音：「这家藏在巷子深处的咖啡馆，我愿意称它为城市里最温柔的角落」\n\n**分镜 2 — 环境展示 (3-12s)**\n画面：快速切换店内细节 — 复古台灯、手写菜单、窗边绿植\n配音：「老板是个从日本留学回来的咖啡师，整家店的审美都很在线」\n字幕：📍 城中村·老巷子 | ☕ 手冲 ¥28 起\n\n**分镜 3 — 咖啡特写 (12-25s)**\n画面：手冲咖啡的特写 — 热水注入、泡沫升起、拉花成型\n配音：「他们家的招牌是冰博客拿铁，奶泡绵密得像在喝一朵云」\n字幕：☁️ 冰博客拿铁 ¥32 — 本期推荐\n\n**分镜 4 — 互动环节 (25-35s)**\n画面：和朋友在店内拍照、聊天、翻书\n配音：「最重要的是，这里拍照真的太好看了，随便一拍就是日系杂志风」\n\n**分镜 5 — 结尾引导 (35-45s)**\n画面：咖啡杯特写 + 店名招牌\n配音：「如果你也知道这样隐藏的好店，评论区告诉我呀～」\n字幕：❤️ 点赞收藏 · 周末打卡\n\n---\n\n需要我调整某个分镜的内容，或者补充 BGM 推荐吗？'},
                    {'role': 'user', 'content': '开头换一个更有悬念的方式，再推荐一下 BGM'},
                    {'role': 'assistant', 'content': '没问题！以下是优化后的开场和 BGM 方案：\n\n**优化开场：**\n「这家藏在巷子里的咖啡馆...我去了 7 次」\n（配合推门慢动作 + 暖色光晕）\n\n这个开场利用了数字悬念，能在前 3 秒抓住注意力。\n\n**BGM 方案：**\n- 风格：City Pop / Lo-fi\n- 推荐曲目：轻柔钢琴 + 电子节拍\n- 音量控制：解说时降低，转场时渐强\n\n需要我把完整的最终版脚本整理出来吗？'},
                ],
            },
            {
                'title': '直播话术优化方案',
                'messages': [
                    {'role': 'user', 'content': '我要做一场美妆产品的直播带货，需要设计完整的话术方案'},
                    {'role': 'assistant', 'content': '好的，我来为你设计一场美妆直播带货的话术方案：\n\n## 📋 直播概要\n- **主题：** 夏日清透妆容 · 限时专场\n- **时长：** 90 分钟\n- **产品数量：** 5 款核心产品\n\n---\n\n## 🎬 话术流程\n\n### 第一阶段：暖场 (0-10min)\n\n**开场话术：**\n「宝子们晚上好～今天这场直播我准备了超多惊喜！夏天到了，底妆最怕的就是脱妆对不对？今天教你们一个超持久的清透妆容，整个下午茶拍完照都不用补妆！」\n\n**互动话术：**\n- 「先到的宝宝扣个1，看看有多少人」\n- 「今天直播间有专属福利，想要的扣想要」\n\n### 第二阶段：产品讲解 (10-60min)\n每款产品按 「痛点 → 解决方案 → 效果展示 → 价格优势」 的节奏进行。\n\n### 第三阶段：收官 (60-90min)\n回顾所有产品优惠，制造紧迫感，预告下次直播。\n\n---\n\n需要我为每款产品编写详细话术吗？'},
                ],
            },
            {
                'title': '小红书图文排版建议',
                'messages': [
                    {'role': 'user', 'content': '帮我设计一套小红书美食探店图文的排版方案'},
                    {'role': 'assistant', 'content': '好的，以下是小红书美食探店图文排版方案：\n\n## 📐 排版规范\n- **尺寸：** 1242 × 1660px（3:4竖版）\n- **字体：** 标题用思源黑体 Bold，正文用思源宋体\n- **配色：** 暖橙 #E8A838 为主色，深棕 #3C2415 为辅色\n\n## 📄 页面结构\n\n### 封面（第1页）\n- 顶部 70%：美食大图（带轻微滤镜）\n- 底部 30%：半透明色块 + 标题文字\n- 右上角：打卡定位标签\n\n### 内容页（第2-5页）\n- 左右分栏布局\n- 左侧：菜品图片\n- 右侧：菜品名称 + 价格 + 一句话点评\n- 底部：星级评分 + 标签\n\n### 总结页（第6页）\n- 店名 + 地址 + 人均消费\n- 综合评分 + 推荐菜品 TOP3\n- 「收藏不迷路」引导语\n\n需要我推荐具体的配色和滤镜参数吗？'},
                ],
            },
        ]

        convos = []
        for cd in conversations_data:
            convo, created = Conversation.objects.get_or_create(
                user=creator,
                title=cd['title'],
                defaults={'agent': agent},
            )
            if created or convo.messages.count() == 0:
                for md in cd['messages']:
                    Message.objects.create(
                        conversation=convo,
                        role=md['role'],
                        content=md['content'],
                    )
            convos.append(convo)
        return convos
