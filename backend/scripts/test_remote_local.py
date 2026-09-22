"""Exercise two real local ASGI backends and a connector, without Redis.

Run with backend/.venv/bin/python backend/scripts/test_remote_local.py.
Use --keep-running for manual API testing after the smoke checks pass.
All databases, credentials and logs live in a fresh private temporary directory.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx


BACKEND = Path(__file__).resolve().parents[1]
SEED = """
import json, os
from django.contrib.auth import get_user_model
from apps.conversations.models import Conversation
from modules.execution.models import Run, RunEvent
user = get_user_model().objects.create_user(
    username=os.environ['SMOKE_USERNAME'], password=os.environ['SMOKE_PASSWORD'], role='admin')
org = user.owned_organizations.get()
result = {'user_id': user.id, 'organization_id': str(org.id)}
if os.environ['REMOTE_ACCESS_HOST_ENABLED'] == 'True':
    conversation = Conversation.objects.create(user=user, organization=org, title='Local smoke history')
    run = Run.objects.create(owner=user, organization=org, executor_kind='agent',
        source_type='conversation', source_id=str(conversation.id), status='succeeded', next_event_sequence=2)
    for sequence, kind in [(1, 'output.delta'), (2, 'run.succeeded')]:
        RunEvent.objects.create(run=run, organization=org, sequence=sequence,
            type=kind, payload={'text': 'local-stream-marker'} if sequence == 1 else {})
    result.update(conversation_id=conversation.id, run_id=str(run.id))
print(json.dumps(result))
"""
COUNTS = """
import json
from apps.conversations.models import Conversation
from modules.execution.models import Run, RunEvent, IdempotencyRecord
print(json.dumps({model.__name__: model.objects.count()
    for model in (Conversation, Run, RunEvent, IdempotencyRecord)}))
"""


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_for(predicate, description, processes, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check(all(p.poll() is None for p in processes), f'Process exited while waiting for {description}')
        try:
            if predicate():
                return
        except httpx.TransportError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f'Timed out waiting for {description}')


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-port', type=int, default=18080)
    parser.add_argument('--client-port', type=int, default=18081)
    parser.add_argument('--keep-running', action='store_true')
    parser.add_argument('--production-server', action='store_true',
                        help='Test production settings with explicit HTTP and memory relay enabled.')
    args = parser.parse_args()
    check(sys.prefix != sys.base_prefix, 'Run this script using the project virtual environment.')
    check(args.server_port != args.client_port, 'Server and client need different ports.')
    for port in (args.server_port, args.client_port):
        check(1 <= port <= 65535, 'Invalid port')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))

    root = Path(tempfile.mkdtemp(prefix='creation-studio-remote-local-'))
    print(f'Test data and logs: {root}', flush=True)
    processes, logs, clients = [], [], []
    common = {
        **os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings.development',
        'DATABASE_ENGINE': 'sqlite', 'REDIS_ENABLED': 'False', 'REMOTE_RELAY_REDIS_URL': '',
        'SINGLE_TENANT_MODE': 'False', 'LICENSE_AUTH_ENABLED': 'False',
        'ALLOWED_HOSTS': 'localhost,127.0.0.1', 'OTEL_ENABLED': 'False',
        'SENTRY_DSN': '', 'API_RATE_THROTTLING_ENABLED': 'False', 'PYTHONUNBUFFERED': '1',
    }

    def environment(role):
        directory = root / role
        directory.mkdir()
        host = role == 'client'
        env = {
            **common, 'SECRET_KEY': secrets.token_urlsafe(48),
            'SQLITE_PATH': str(directory / 'db.sqlite3'),
            'AGENT_WORKSPACE_ROOT': str(directory / 'workspaces'),
            'MEDIA_ROOT': str(directory / 'media'),
            'ARTIFACT_ROOT': str(directory / 'artifacts'),
            'REMOTE_CONNECTOR_LOCK_PATH': str(directory / 'connector.lock'),
            'REMOTE_ACCESS_HOST_ENABLED': str(host), 'REMOTE_RELAY_ENABLED': str(not host),
            'REMOTE_CONNECTOR_LOCAL_URL': f'http://127.0.0.1:{args.client_port}',
            'SMOKE_USERNAME': f'{role}-tester', 'SMOKE_PASSWORD': secrets.token_urlsafe(24),
        }
        if not host and args.production_server:
            env.update(
                DJANGO_SETTINGS_MODULE='backend.settings.production', DEBUG='False',
                REMOTE_RELAY_ALLOW_MEMORY='True', SECURE_SSL_REDIRECT='False',
                SESSION_COOKIE_SECURE='False', CSRF_COOKIE_SECURE='False',
                JWT_REFRESH_COOKIE_SECURE='False',
            )
        return env

    def management(env, *arguments):
        log_path = root / env['SMOKE_USERNAME'].replace('-tester', '') / 'setup.log'
        with log_path.open('a+') as log:
            offset = log.tell()
            result = subprocess.run([sys.executable, 'manage.py', *arguments], cwd=BACKEND,
                                    env=env, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=600)
            log.seek(offset)
            output = log.read()
        check(result.returncode == 0, f'Management command failed; see {log_path}')
        return output

    def shell_json(env, source):
        return json.loads(management(env, 'shell', '-c', source).strip().splitlines()[-1])

    def start(name, env, arguments):
        log = (root / f'{name}.log').open('w')
        logs.append(log)
        process = subprocess.Popen([sys.executable, *arguments], cwd=BACKEND, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    def api(client, method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        check(response.status_code == expected,
              f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:400]}')
        return response

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, interrupt)
    try:
        server_env, host_env = environment('server'), environment('client')
        print('Initializing database schema...', flush=True)
        management(server_env, 'migrate', '--noinput')
        # Both roles use the same schema. Copy it before creating any test users
        # or business records; SQLite's backup API also handles WAL safely.
        with sqlite3.connect(server_env['SQLITE_PATH']) as source:
            with sqlite3.connect(host_env['SQLITE_PATH']) as target:
                source.backup(target)
        identities = []
        for env, port in ((server_env, args.server_port), (host_env, args.client_port)):
            print(f'Starting {env["SMOKE_USERNAME"]} on {port}...', flush=True)
            identities.append(shell_json(env, SEED))
            start(env['SMOKE_USERNAME'], env,
                  ['-m', 'daphne', '-b', '127.0.0.1', '-p', str(port), 'backend.asgi:application'])
            client = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=25, trust_env=False)
            clients.append(client)
            wait_for(lambda: client.get('/healthz/').status_code == 200, 'backend health', processes)
            login = api(client, 'POST', '/api/v1/auth/login/', json={
                'username': env['SMOKE_USERNAME'], 'password': env['SMOKE_PASSWORD'],
            })
            if env is server_env and args.production_server:
                check('Secure' not in login.headers.get('set-cookie', ''), 'HTTP login cookie is Secure')
                check('HttpOnly' in login.headers.get('set-cookie', ''), 'Refresh cookie lost HttpOnly')
                # No refresh token in the body: exercise the cookie over HTTP.
                refreshed = api(client, 'POST', '/api/v1/auth/token/refresh/', json={}).json()
                client.headers['Authorization'] = 'Bearer ' + refreshed['access']
                print('PASS: production HTTP login and cookie refresh, without HTTPS redirect', flush=True)
            else:
                client.headers['Authorization'] = 'Bearer ' + login.json()['tokens']['access']

        server, host = clients
        server_identity, host_identity = identities
        config = {
            'server_url': str(server.base_url).rstrip('/'), 'computer_name': 'Local test computer',
            'enabled': True, 'local_user_id': host_identity['user_id'],
            'organization_id': host_identity['organization_id'],
        }
        api(host, 'PUT', '/api/v1/remote-access/', json=config)
        pairing = api(host, 'POST', '/api/v1/remote-access/pair/', json={}).json()
        device_id = pairing['device_id']
        proxy = f'/api/v1/remote/devices/{device_id}/proxy/'
        api(server, 'POST', '/api/v1/remote/claim/', json={'code': pairing['pairing_code']})
        api(server, 'GET', proxy + 'conversations/', expected=503)
        pending = api(host, 'POST', '/api/v1/remote-access/pending/', json={}).json()
        check(pending['account_id'] == server_identity['user_id'], 'Wrong pairing account')
        api(host, 'POST', '/api/v1/remote-access/confirm/', json={'account_id': pending['account_id']})
        start('connector', host_env, ['manage.py', 'run_remote_connector'])

        def online():
            return api(server, 'GET', '/api/v1/remote/devices/').json()[0]['online']

        wait_for(online, 'connector online', processes)
        print('PASS: pairing, account confirmation and real WebSocket connection', flush=True)
        context = api(server, 'GET', proxy + 'remote-access/context/').json()
        check(context['organization_id'] == host_identity['organization_id'], 'Wrong local organization')
        history = api(server, 'GET', proxy + 'conversations/?page=1').json()
        check(history['results'][0]['id'] == host_identity['conversation_id'], 'Missing local history')
        payload = {'title': 'Created through relay'}
        headers = {'Idempotency-Key': 'local-smoke-create'}
        created = api(server, 'POST', proxy + 'conversations/', expected=201, json=payload, headers=headers).json()
        replay = api(server, 'POST', proxy + 'conversations/', expected=201, json=payload, headers=headers).json()
        check(created['id'] == replay['id'], 'Idempotent retry created another conversation')
        api(server, 'POST', proxy + 'conversations/', expected=409,
            json={'title': 'Conflicting payload'}, headers=headers)
        api(server, 'GET', proxy + 'auth/me/', expected=400)
        print('PASS: history, remote creation, idempotent retry and path restrictions', flush=True)

        stream_path = (proxy + f'organizations/{host_identity["organization_id"]}'
                       f'/runs/{host_identity["run_id"]}/stream?after=0')
        with server.stream('GET', stream_path, headers={
            'Accept': 'text/event-stream', 'Last-Event-ID': '0',
        }) as response:
            check(response.status_code == 200, f'SSE returned {response.status_code}')
            check(response.headers['content-type'].startswith('text/event-stream'), 'Wrong SSE content type')
            body = ''.join(response.iter_text())
        check('local-stream-marker' in body and 'event: run.succeeded' in body, 'Missing streamed events')
        print('PASS: real HTTP → WebSocket → local HTTP SSE forwarding', flush=True)

        api(host, 'PUT', '/api/v1/remote-access/', json={**config, 'enabled': False})
        wait_for(lambda: not online(), 'device offline', processes)
        api(server, 'GET', proxy + 'conversations/', expected=503)
        api(host, 'PUT', '/api/v1/remote-access/', json=config)
        wait_for(online, 'device reconnected', processes)
        api(server, 'GET', proxy + 'conversations/')
        server_counts = shell_json(server_env, COUNTS)
        host_counts = shell_json(host_env, COUNTS)
        check(not any(server_counts.values()), f'Business records leaked to server: {server_counts}')
        check(host_counts['Conversation'] == 2, f'Unexpected local records: {host_counts}')
        print('PASS: offline rejection, reconnection and isolated business data', flush=True)

        if not args.keep_running:
            api(server, 'DELETE', f'/api/v1/remote/devices/{device_id}/', expected=204)
            unbound = api(host, 'POST', '/api/v1/remote-access/unbind/', json={}).json()
            check(unbound['device_id'] is None and not unbound['enabled'], 'Stale local binding remains')
            api(host, 'POST', '/api/v1/remote-access/unbind/', json={})
            print('PASS: local unbind after server revocation and repeated unbind', flush=True)

        access = {role: {'url': str(client.base_url), 'username': env['SMOKE_USERNAME'],
                         'password': env['SMOKE_PASSWORD']}
                  for role, client, env in [('server', server, server_env), ('client', host, host_env)]}
        access['device_id'] = device_id
        access_path = root / 'access.json'
        with open(access_path, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            json.dump(access, output, indent=2)
        print(f'All checks passed without Redis. Access details: {access_path}', flush=True)
        if args.keep_running:
            print('Backends and connector remain running. Press Ctrl+C to stop all three.', flush=True)
            while True:
                check(all(p.poll() is None for p in processes), 'A test process exited')
                time.sleep(1)
    finally:
        for process in reversed(processes):
            stop(process)
        for client in clients:
            client.close()
        for log in logs:
            log.close()
        signal.signal(signal.SIGTERM, previous_term)
        print(f'Test processes stopped. Data and logs retained at {root}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
