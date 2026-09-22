"""Ephemeral Pub/Sub only: never Redis lists, streams, cache values or jobs."""
import asyncio
import json
from collections import defaultdict

from django.conf import settings

_subscribers = defaultdict(set)


class Subscription:
    def __init__(self, topic):
        self.topic = "remote:v1:" + topic
        self.client = None
        self.pubsub = None
        self.queue = None

    async def open(self):
        if settings.REMOTE_RELAY_REDIS_URL:
            from redis.asyncio import Redis
            self.client = Redis.from_url(settings.REMOTE_RELAY_REDIS_URL, decode_responses=True)
            self.pubsub = self.client.pubsub()
            await self.pubsub.subscribe(self.topic)
            # Await subscription acknowledgement before anyone publishes.
            while True:
                event = await self.pubsub.get_message(timeout=5)
                if event and event["type"] == "subscribe":
                    break
        elif settings.DEBUG or settings.REMOTE_RELAY_ALLOW_MEMORY:
            self.queue = asyncio.Queue(maxsize=128)
            _subscribers[self.topic].add(self.queue)
        else:
            raise RuntimeError("Remote relay requires Redis Pub/Sub")
        return self

    async def receive(self, timeout=65):
        async def read():
            if self.queue is not None:
                return await self.queue.get()
            while True:
                event = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
                if event and event["type"] == "message":
                    return json.loads(event["data"])
        return await asyncio.wait_for(read(), timeout)

    async def close(self):
        if self.queue is not None:
            _subscribers[self.topic].discard(self.queue)
            if not _subscribers[self.topic]:
                del _subscribers[self.topic]
        if self.pubsub:
            await self.pubsub.aclose()
        if self.client:
            await self.client.aclose()


async def publish(topic, message):
    topic = "remote:v1:" + topic
    if settings.REMOTE_RELAY_REDIS_URL:
        from redis.asyncio import Redis
        async with Redis.from_url(settings.REMOTE_RELAY_REDIS_URL) as client:
            return await client.publish(topic, json.dumps(message, separators=(",", ":")))
    if not (settings.DEBUG or settings.REMOTE_RELAY_ALLOW_MEMORY):
        raise RuntimeError("Remote relay requires Redis Pub/Sub")
    count = 0
    for queue in tuple(_subscribers.get(topic, ())):
        try:
            queue.put_nowait(message)
            count += 1
        except asyncio.QueueFull:
            # Force the affected subscription to fail; never accumulate bodies.
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "error", "detail": "Slow remote subscriber"})
    return count
