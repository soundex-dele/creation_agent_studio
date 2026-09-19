export interface StudyTutorExtraSection {
  key: string;
  label: string;
  items: string[];
}

export interface StudyTutorAnswer {
  subject: string;
  recognizedProblem: string;
  knowledgePoints: string[];
  hintLevel: number | null;
  hint: string;
  steps: string[];
  finalAnswer: string;
  validationStatus: string;
  variantProblem: string;
  variantAnswer: string;
  extraSections: StudyTutorExtraSection[];
}

const knownKeys = new Set([
  'subject',
  'recognized_problem',
  'recognizedProblem',
  'knowledge_points',
  'knowledgePoints',
  'hint_level',
  'hintLevel',
  'hint',
  'steps',
  'final_answer',
  'finalAnswer',
  'validation_status',
  'validationStatus',
  'variant_problem',
  'variantProblem',
  'variant_answer',
  'variantAnswer',
  'strategy_version',
]);

const fieldLabels: Record<string, string> = {
  analysis: '思路分析',
  explanation: '补充讲解',
  method: '解题方法',
  key_points: '关键要点',
  common_mistakes: '易错点',
  checks: '检查方法',
  next_steps: '下一步建议',
};

function stripJsonFence(content: string) {
  const trimmed = content.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1].trim() : trimmed;
}

function readableItems(value: unknown): string[] {
  if (value === null || value === undefined || value === '') return [];
  if (typeof value === 'string') return value.trim() ? [value.trim()] : [];
  if (typeof value === 'number' || typeof value === 'boolean') return [String(value)];
  if (Array.isArray(value)) return value.flatMap(readableItems);
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) return [];
    return [entries.map(([key, nested]) => {
      const text = readableItems(nested).join('；');
      return text ? `${humanizeKey(key)}：${text}` : '';
    }).filter(Boolean).join('；')];
  }
  return [];
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const text = readableItems(value)[0];
    if (text) return text;
  }
  return '';
}

function humanizeKey(key: string) {
  if (fieldLabels[key]) return fieldLabels[key];
  return key
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim();
}

function unwrapParsedValue(value: unknown): unknown {
  if (typeof value === 'string') {
    try {
      return JSON.parse(stripJsonFence(value));
    } catch {
      return value;
    }
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (Object.keys(record).length === 1 && 'result' in record) {
      return unwrapParsedValue(record.result);
    }
  }
  return value;
}

export function looksLikeStudyTutorJson(content: string) {
  const trimmed = content.trimStart();
  return trimmed.startsWith('{') || /^```json\b/i.test(trimmed);
}

export function parseStudyTutorAnswer(content: string): StudyTutorAnswer | null {
  let parsed: unknown;
  try {
    parsed = unwrapParsedValue(JSON.parse(stripJsonFence(content)));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;

  const record = parsed as Record<string, unknown>;
  const hintLevelValue = record.hint_level ?? record.hintLevel;
  const hintLevel = typeof hintLevelValue === 'number'
    ? hintLevelValue
    : typeof hintLevelValue === 'string' && hintLevelValue.trim()
      ? Number(hintLevelValue)
      : null;
  const extraSections = Object.entries(record)
    .filter(([key, value]) => !knownKeys.has(key) && readableItems(value).length > 0)
    .map(([key, value]) => ({
      key,
      label: humanizeKey(key),
      items: readableItems(value),
    }));

  return {
    subject: firstText(record.subject),
    recognizedProblem: firstText(record.recognized_problem, record.recognizedProblem),
    knowledgePoints: readableItems(record.knowledge_points ?? record.knowledgePoints),
    hintLevel: Number.isFinite(hintLevel) ? hintLevel : null,
    hint: firstText(record.hint),
    steps: readableItems(record.steps),
    finalAnswer: firstText(record.final_answer, record.finalAnswer),
    validationStatus: firstText(record.validation_status, record.validationStatus),
    variantProblem: firstText(record.variant_problem, record.variantProblem),
    variantAnswer: firstText(record.variant_answer, record.variantAnswer),
    extraSections,
  };
}
