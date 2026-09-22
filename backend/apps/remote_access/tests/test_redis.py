"""Real Redis integration. Set REMOTE_TEST_REDIS_BINARY to a redis-server binary."""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest
import redis

from apps.remote_access.broker import Subscription, publish


@pytest.fixture
def redis_url(tmp_path):
    binary = os.environ.get('REMOTE_TEST_REDIS_BINARY') or shutil.which('redis-server')
    if not binary:
        pytest.skip('Set REMOTE_TEST_REDIS_BINARY to run real Redis cross-process tests')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen([
        binary, '--bind', '127.0.0.1', '--port', str(port), '--save', '',
        '--appendonly', 'no', '--dir', str(tmp_path), '--loglevel', 'warning',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'redis://127.0.0.1:{port}/0'
    client = redis.Redis.from_url(url)
    try:
        for _ in range(100):
            try:
                if client.ping():
                    break
            except redis.ConnectionError:
                time.sleep(.05)
        else:
            raise RuntimeError('Temporary Redis did not start')
        yield url
        assert client.dbsize() == 0, 'Relay must not persist request or response bodies'
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.asyncio
async def test_pubsub_crosses_processes_without_persisting_payloads(redis_url, settings):
    settings.REMOTE_RELAY_REDIS_URL = redis_url
    source = '''
import asyncio, json, sys
from django.conf import settings
settings.configure(REMOTE_RELAY_REDIS_URL=sys.argv[1], DEBUG=False, REMOTE_RELAY_ALLOW_MEMORY=False)
from apps.remote_access.broker import Subscription, publish
async def main():
    subscription = await Subscription('cross-process').open()
    print('ready', flush=True)
    try:
        request = await subscription.receive(timeout=10)
        await publish('cross-process-response', {'type': 'chunk', 'id': request['id'], 'body': request['body']})
    finally:
        await subscription.close()
asyncio.run(main())
'''
    child = subprocess.Popen([sys.executable, '-c', source, redis_url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    response = await Subscription('cross-process-response').open()
    try:
        ready = await asyncio.wait_for(asyncio.to_thread(child.stdout.readline), 10)
        assert ready.strip() == 'ready'
        assert await publish('cross-process', {'id': 'request-1', 'body': 'ephemeral private text'}) == 1
        assert await response.receive(timeout=10) == {'type': 'chunk', 'id': 'request-1', 'body': 'ephemeral private text'}
        assert await asyncio.to_thread(child.wait, 10) == 0
        # Pub/Sub drops messages when the destination is offline.
        assert await publish('cross-process', {'body': 'offline instruction'}) == 0
    finally:
        await response.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
