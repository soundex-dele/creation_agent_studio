import type { AnswerCard, StudySubject } from '@/types/studyWithMethod';


export const answerCardCurricula: Partial<Record<StudySubject, string>> = {
  math: 'xj-math-current',
  history: 'pep-history-current',
};

export function answeredQuestionCount(card: AnswerCard | null, answers: Record<string, string>) {
  return card?.questions.filter((question) => Boolean(answers[question.id])).length || 0;
}

export function buildAnswerSubmission(card: AnswerCard, answers: Record<string, string>) {
  const missing = card.questions.find((question) => !answers[question.id]);
  if (missing) throw new Error('请完成答题卡中的全部题目。');
  return card.questions.map((question) => ({
    question_id: question.id,
    selected_option_id: answers[question.id],
  }));
}
