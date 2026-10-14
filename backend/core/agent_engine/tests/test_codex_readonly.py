from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.agent_engine.adapters.codex import CodexAdapter, _AppServerSdk, _AppServerCodex


@pytest.mark.parametrize('full_disk', [False, True])
def test_native_readonly_session_sets_restricted_roots_and_disables_external_tools(tmp_path, full_disk):
    transport = MagicMock(input_request=None)
    def request(method, params):
        if method == 'config/read':
            return {'config': {'mcp_servers': {'external.server': {'enabled': True}}}}
        if method == 'thread/start':
            return {'thread': {'id': 'thread'}, 'model': 'configured',
                'activePermissionProfile': {'id': params['permissions']}}
        return {'turn': {'id': 'turn'}}
    transport.request.side_effect = request
    transport.next_notification.return_value = {'method': 'turn/completed',
        'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}
    with patch('core.agent_engine.adapters.codex._AppServerTransport', return_value=transport):
        client = _AppServerCodex(codex_bin=Path('codex'))
    adapter = CodexAdapter()
    with patch.object(adapter, '_client', return_value=(_AppServerSdk, client)):
        result = adapter.complete([{'role': 'user', 'content': 'Explore'}], working_directory=str(tmp_path),
            read_only_paths=[str(tmp_path)], read_only_full_disk=full_disk, permission_mode='default',
            thread_config={'features.apps': True, 'web_search': 'live',
                'mcp_servers.external.server.enabled': True, 'mcp_servers': {'injected': {'command': 'external'}}})
    assert result.success
    calls = {call.args[0]: call.args[1] for call in transport.request.call_args_list}
    assert 'sandbox' not in calls['thread/start']
    profile = calls['thread/start']['permissions']
    assert calls['thread/start']['approvalPolicy'] == 'never'
    assert calls['thread/start']['config'] == {
        'features.apps': False, 'web_search': 'disabled', 'mcp_servers': {'external.server': {'enabled': False}},
        'plugins': {}, 'permissions': {profile: {
            'filesystem': {':root': 'read'} if full_disk else {':minimal': 'read', str(tmp_path): 'read'},
            'network': {'enabled': False}}}}
    assert calls['config/read']['cwd'] == str(tmp_path)
    assert 'sandboxPolicy' not in calls['turn/start']
    transport.close.assert_called_once()


@pytest.mark.parametrize('options', [{'read_only_paths': []}, {'read_only_paths': ['relative']},
    {'permission_mode': 'allow_all'}, {'thread_id': 'old-thread'},
    {'read_only_full_disk': 'true'}, {'read_only_paths': None, 'read_only_full_disk': True}])
def test_readonly_mode_cannot_silently_widen_access(tmp_path, options):
    adapter = CodexAdapter()
    with patch.object(adapter, '_client') as client:
        with pytest.raises(ValueError):
            adapter.complete([], **{'read_only_paths': [str(tmp_path)], **options})
    client.assert_not_called()


def test_unsupported_permission_profile_never_starts_model_turn(tmp_path):
    transport = MagicMock(input_request=None)
    transport.request.side_effect = [{'config': {}}, {'thread': {'id': 'thread'}}]
    with patch('core.agent_engine.adapters.codex._AppServerTransport', return_value=transport):
        client = _AppServerCodex(codex_bin=Path('codex'))
    adapter = CodexAdapter()
    with patch.object(adapter, '_client', return_value=(_AppServerSdk, client)):
        with pytest.raises(RuntimeError, match='permissions profile'):
            adapter.complete([], working_directory=str(tmp_path), read_only_paths=[str(tmp_path)])
    assert [call.args[0] for call in transport.request.call_args_list] == ['config/read', 'thread/start']
    transport.close.assert_called_once()
