"""Bounded, read-only network acceptance probe; never prints credentials."""
import json
from django.core.management.base import BaseCommand, CommandError
from modules.tenancy.database import tenant_database_context
from apps.applications.models import Application
from app_center.douyin_benchmark.backend.collector_config import LocalDTKClient
from app_center.douyin_benchmark.backend.provider import CollectionError


class Command(BaseCommand):
    help = 'Probe the configured Douyin hotlist and one keyword search page without saving data.'

    def add_arguments(self, parser):
        parser.add_argument('--application', required=True, type=int)
        parser.add_argument('--keyword', default='科普')

    def handle(self, *args, **options):
        try:
            app = Application.objects.get(pk=options['application'], slug='douyin-benchmark')
            with tenant_database_context(app.organization_id):
                client = LocalDTKClient(application=app)
                result = {}
                for label, path, params in [('hotlist', '/radar/hotlist', {}),
                                           ('search', '/radar/search', {'keyword': options['keyword'], 'cursor': '0'})]:
                    try:
                        data = client.fetch(path, params)
                        rows = data['items']
                        result[label] = {'verified': bool(rows), 'count': len(rows), 'captured_at': data['captured_at'],
                                         'examples': [{'title': r['title'], 'url': r['url']} for r in rows[:2]]}
                    except CollectionError as exc:
                        result[label] = {'verified': False, 'error': str(exc), 'code': exc.code, 'diagnostic': exc.diagnostic}
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                if not all(r['verified'] for r in result.values()):
                    raise CommandError('真实雷达验收未通过，详情见以上脱敏结果。')
        except Application.DoesNotExist:
            raise CommandError('未找到指定抖音应用。') from None
