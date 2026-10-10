import pytest

from ..exploration import explore


def test_model_can_continue_past_old_round_limit_even_after_every_chunk_is_read(settings):
    settings.REPO_EXPLAINER_ROUNDS = 1
    calls, stages = [], []
    def model(instruction, data):
        calls.append(data)
        assert data['方向'] == '使用场景'
        assert len(data['当前源码窗口']) == 1
        if len(calls) < 21:
            return {'action': 'read', 'path': 'README.md', 'notes': '已读e1，继续核对内容角度'}
        return {'action': 'finish', 'evidence_ids': ['e1']}
    selected, coverage = explore({'README.md': {'text': 'tool'}}, model, stages.append, '使用场景')
    assert len(calls) == 21
    assert coverage['exploration_rounds'] == 21 and coverage['chunks_read'] == 1
    assert not coverage['incomplete']
    assert selected['e1']['quote'] == 'tool'
    assert calls[-1]['上次动作结果']['already_read']
    assert calls[-1]['工作笔记'] == '已读e1，继续核对内容角度'
    assert any('第20轮' in stage for stage in stages)
    assert all('/3' not in stage for stage in stages)


def test_context_eviction_does_not_cap_total_exploration_or_lose_final_evidence(settings):
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 100
    files = {f'{i}.py': {'text': str(i) * 60} for i in range(4)}
    calls = []
    def model(instruction, data):
        assert sum(len(row['quote']) for row in data['当前源码窗口']) <= 100
        calls.append(data)
        if len(calls) <= 4:
            return {'action': 'read', 'path': f'{len(calls) - 1}.py'}
        assert [row['id'] for row in data['当前源码窗口']] == ['e4']
        assert data['累计已读片段数'] == 4
        return {'action': 'finish', 'evidence_ids': ['e1']}
    selected, coverage = explore(files, model, lambda _: None)
    assert coverage['characters_read'] == 240 > 100
    assert coverage['evidence_characters'] == 60
    assert selected['e1']['path'] == '0.py'


def test_directory_pagination_can_reach_files_beyond_initial_directory_window(settings):
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 100
    files = {f'src/{i:05}.py': {'text': ''} for i in range(6001)}
    files['src/06000.py']['text'] = 'x' * 60
    turn = 0
    def model(instruction, data):
        nonlocal turn
        turn += 1
        if turn == 1:
            assert len(data['上次动作结果']['files']) == 100
            assert data['文件总数'] == 6001
            return {'action': 'list', 'prefix': 'src/', 'offset': 6000}
        if turn == 2:
            assert data['上次动作结果']['files'] == ['src/06000.py']
            assert data['上次动作结果']['next_offset'] is None
            return {'action': 'read', 'path': 'src/06000.py'}
        return {'action': 'finish', 'evidence_ids': ['e1']}
    selected, coverage = explore(files, model, lambda _: None)
    assert selected['e1']['path'] == 'src/06000.py'
    assert coverage['files_read'] == 1 and coverage['files_total'] == 6001


def test_search_pagination_and_exact_line_read(settings):
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 12000
    files = {f'{i:02}.py': {'text': '\n'.join(['needle'] * 160)} for i in range(20)}
    turn = 0
    def model(instruction, data):
        nonlocal turn
        turn += 1
        if turn == 1:
            return {'action': 'search', 'query': 'needle'}
        if turn == 2:
            result = data['上次动作结果']
            assert result['total'] == 40 and len(result['matches']) == 30
            assert result['next_offset'] == 30
            return {'action': 'search', 'query': 'needle', 'offset': 30}
        if turn == 3:
            assert len(data['上次动作结果']['matches']) == 10
            assert data['上次动作结果']['next_offset'] is None
            return {'action': 'read', 'path': '19.py', 'start': 82}
        assert data['上次动作结果']['next_start'] is None
        return {'action': 'finish', 'evidence_ids': ['e40']}
    selected, _ = explore(files, model, lambda _: None)
    assert selected['e40']['start'] == 81 and selected['e40']['end'] == 160


@pytest.mark.parametrize('command', [
    {'action': 'read', 'path': '/etc/passwd'}, {'action': 'read', 'path': '../README.md'},
    {'action': 'read', 'path': 'README.md', 'start': False},
    {'action': 'read', 'path': 'README.md', 'start': 1000},
    {'action': 'finish', 'evidence_ids': ['fake']},
    {'action': 'list', 'offset': -1}, {'action': 'search', 'query': ''},
    {'action': 'execute', 'command': 'anything'}, {'action': 'read', 'notes': 'x' * 8001}, [],
])
def test_invalid_actions_return_feedback_for_model_to_recover(command):
    turn = 0
    def model(instruction, data):
        nonlocal turn
        turn += 1
        if turn == 1:
            return command
        assert data['上次动作结果']['error']
        return {'action': 'finish', 'evidence_ids': ['e1']}
    selected, coverage = explore({'README.md': {'text': 'tool'}}, model, lambda _: None)
    assert list(selected) == ['e1'] and coverage['exploration_rounds'] == 2


def test_final_evidence_must_be_read_and_fit_context_without_forcing_an_early_stop(settings):
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 100
    commands = iter([
        {'action': 'search', 'query': 'py'},
        {'action': 'finish', 'evidence_ids': ['e1']},  # Search metadata isn't a read.
        {'action': 'read', 'path': 'a.py'},
        {'action': 'read', 'path': 'b.py'},
        {'action': 'finish', 'evidence_ids': ['e1', 'e2']},  # 120 characters exceed this context.
        {'action': 'search', 'query': 'nonexistent'},
        {'action': 'finish', 'evidence_ids': ['e1']},
    ])
    observations = []
    def model(instruction, data):
        observations.append(data['上次动作结果'])
        return next(commands)
    selected, coverage = explore({'a.py': {'text': 'a' * 60}, 'b.py': {'text': 'b' * 60}}, model, lambda _: None)
    assert '已经读取' in observations[2]['error']
    assert '上下文容量' in observations[5]['error']
    assert observations[6]['total'] == 0
    assert list(selected) == ['e1'] and coverage['exploration_rounds'] == 7


def test_cancellation_interrupts_an_open_ended_exploration():
    calls = []
    def model(instruction, data):
        calls.append(data)
        return {'action': 'search', 'query': 'notfound'}
    def check():
        if len(calls) >= 8:
            raise InterruptedError('用户取消')
    with pytest.raises(InterruptedError, match='用户取消'):
        explore({'README.md': {'text': 'tool'}}, model, lambda _: None, check=check)
    assert len(calls) == 8


def test_provider_failure_is_not_swallowed_as_tool_feedback():
    def model(instruction, data):
        raise RuntimeError('模型请求超时')
    with pytest.raises(RuntimeError, match='超时'):
        explore({'README.md': {'text': 'tool'}}, model, lambda _: None)
