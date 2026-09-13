from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.templates.models import Template, TemplateAnalysisSection, TemplateCategory


class TemplateFilterTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        articles = TemplateCategory.objects.create(
            name='公众号文章', slug='articles', description='长文案例')
        videos = TemplateCategory.objects.create(
            name='视频脚本', slug='video-scripts', description='视频案例')
        article = Template.objects.create(
            title='信息整理方法',
            summary='从真实困扰切入的方法型文章',
            category=articles,
            created_by=self.user,
            status='published',
            source_author='林间笔记',
            source_platform='少数派',
            tags=['方法论', '效率'],
        )
        TemplateAnalysisSection.objects.create(
            template=article,
            section_type='hook',
            title='开头钩子',
            content='具体场景制造共鸣',
        )
        Template.objects.create(
            title='互联网怀旧脚本',
            summary='观点型视频脚本',
            category=videos,
            created_by=self.user,
            status='published',
            content_type='video_script',
            source_platform='Bilibili',
            tags=['观点', '脚本'],
        )

    def results(self, response):
        return response.data if isinstance(response.data, list) else response.data['results']

    def test_searches_title_author_and_platform(self):
        for query in ['信息整理', '林间笔记', '少数派']:
            response = self.client.get('/api/v1/templates/', {'search': query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(self.results(response)), 1)

    def test_filters_by_category_and_content_type(self):
        response = self.client.get('/api/v1/templates/', {'category': 'video-scripts'})
        self.assertEqual(len(self.results(response)), 1)
        response = self.client.get('/api/v1/templates/', {'content_type': 'article'})
        self.assertEqual(len(self.results(response)), 1)

    def test_detail_contains_analysis_and_increments_views(self):
        template = Template.objects.get(title='信息整理方法')
        response = self.client.get(f'/api/v1/templates/{template.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['analysis_sections']), 1)
        template.refresh_from_db()
        self.assertEqual(template.view_count, 1)

    def test_create_case_with_nested_analysis(self):
        category = TemplateCategory.objects.get(slug='articles')
        response = self.client.post('/api/v1/templates/', {
            'category': category.id,
            'title': '新案例',
            'summary': '待分析的文章案例',
            'content_type': 'article',
            'status': 'draft',
            'analysis_sections': [{
                'section_type': 'structure',
                'title': '内容结构',
                'content': '问题 → 尝试 → 结论',
                'order': 0,
            }],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        created = Template.objects.get(title='新案例')
        self.assertEqual(created.created_by, self.user)
        self.assertEqual(created.analysis_sections.count(), 1)
