import React, { useEffect, useState } from 'react';
import { Button, Input, Radio } from 'antd';
import type { AgentQuestion } from '@/entities/run';

const OTHER_VALUE = '__other__';

interface AgentQuestionCardProps {
  question: AgentQuestion;
  onAnswer: (answer: { text?: string; selections?: string[] }) => Promise<void>;
  onCancel: () => Promise<void>;
}

const AgentQuestionCard: React.FC<AgentQuestionCardProps> = ({ question, onAnswer, onCancel }) => {
  const [selection, setSelection] = useState('');
  const [customText, setCustomText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setSelection('');
    setCustomText('');
  }, [question]);

  const submit = async () => {
    const isOther = selection === OTHER_VALUE;
    if (!selection || (isOther && !customText.trim())) return;
    setSubmitting(true);
    try {
      await onAnswer({
        text: isOther ? customText.trim() : '',
        selections: isOther ? [] : [selection],
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="agent-question-card">
      <div className="agent-question-eyebrow">
        {question.kind === 'permission' ? '工具权限确认' : question.header || 'Agent 提问'}
      </div>
      <div className="agent-question-title">{question.question}</div>
      {question.options.length > 0 && (
        <Radio.Group
          className="agent-question-options"
          value={selection}
          onChange={(event) => setSelection(event.target.value)}
        >
          {question.options.map((option) => (
            <Radio key={option.value} value={option.value}>
              <span>{option.label}</span>
              {option.description && (
                <span className="agent-question-option-description">{option.description}</span>
              )}
            </Radio>
          ))}
          {question.kind === 'question' && (
            <Radio value={OTHER_VALUE}>
              <span>Other</span>
              <span className="agent-question-option-description">输入自定义回答</span>
            </Radio>
          )}
        </Radio.Group>
      )}
      {selection === OTHER_VALUE && (
        <Input.TextArea
          value={customText}
          onChange={(event) => setCustomText(event.target.value)}
          placeholder="请输入自定义回答"
          autoFocus
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
      )}
      <div className="agent-question-actions">
        <Button danger onClick={() => void onCancel()} disabled={submitting}>取消任务</Button>
        <Button
          type="primary"
          onClick={() => void submit()}
          loading={submitting}
          disabled={!selection || (selection === OTHER_VALUE && !customText.trim())}
        >
          提交回答
        </Button>
      </div>
    </div>
  );
};

export default AgentQuestionCard;
