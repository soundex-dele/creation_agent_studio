import { Button, Input, Select } from 'antd';
import { scenes, type PromptInput } from '@/services/promptMaster';

export function PromptForm({ value, onChange, disabled = false, submit, label }: {
  value: PromptInput; onChange: (value: PromptInput) => void; disabled?: boolean; submit: () => void; label: string;
}) {
  const field = <K extends keyof PromptInput>(key: K, next: PromptInput[K]) => onChange({ ...value, [key]: next });
  return <div className="pm-input-form">
    <label htmlFor="pm-topic">{value.mode === 'optimize' ? '粘贴已有提示词' : '你希望 AI 帮你完成什么？'}</label>
    <Input.TextArea id="pm-topic" value={value.mode === 'optimize' ? value.original : value.topic} disabled={disabled}
      maxLength={value.mode === 'optimize' ? 30000 : 20000} autoSize={{ minRows: 5, maxRows: 14 }} showCount
      placeholder={value.mode === 'optimize' ? '粘贴原文，我们会保留你的意图，补齐缺失的要求。' : '例如：帮我写一篇面向新手的露营装备选购文章，预算控制在 2000 元以内。'}
      onChange={(e) => field(value.mode === 'optimize' ? 'original' : 'topic', e.target.value)} />
    {value.mode === 'optimize' && <><label htmlFor="pm-objective">希望怎样改进？<span>（可选）</span></label>
      <Input.TextArea id="pm-objective" disabled={disabled} value={value.objective} maxLength={5000} autoSize={{ minRows: 2, maxRows: 6 }}
        placeholder="例如：让回答更具体，减少空泛建议，按表格输出。" onChange={(e) => field('objective', e.target.value)} /></>}
    <div className="pm-form-row"><div><label htmlFor="pm-scene">使用场景</label><Select id="pm-scene" disabled={disabled} value={value.scene}
      options={Object.entries(scenes).map(([key, text]) => ({ value: key, label: text }))} onChange={(v) => field('scene', v)} /></div>
      <div><label htmlFor="pm-language">提示词语言</label><Select id="pm-language" disabled={disabled} value={value.language}
        options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]} onChange={(v) => field('language', v)} /></div></div>
    <Button type="primary" size="large" disabled={disabled || !(value.mode === 'optimize' ? value.original : value.topic).trim()} onClick={submit}>{label}</Button>
  </div>;
}
