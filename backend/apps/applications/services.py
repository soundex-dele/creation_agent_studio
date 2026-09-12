import re
from typing import Any

from rest_framework.exceptions import ValidationError


_PLACEHOLDER = re.compile(r'\{([a-zA-Z][a-zA-Z0-9_-]*)\}')


def compose_guided_prompt(prompt: dict, answers: dict[str, Any], *, application_id: int) -> dict:
    normalized: dict[str, Any] = {}
    for question in prompt.get('questions', []):
        value = answers.get(question['key'], question.get('default_value'))
        empty = value is None or value == '' or value == []
        if question.get('required') and empty:
            raise ValidationError({question['key']: f"{question['label']}为必填项。"})
        if empty:
            normalized[question['key']] = ''
            continue
        if question['type'] in ('single_choice', 'multi_choice'):
            allowed = {
                option['value']: option['label']
                for option in question.get('options', [])
            }
            values = value if isinstance(value, list) else [value]
            if any(str(item) not in allowed for item in values):
                raise ValidationError({question['key']: '包含无效选项。'})
            labels = [allowed[str(item)] for item in values]
            normalized[question['key']] = (
                labels if question['type'] == 'multi_choice' else labels[0])
        else:
            normalized[question['key']] = value

    def replace(match):
        value = normalized.get(match.group(1), '')
        return '、'.join(str(item) for item in value) if isinstance(value, list) else str(value)

    content = _PLACEHOLDER.sub(replace, prompt['prompt_template'])
    content = '\n'.join(
        line.rstrip() for line in content.splitlines()
        if line.rstrip().rstrip('：:').strip()
    ).strip()
    return {
        'prompt': content,
        'normalized_answers': normalized,
        'guided_prompt_id': str(prompt.get('id') or prompt['key']),
        'application_id': application_id,
    }
