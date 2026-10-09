"""Keep existing personal cookies when switching to editable plaintext settings."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations


def convert_cookies(apps, schema_editor, *, decrypt):
    connection = schema_editor.connection
    config_model = apps.get_model('douyin_benchmark', 'CollectorConfig')
    organization_model = apps.get_model('enterprise', 'Organization')
    cipher = Fernet(base64.urlsafe_b64encode(
        hashlib.sha256((settings.SECRET_KEY + ':douyin-benchmark').encode()).digest()))
    # Visit each organization explicitly so forced PostgreSQL RLS stays enabled.
    with connection.cursor() as cursor:
        previous = None
        if connection.vendor == 'postgresql':
            cursor.execute("SELECT current_setting('app.organization_id', true)")
            previous = cursor.fetchone()[0]
        try:
            for organization_id in organization_model.objects.using(connection.alias).values_list('pk', flat=True).iterator():
                if connection.vendor == 'postgresql':
                    cursor.execute("SELECT set_config('app.organization_id', %s, true)", [str(organization_id)])
                configs = config_model.objects.using(connection.alias).filter(organization_id=organization_id)
                for config in configs.iterator():
                    try:
                        value = (cipher.decrypt(config.cookies.encode()).decode() if decrypt
                                 else cipher.encrypt(config.cookies.encode()).decode())
                    except InvalidToken:
                        raise RuntimeError('Cannot migrate saved Douyin cookies; restore the original SECRET_KEY and retry.') from None
                    configs.filter(pk=config.pk).update(cookies=value)
        finally:
            if connection.vendor == 'postgresql':
                cursor.execute("SELECT set_config('app.organization_id', %s, true)", [previous or ''])


def decrypt_cookies(apps, schema_editor):
    convert_cookies(apps, schema_editor, decrypt=True)


def encrypt_cookies(apps, schema_editor):
    convert_cookies(apps, schema_editor, decrypt=False)


class Migration(migrations.Migration):
    dependencies = [('douyin_benchmark', '0009_voice_rls')]
    operations = [
        migrations.RenameField(model_name='collectorconfig', old_name='encrypted_cookies', new_name='cookies'),
        migrations.RunPython(decrypt_cookies, encrypt_cookies),
    ]
