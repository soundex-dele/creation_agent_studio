import React, { useEffect, useState } from 'react';
import { Button, Input, Radio } from 'antd';
import type { AgentQuestion } from '@/entities/run';

const OTHER_VALUE = '__other__';

interface AgentQuestionCardProps {
  question: AgentQuestion;
  onAnswer: (answer: {
    text?: string;
    selections?: string[];
    answers?: Record<string, { answers: string[] }>;
  }) => Promise<void>;
  onCancel: () => Promise<void>;
}

const AgentQuestionCard: React.FC<AgentQuestionCardProps> = ({ question, onAnswer, onCancel }) => {
  const [values, setValues] = useState<Record<string, string>>({});
  const [customValues, setCustomValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const questions = question.questions?.length ? question.questions : [question];

  useEffect(() => {
    setValues({});
    setCustomValues({});
  }, [question]);

  const resolvedAnswer = (id: string) => (
    values[id] === OTHER_VALUE ? customValues[id]?.trim() ?? '' : values[id]?.trim() ?? ''
  );
  const complete = questions.every((item) => Boolean(resolvedAnswer(item.id)));

  const submit = async () => {
    if (!complete) return;
    setSubmitting(true);
    try {
      if (question.kind === 'permission') {
        const value = resolvedAnswer(questions[0].id);
        await onAnswer({
          text: values[questions[0].id] === OTHER_VALUE ? value : '',
          selections: values[questions[0].id] === OTHER_VALUE ? [] : [value],
        });
      } else {
        const answers = Object.fromEntries(
          questions.map((item) => [item.id, { answers: [resolvedAnswer(item.id)] }]),
        );
        const single = questions.length === 1 ? resolvedAnswer(questions[0].id) : '';
        await onAnswer({
          text: questions.length === 1 && values[questions[0].id] === OTHER_VALUE
            ? single
            : undefined,
          selections: questions.length === 1 && values[questions[0].id] !== OTHER_VALUE
            ? [single]
            : undefined,
          answers,
        });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="agent-question-card">
      <div className="agent-question-eyebrow">
        {question.kind === 'permission' ? '工具权限确认' : 'Agent 提问'}
      </div>
      {questions.map((item, index) => {
        const showOther = question.kind === 'question' && (item.isOther ?? true);
        const selection = values[item.id] ?? '';
        return (
          <div className="agent-question-item" key={item.id}>
            {(questions.length > 1 || item.header) && (
              <div className="agent-question-header">
                {questions.length > 1 ? `${index + 1}. ` : ''}{item.header}
              </div>
            )}
            <div className="agent-question-title">{item.question}</div>
            {item.options.length > 0 ? (
              <Radio.Group
                className="agent-question-options"
                value={selection}
                onChange={(event) => setValues((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))}
              >
                {item.options.map((option) => (
                  <Radio key={option.value} value={option.value}>
                    <span>{option.label}</span>
                    {option.description && (
                      <span className="agent-question-option-description">{option.description}</span>
                    )}
                  </Radio>
                ))}
                {showOther && (
                  <Radio value={OTHER_VALUE}>
                    <span>Other</span>
                    <span className="agent-question-option-description">输入自定义回答</span>
                  </Radio>
                )}
              </Radio.Group>
            ) : item.isSecret ? (
              <Input.Password
                value={selection}
                onChange={(event) => setValues((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))}
                placeholder="请输入回答"
              />
            ) : (
              <Input.TextArea
                value={selection}
                onChange={(event) => setValues((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))}
                placeholder="请输入回答"
                autoSize={{ minRows: 1, maxRows: 4 }}
              />
            )}
            {selection === OTHER_VALUE && (
              <Input.TextArea
                value={customValues[item.id] ?? ''}
                onChange={(event) => setCustomValues((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))}
                placeholder="请输入自定义回答"
                autoFocus
                autoSize={{ minRows: 1, maxRows: 4 }}
              />
            )}
          </div>
        );
      })}
      <div className="agent-question-actions">
        <Button danger onClick={() => void onCancel()} disabled={submitting}>取消任务</Button>
        <Button
          type="primary"
          onClick={() => void submit()}
          loading={submitting}
          disabled={!complete}
        >
          提交回答
        </Button>
      </div>
    </div>
  );
};

export default AgentQuestionCard;
