import { describe, expect, it } from 'vitest';

import {
  validateWorkflowInput,
  workflowInputDefaults,
  workflowInputFields,
  workflowInputSourceOptions,
} from '../workflowInputSchema';


const schema = {
  type: 'object' as const,
  properties: {
    text: {
      type: 'string' as const,
      title: '原始文本',
      description: '需要分发的内容',
      minLength: 3,
      'x-control': 'textarea' as const,
    },
    copies: { type: 'number' as const, title: '份数', default: 2, minimum: 1 },
  },
  required: ['text'],
  additionalProperties: false,
};

describe('workflow input schema', () => {
  it('converts JSON Schema properties into ordered run fields', () => {
    expect(workflowInputFields(schema)).toMatchObject([
      { key: 'text', label: '原始文本', required: true, multiline: true },
      { key: 'copies', label: '份数', required: false, defaultValue: 2 },
    ]);
    expect(workflowInputSourceOptions(schema)).toEqual([
      { value: 'from:workflow.input.text', label: '工作流输入 · 原始文本' },
      { value: 'from:workflow.input.copies', label: '工作流输入 · 份数' },
    ]);
  });

  it('builds defaults and returns field-level validation errors', () => {
    const fields = workflowInputFields(schema);
    expect(workflowInputDefaults(fields)).toEqual({ copies: 2 });
    expect(validateWorkflowInput(fields, { text: 'a', copies: 0 })).toEqual({
      text: '原始文本至少需要 3 个字符',
      copies: '份数不能小于 1',
    });
    expect(validateWorkflowInput(fields, { text: '可分发文本', copies: 1 })).toEqual({});
  });
});
