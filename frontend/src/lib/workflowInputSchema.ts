import type {
  WorkflowInputProperty,
  WorkflowInputSchema,
  WorkflowInputValue,
  WorkflowRunInputField,
} from '@/types';


export const emptyWorkflowInputSchema = (): WorkflowInputSchema => ({
  type: 'object',
  properties: {},
  required: [],
  additionalProperties: false,
});

export const workflowInputFields = (
  schema?: WorkflowInputSchema,
): WorkflowRunInputField[] => {
  const required = new Set(schema?.required || []);
  return Object.entries(schema?.properties || {}).map(([key, definition]) => {
    const options = definition.type === 'array'
      ? definition.items?.enum?.map((value) => ({ value, label: value }))
      : definition.enum?.map((value) => ({ value, label: String(value) }));
    return {
      key,
      label: definition.title || key,
      description: definition.description,
      placeholder: definition['x-placeholder'],
      type: definition.type,
      required: required.has(key),
      defaultValue: definition.default,
      options,
      multiline: definition['x-control'] === 'textarea',
      minLength: definition.minLength,
      maxLength: definition.maxLength,
      minimum: definition.minimum,
      maximum: definition.maximum,
    };
  });
};

export const workflowInputDefaults = (
  fields: WorkflowRunInputField[],
): Record<string, WorkflowInputValue> => Object.fromEntries(
  fields.flatMap((field) => (
    field.defaultValue === undefined ? [] : [[field.key, field.defaultValue]]
  )),
);

export const validateWorkflowInput = (
  fields: WorkflowRunInputField[],
  values: Record<string, WorkflowInputValue>,
): Record<string, string> => {
  const errors: Record<string, string> = {};
  fields.forEach((field) => {
    const value = values[field.key];
    const empty = value === undefined || value === ''
      || (Array.isArray(value) && value.length === 0);
    if (field.required && empty) {
      errors[field.key] = `请填写${field.label}`;
      return;
    }
    if (empty) return;
    if (typeof value === 'string') {
      if (field.minLength !== undefined && value.length < field.minLength) {
        errors[field.key] = `${field.label}至少需要 ${field.minLength} 个字符`;
      } else if (field.maxLength !== undefined && value.length > field.maxLength) {
        errors[field.key] = `${field.label}不能超过 ${field.maxLength} 个字符`;
      }
    }
    if (typeof value === 'number') {
      if (field.minimum !== undefined && value < field.minimum) {
        errors[field.key] = `${field.label}不能小于 ${field.minimum}`;
      } else if (field.maximum !== undefined && value > field.maximum) {
        errors[field.key] = `${field.label}不能大于 ${field.maximum}`;
      }
    }
  });
  return errors;
};

export const workflowInputSourceOptions = (schema?: WorkflowInputSchema) => (
  workflowInputFields(schema).map((field) => ({
    value: `from:workflow.input.${field.key}`,
    label: `工作流输入 · ${field.label}`,
  }))
);

export const workflowInputProperty = (
  control: 'text' | 'textarea' | 'number' | 'boolean',
  title: string,
): WorkflowInputProperty => {
  if (control === 'number') return { type: 'number', title };
  if (control === 'boolean') return { type: 'boolean', title, default: false };
  return {
    type: 'string',
    title,
    'x-control': control,
  };
};
