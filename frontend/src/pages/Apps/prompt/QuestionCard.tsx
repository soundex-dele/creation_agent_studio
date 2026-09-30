import { Checkbox, Input, Radio } from 'antd';
import { type Question, type Answers } from '@/services/promptMaster';

export function QuestionCard({ question: q, index, value, disabled, onChange }: {
  question: Question; index: number; value: Answers[string] | undefined; disabled: boolean; onChange: (value: Answers[string]) => void;
}) {
  const text = typeof value === 'string' && !q.options.some((o) => o.value === value) ? value : '';
  return <fieldset className="pm-question" disabled={disabled}><legend><span>{String(index + 1).padStart(2, '0')}</span>{q.label}</legend>
    {q.help && <p>{q.help}</p>}
    {q.type === 'single_choice' && <Radio.Group aria-label={q.label} disabled={disabled} value={typeof value === 'string' ? value : undefined} onChange={(e) => onChange(e.target.value)}>
      {q.options.map((o) => <Radio.Button key={o.value} value={o.value}>{o.label}</Radio.Button>)}
    </Radio.Group>}
    {q.type === 'multi_choice' && <Checkbox.Group aria-label={q.label} disabled={disabled} options={q.options} value={Array.isArray(value) ? value : []} onChange={(v) => onChange(v as string[])} />}
    <Input.TextArea aria-label={`${q.label}：自由填写`} disabled={disabled} value={text} maxLength={5000}
      autoSize={{ minRows: 2, maxRows: 6 }} placeholder={q.type === 'text' ? '写下你的想法，或使用下方推荐' : '也可以自由填写（替代上方选择）'} onChange={(e) => onChange(e.target.value)} />
    <Checkbox disabled={disabled} checked={value === null} onChange={(e) => onChange(e.target.checked ? null : '')}>帮我决定</Checkbox>
    <small>推荐：{q.recommended}</small>
  </fieldset>;
}
