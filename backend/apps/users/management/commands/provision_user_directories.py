from django.core.management.base import BaseCommand

from apps.users.models import User
from core.user_directories import user_directory


class Command(BaseCommand):
    help = 'Create missing private workspace directories for existing active users.'

    def handle(self, **options):
        count = 0
        for user in User.objects.filter(is_active=True).iterator():
            user_directory(user)
            count += 1
        self.stdout.write(self.style.SUCCESS(f'已检查并创建 {count} 个用户专属目录。'))
