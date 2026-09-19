import { describe, expect, it } from 'vitest';

import type { AnswerCard } from '@/types/studyWithMethod';
import {
  answerCardCurricula,
  answeredQuestionCount,
  buildAnswerSubmission,
} from '../answerCard';


const card = {
  questions: [
    { id: 'q1', stem: '求 $f(x)$ 的定义域', options: [] },
    { id: 'q2', stem: '判断命题真假', options: [] },
  ],
} as unknown as AnswerCard;

describe('knowledge answer card', () => {
  it('only enables the two bundled curricula', () => {
    expect(answerCardCurricula).toEqual({
      math: 'xj-math-current',
      history: 'pep-history-current',
    });
  });

  it('counts selected questions and builds the server grading payload', () => {
    expect(answeredQuestionCount(card, { q1: 'B' })).toBe(1);
    expect(buildAnswerSubmission(card, { q1: 'B', q2: 'D' })).toEqual([
      { question_id: 'q1', selected_option_id: 'B' },
      { question_id: 'q2', selected_option_id: 'D' },
    ]);
  });

  it('rejects submission while any question is unanswered', () => {
    expect(() => buildAnswerSubmission(card, { q1: 'A' })).toThrow(
      '请完成答题卡中的全部题目。',
    );
  });
});
