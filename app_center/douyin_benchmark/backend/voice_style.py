"""Evidence-backed style extraction, compiled into the existing editable text fields."""
import json
from pathlib import Path


PROMPT_SPEC = json.loads(Path(__file__).with_name('voice_prompt.json').read_text(encoding='utf-8'))
DIMENSIONS = ('叙述身份与读者关系', '开头方式', '推进逻辑', '句式与段落', '用词与修辞', '情绪与节奏', '结尾方式')


def make_prompt(content):
    sections = [(label, content.get(key, '')) for key, label in PROMPT_SPEC['fields']]
    return '\n\n'.join(f'【{label}】\n{text}' for label, text in sections + PROMPT_SPEC['sections'])


def compile_style(features, samples):
    """Do not trust model-provided confidence or free-form rules/avoid fields."""
    if not isinstance(features, list) or len(features) != len(DIMENSIONS):
        raise ValueError('文风分析必须覆盖七个维度，证据不足时使用空规则列表。')
    sources = {s['id']: s for s in samples if s['usage'] == 'style' and s['text'].strip()}
    by_dimension = {}
    rules, examples, avoid, findings = [], [], [], []
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get('dimension'), str) or feature['dimension'] not in DIMENSIONS:
            raise ValueError('文风维度无效。')
        dimension = feature['dimension']
        if dimension in by_dimension:
            raise ValueError('文风维度不能重复。')
        rows = feature.get('rules')
        if not isinstance(rows, list) or len(rows) > 2:
            raise ValueError('每个维度最多提炼两条有依据的规则。')
        by_dimension[dimension] = rows
    for dimension in DIMENSIONS:
        rows = by_dimension[dimension]
        if not rows:
            rules.append(f'【{dimension}】证据不足，不预设表达习惯。')
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                    or len(row[k]) > 600 for k in ('instruction', 'when', 'deviation')):
                raise ValueError('文风规则必须说明怎么写、何时使用及有依据的偏离。')
            refs = row.get('evidence')
            if not isinstance(refs, list) or not 1 <= len(refs) <= 3:
                raise ValueError('每条文风规则需要一至三个原文依据。')
            cited, texts, quotes = set(), set(), []
            for ref in refs:
                source = sources.get(ref['sample_id']) if isinstance(ref, dict) and isinstance(ref.get('sample_id'), str) else None
                quote = ref.get('quote') if isinstance(ref, dict) else None
                if not source or not isinstance(quote, str) or not quote.strip() or len(quote) > 600 or quote not in source['text']:
                    raise ValueError('文风规则只能引用代表风格正文中存在的连续原文。')
                cited.add(source['id'])
                texts.add(''.join(source['text'].split()))
                quotes.append((source, quote))
            # Duplicated imports of the same body cannot establish a cross-sample pattern.
            common = len(cited) >= 2 and len(texts) >= 2
            label = f'{dimension}{index} · ' + ('跨样本共性' if common else '单篇候选')
            text = f'【{label}】怎么写：{row["instruction"]}\n何时使用：{row["when"]}'
            rules.append(text + '\n原文依据：' + '、'.join(dict.fromkeys(s['title'] for s, _ in quotes)))
            avoid.append(f'【{label}】在上述适用条件下，避免：{row["deviation"]}')
            for source, quote in quotes:
                examples.append(f'【{label}｜{source["title"]}】\n{quote}')
                findings.append({'category': 'keep', 'text': text, 'sample_id': source['id'], 'quote': quote})
    result = dict(rules='\n\n'.join(rules), examples='\n\n'.join(examples), avoid='\n\n'.join(avoid))
    if any(len(v) > 20000 for v in result.values()):
        raise ValueError('文风规则过长，请精简规则和引用。')
    return result, findings


ANALYSIS_PROMPT = '''分析我自己的账号，区分历史定位、目标定位、受众推测和改善建议。
只从usage=style的正文提取实际表达习惯，content用途只参考内容，不学习风格，exclude不使用。
优先还原个人表达，不将有意重复、跳跃转折、留白当作缺点，不套用通用禁词表或爆款公式。
逐一分析七个维度：叙述身份与读者关系、开头方式、推进逻辑、句式与段落、用词与修辞、情绪与节奏、结尾方式。
每个维度最多两条规则，每条说明怎么写、何时使用、什么表达会偏离，以及1—3个连续原文依据。
跨样本共性需要至少两篇不同正文支持，只有单篇依据时是候选；证据不足时rules为空列表，禁止补造习惯。
instruction只描述观察到的习惯，不写改善建议；deviation必须是与该习惯对应的偏离，不是通用禁令。
改善建议只放findings的improve类别，不写入style_features或content的文风字段。
返回JSON：{"content":{"current_positioning":"历史定位（标题分析注明初步推测）",
"positioning":"建议目标定位","audience":"目标受众（推测）","content_pillars":"内容支柱",
"content_boundaries":"内容边界","rules":"","examples":"","avoid":""},
"style_features":[{"dimension":"上述七个维度之一","rules":[{"instruction":"怎么写",
"when":"适用条件","deviation":"有依据的风格偏离","evidence":[{"sample_id":"实际样本ID","quote":"连续原文"}]}]}],
"findings":[{"category":"positioning|improve","text":"结论或独立改善建议","sample_id":"实际样本ID","quote":"连续原文"}]}。
style_features需逐一包含七个维度；findings至少一项，最多20项；不编造经历、数据或原文。
仅定位模式时style_features返回空列表，rules、examples、avoid为空字符串，findings只分析定位。
'''
