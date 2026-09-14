import asyncio
import json
import time

from asgiref.sync import sync_to_async
from channels.layers import InMemoryChannelLayer, get_channel_layer
from django.db import close_old_connections

from modules.execution.api.serializers import RunEventSerializer
from modules.execution.models import Run, RunEvent
from apps.enterprise.models import Organization
from modules.tenancy.database import tenant_database_context


class StreamAccessLost(Exception):
    pass


TERMINAL_EVENT_TYPES = {"run.succeeded", "run.failed", "run.cancelled"}


def _cross_process_channel_layer(layer):
    """Return a notification layer only when workers can reach web subscribers."""

    # InMemoryChannelLayer is process-local. Treating it as shared makes a web
    # stream sleep until the heartbeat whenever the execution worker runs in a
    # separate process, which batches all deltas into an apparent final answer.
    if layer is None or isinstance(layer, InMemoryChannelLayer):
        return None
    return layer


def encode_event(event):
    envelope = RunEventSerializer(event).data
    data = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n".encode()


@sync_to_async(thread_sensitive=True)
def _load_event_batch(*, user, organization_id, run_id, after, limit):
    close_old_connections()
    try:
        with tenant_database_context(organization_id):
            has_access = (
                Organization.objects.visible_to(user)
                .filter(pk=organization_id, is_active=True)
                .exists()
            )
            if not has_access:
                raise StreamAccessLost
            if not Run.objects.for_organization(organization_id).filter(pk=run_id).exists():
                raise StreamAccessLost
            return list(
                RunEvent.objects.for_organization(organization_id)
                .filter(run_id=run_id, sequence__gt=after)
                .order_by("sequence")[:limit]
            )
    finally:
        # sync_to_async's thread-sensitive executor is long lived; without an
        # explicit close, an SSE read can pin a PostgreSQL connection after the
        # stream has ended.
        close_old_connections()


async def stream_run_events(
    *,
    user,
    organization_id,
    run_id,
    after,
    poll_interval=0.5,
    heartbeat_interval=15.0,
    batch_size=100,
):
    """Subscribe first, then replay and continuously fill from the database."""

    channel_layer = _cross_process_channel_layer(get_channel_layer())
    channel_name = None
    group_name = f"run-{run_id}"
    if channel_layer is not None:
        channel_name = await channel_layer.new_channel("run-stream.")
        await channel_layer.group_add(group_name, channel_name)

    cursor = after
    last_write = time.monotonic()
    try:
        while True:
            try:
                events = await _load_event_batch(
                    user=user,
                    organization_id=organization_id,
                    run_id=run_id,
                    after=cursor,
                    limit=batch_size,
                )
            except StreamAccessLost:
                return

            if events:
                for event in events:
                    cursor = event.sequence
                    last_write = time.monotonic()
                    yield encode_event(event)
                    if event.type in TERMINAL_EVENT_TYPES:
                        return
                # Drain the factual database before waiting on notifications.
                if len(events) == batch_size:
                    continue

            elapsed = time.monotonic() - last_write
            wait_seconds = (
                min(poll_interval, max(0.0, heartbeat_interval - elapsed))
                if channel_name is None
                else max(0.0, heartbeat_interval - elapsed)
            )
            if channel_name is None:
                await asyncio.sleep(wait_seconds)
            else:
                try:
                    await asyncio.wait_for(
                        channel_layer.receive(channel_name),
                        timeout=wait_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

            if time.monotonic() - last_write >= heartbeat_interval:
                last_write = time.monotonic()
                yield b": keep-alive\n\n"
    finally:
        if channel_name is not None:
            await channel_layer.group_discard(group_name, channel_name)
