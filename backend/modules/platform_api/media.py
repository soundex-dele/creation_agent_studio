"""HTTP byte ranges and bounded synchronous/asynchronous file streaming."""
import asyncio
import re

def byte_range(header, size):
    if not header:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or not size:
        raise ValueError("Invalid range")
    first, last = match.groups()
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError("Invalid suffix")
        return max(0, size - length), size - 1, True
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable range")
    return start, end, True


def stream_file(path, start, length):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


async def stream_file_async(path, start, length):
    # A sync iterator under Django ASGI is materialized in memory. Always give
    # ASGI an async iterator, and keep blocking disk reads off its event loop.
    handle = await asyncio.to_thread(path.open, "rb")
    try:
        await asyncio.to_thread(handle.seek, start)
        remaining = length
        while remaining:
            chunk = await asyncio.to_thread(handle.read, min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()
