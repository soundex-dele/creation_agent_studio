"""Strict, shared file-transfer wire schema. No filesystem access here."""
import re

MAX_FILE_SIZE = 2 * 1024**3
FILE_CHUNK = 256 * 1024


def validate_file_request(method, path, query, body):
    if len(query) != len(dict(query)):
        raise ValueError('Duplicate file query')
    if path.endswith('/read/'):
        if (set(dict(query)) != {'offset', 'length', 'stream_id'}
                or not re.fullmatch('[0-9a-f]{32}', dict(query).get('stream_id', ''))
                or any(not v.isascii() or not v.isdecimal() for k, v in query if k != 'stream_id')):
            raise ValueError('Invalid download range')
        values = {k: int(v) for k, v in query if k != 'stream_id'}
        if not 0 <= values['offset'] <= MAX_FILE_SIZE or not 1 <= values['length'] <= FILE_CHUNK:
            raise ValueError('Invalid download range')
    elif query:
        raise ValueError('File queries are not allowed')
    if method == 'GET':
        if body is not None:
            raise ValueError('File reads do not accept a body')
        return
    if not isinstance(body, dict):
        raise ValueError('A JSON object is required')
    action = path.strip('/').split('/')[-1]
    fields = {'list': {'path', 'cursor'}, 'uploads': {'path', 'name', 'size'}, 'downloads': {'path'},
              'chunk': {'offset', 'data', 'sha256'}, 'complete': set(), 'cancel': set(),
              'progress': {'offset', 'length', 'stream_id'}, 'open': {'stream_id'}, 'release': {'stream_id'}}
    if set(body) != fields[action]:
        raise ValueError('Invalid file request fields')
    if 'stream_id' in body and (not isinstance(body['stream_id'], str) or not re.fullmatch('[0-9a-f]{32}', body['stream_id'])):
        raise ValueError('Invalid download stream')
    for key in ('path', 'name', 'cursor'):
        if key in body and (not isinstance(body[key], str) or len(body[key]) > 4096 or '\x00' in body[key]):
            raise ValueError('Invalid file path or name')
    for key in ('size', 'offset', 'length'):
        if key in body and (type(body[key]) is not int or not 0 <= body[key] <= MAX_FILE_SIZE):
            raise ValueError('Invalid file size or offset')
    if action == 'progress' and not 0 <= body['length'] <= FILE_CHUNK:
        raise ValueError('Invalid progress length')
    if action == 'chunk' and (not isinstance(body['data'], str) or len(body['data']) > (FILE_CHUNK + 2) // 3 * 4
                              or not isinstance(body['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', body['sha256'])):
        raise ValueError('Invalid upload chunk')
