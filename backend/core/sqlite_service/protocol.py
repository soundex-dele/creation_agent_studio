"""Length-framed JSON; never deserialize executable Python objects."""

import base64
import datetime
import json
import struct
import socket
import time

VERSION = 1
MAX_FRAME_BYTES = 64 * 1024 * 1024


def _encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return {"$type": type(value).__name__, "value": value.isoformat()}
    raise TypeError(f"Unsupported database wire value: {type(value).__name__}")


def _decode(value):
    if set(value) == {"$bytes"}:
        return base64.b64decode(value["$bytes"], validate=True)
    if set(value) == {"$type", "value"}:
        converter = {
            "datetime": datetime.datetime.fromisoformat,
            "date": datetime.date.fromisoformat,
            "time": datetime.time.fromisoformat,
        }.get(value["$type"])
        if converter:
            return converter(value["value"])
    return value


def _read(sock, size, *, deadline=None, stop_event=None):
    chunks = bytearray()
    while len(chunks) < size:
        if stop_event is not None and stop_event.is_set():
            raise EOFError("SQLite service is stopping")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("SQLite service session idle deadline exceeded")
        try:
            chunk = sock.recv(size - len(chunks))
        except socket.timeout:
            if stop_event is None:
                raise
            continue
        if not chunk:
            raise EOFError("SQLite service connection closed")
        chunks.extend(chunk)
    return chunks


def receive(sock, *, timeout=None, stop_event=None):
    deadline = time.monotonic() + timeout if timeout is not None else None
    options = {"deadline": deadline, "stop_event": stop_event}
    size = struct.unpack("!I", _read(sock, 4, **options))[0]
    if size > MAX_FRAME_BYTES:
        raise ValueError("SQLite service frame exceeds size limit")
    return json.loads(_read(sock, size, **options), object_hook=_decode)


def send(sock, value):
    data = json.dumps(value, default=_encode, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError("SQLite service frame exceeds size limit")
    sock.sendall(struct.pack("!I", len(data)) + data)
