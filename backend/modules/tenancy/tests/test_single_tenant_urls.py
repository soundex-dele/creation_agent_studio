from uuid import UUID

import pytest
from django.urls import resolve


@pytest.mark.parametrize('resource', [
    'creator-profiles', 'inspirations', 'ideas', 'publications',
    'subscriptions', 'notifications', 'digests',
])
@pytest.mark.parametrize('record_id', [None, UUID('00000000-0000-0000-0000-000000000001')])
def test_record_alias_preserves_route_parameters(resource, record_id):
    suffix = f'/{record_id}' if record_id else ''
    match = resolve(f'/api/v1/applications/31/douyin-benchmark/{resource}{suffix}')

    expected = {'application_id': 31, 'resource': resource}
    if record_id:
        expected['record_id'] = record_id
    assert match.kwargs == expected
