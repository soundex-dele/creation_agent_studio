import copy

import pytest

from ..owned import validate_report
from ..voice_style import compile_style, make_prompt
from .test_owned import content, style_features


def samples():
    return [dict(id='s', title='作品一', text='原文只说这些', usage='style'),
            dict(id='s2', title='作品二', text='第二篇原文说另一个问题', usage='style')]


def test_style_compiles_evidence_and_keeps_advice_out_of_prompt():
    report = dict(content=content(), style_features=style_features(), findings=[
        dict(category='improve', sample_id='s', quote='原文', text='建议加入三个金句')])
    report['content'].update(rules='不能采用的自由规则', examples='虚构示例', avoid='通用禁词表')
    result = validate_report(report, samples(), 'style')
    prompt = result['content']['prompt']
    assert '单篇候选' in prompt and '证据不足' in prompt
    assert '作品一' in prompt and '解释一个新观点时' in prompt
    for text in ['三个金句', '不能采用的自由规则', '虚构示例', '通用禁词表']:
        assert text not in prompt
    assert result['findings'][0]['text'] == '建议加入三个金句'
    assert result['findings'][1]['category'] == 'keep'


def test_cross_sample_label_requires_distinct_sources_and_bodies():
    features = style_features()
    evidence = features[0]['rules'][0]['evidence']
    evidence.append(dict(sample_id='s', quote='只说这些'))
    assert '单篇候选' in compile_style(features, samples())[0]['rules']
    evidence[-1] = dict(sample_id='s2', quote='原文')
    assert '跨样本共性' in compile_style(features, samples())[0]['rules']
    duplicates = samples()
    duplicates[1]['text'] = duplicates[0]['text']
    assert '跨样本共性' not in compile_style(features, duplicates)[0]['rules']


@pytest.mark.parametrize('change', ['content', 'exclude', 'empty', 'quote', 'source', 'missing_dimension', 'duplicate_dimension', 'missing_when'])
def test_style_rejects_unsupported_rules(change):
    features, source = style_features(), samples()
    if change in ['content', 'exclude']:
        source[0]['usage'] = change
    elif change == 'empty':
        source[0]['text'] = ''
    elif change == 'quote':
        features[0]['rules'][0]['evidence'][0]['quote'] = '并不存在'
    elif change == 'source':
        features[0]['rules'][0]['evidence'][0]['sample_id'] = 'foreign'
    elif change == 'missing_dimension':
        features.pop()
    elif change == 'duplicate_dimension':
        features[-1] = copy.deepcopy(features[0])
    else:
        del features[0]['rules'][0]['when']
    with pytest.raises(ValueError):
        compile_style(features, source)


def test_prompt_includes_boundaries_and_not_historical_positioning():
    value = content()
    value.update(current_positioning='历史不再适用', content_pillars='内容支柱正文', content_boundaries='边界正文')
    prompt = make_prompt(value)
    assert '【内容支柱】\n内容支柱正文' in prompt
    assert '【内容边界】\n边界正文' in prompt
    assert '历史不再适用' not in prompt
    assert '保留有意重复、跳跃转折和留白' in prompt
