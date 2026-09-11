from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    return JsonResponse({'status': 'ok'})


def readiness(request):
    checks = {'database': False, 'redis': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks['database'] = True
    except Exception:
        pass
    try:
        cache.set('readiness-check', 'ok', 5)
        checks['redis'] = cache.get('readiness-check') == 'ok'
    except Exception:
        pass
    for worker_pool in settings.REQUIRED_EXECUTION_WORKER_POOLS:
        checks[f'worker:{worker_pool}'] = bool(
            cache.get(f'execution-worker:{worker_pool}'))
    if settings.REQUIRE_AUTOMATION_SCHEDULER:
        checks['scheduler'] = bool(cache.get('automation-scheduler'))
    status_code = 200 if all(checks.values()) else 503
    return JsonResponse({'status': 'ready' if status_code == 200 else 'not_ready',
                         'checks': checks}, status=status_code)
