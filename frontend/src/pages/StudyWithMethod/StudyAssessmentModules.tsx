import { useEffect, useMemo, useState } from 'react';
import { Button, Empty, Progress, Skeleton, Tag, message } from 'antd';
import { BarChart3, CheckCircle2, ClipboardCheck, RotateCcw } from 'lucide-react';

import {
  createDiagnostic,
  generateWeeklyQuiz,
  listWeeklyQuizzes,
  submitDiagnostic,
  submitWeeklyQuiz,
} from '@/services/studyWithMethod';
import type {
  DiagnosticAssessment,
  ReviewRating,
  StudySubject,
  StudyTrend,
  WeeklyQuiz,
} from '@/types/studyWithMethod';

const subjectLabels: Record<StudySubject, string> = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', politics: '思想政治', history: '历史', geography: '地理',
};

function errorText(error: unknown, fallback: string) {
  if (typeof error === 'object' && error && 'response' in error) {
    const data = (error as { response?: { data?: Record<string, unknown> } }).response?.data;
    if (data) return String(data.detail || Object.values(data)[0] || fallback);
  }
  return error instanceof Error ? error.message : fallback;
}

export function StudyTrendSummary({ sevenDay, thirtyDay }: {
  sevenDay: StudyTrend;
  thirtyDay: StudyTrend;
}) {
  const metrics = [
    { label: '7 日计划完成', value: `${sevenDay.completion_rate}%`, hint: `${sevenDay.task_completed}/${sevenDay.task_total} 项` },
    { label: '7 日练习正确', value: `${sevenDay.correct_rate}%`, hint: `${sevenDay.attempt_total} 次作答` },
    { label: '30 日复习', value: String(thirtyDay.reviews_completed), hint: '次有效复习' },
    { label: '稳定掌握', value: String(thirtyDay.mastered_count), hint: '个知识点' },
  ];
  return <section className="swm-trend-summary" aria-labelledby="swm-trend-title">
    <div className="swm-section-title"><div><span className="swm-eyebrow">基于真实学习记录</span><h2 id="swm-trend-title">学习趋势</h2></div><BarChart3 aria-hidden="true" /></div>
    <div className="swm-trend-grid">{metrics.map((item) => <article key={item.label}>
      <span>{item.label}</span><strong>{item.value}</strong><small>{item.hint}</small>
    </article>)}</div>
  </section>;
}

export function DiagnosticPanel({ initial, subjects, organizationId, applicationId, onCompleted }: {
  initial: DiagnosticAssessment | { status: 'not_started' };
  subjects: StudySubject[];
  organizationId: string;
  applicationId: string;
  onCompleted: () => Promise<void>;
}) {
  const [assessment, setAssessment] = useState<DiagnosticAssessment | null>(
    initial.status === 'not_started' ? null : initial,
  );
  const [answers, setAnswers] = useState<Record<string, string | number>>({});
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const question = assessment?.questions[index];
  const answered = assessment?.questions.filter((item) => answers[item.id] !== undefined).length || 0;

  if (!assessment || assessment.status !== 'in_progress') {
    const completed = assessment?.status === 'completed';
    return <section className="swm-diagnostic-card" aria-labelledby="swm-diagnostic-title">
      <div><ClipboardCheck size={28} aria-hidden="true" /><span className="swm-eyebrow">让计划更懂你</span><h2 id="swm-diagnostic-title">{completed ? '学习诊断已完成' : '先做一次轻量诊断'}</h2>
        <p>{completed ? '诊断结果已用于掌握度和未来七天计划。' : '重点科约 4–8 题；无题库学科使用掌握度自评，也可以暂时跳过。'}</p></div>
      {completed && <div className="swm-diagnostic-results">{assessment.results.map((item) => <Tag key={item.id} color={item.score >= 60 ? 'green' : 'orange'}>{subjectLabels[item.subject]} · {item.knowledge_point_name} {item.score}%</Tag>)}</div>}
      <div className="swm-battle-actions">
        {!completed && <Button onClick={async () => {
          setBusy(true);
          try { await createDiagnostic(organizationId, applicationId, subjects, true); await onCompleted(); }
          catch (error) { message.error(errorText(error, '暂时无法跳过诊断')); }
          finally { setBusy(false); }
        }}>稍后再做</Button>}
        <Button type="primary" loading={busy} onClick={async () => {
          setBusy(true);
          try {
            const created = await createDiagnostic(organizationId, applicationId, subjects);
            setAssessment(created); setAnswers({}); setIndex(0);
          } catch (error) { message.error(errorText(error, '创建诊断失败')); }
          finally { setBusy(false); }
        }}>{completed ? '重新诊断' : '开始诊断'}</Button>
      </div>
    </section>;
  }

  if (!question) return <Empty description="诊断中没有可用题目" />;
  return <section className="swm-diagnostic-stage" aria-labelledby="swm-diagnostic-question">
    <div className="swm-module-progress"><span>{subjectLabels[question.subject]} · {question.knowledge_point_name}</span><span>{answered}/{assessment.questions.length}</span></div>
    <Progress percent={Math.round((answered / assessment.questions.length) * 100)} showInfo={false} />
    <h2 id="swm-diagnostic-question">{question.stem}</h2>
    {question.question_type === 'objective' ? <div className="swm-answer-options">{question.options.map((option) => <button
      type="button" key={option.id} className={answers[question.id] === option.id ? 'selected' : ''}
      aria-pressed={answers[question.id] === option.id}
      onClick={() => setAnswers((current) => ({ ...current, [question.id]: option.id }))}
    ><b>{option.id}</b><span>{option.text}</span></button>)}</div> : <div className="swm-rating-grid" role="group" aria-label="选择掌握程度">{[
      [1, '完全不会'], [2, '比较模糊'], [3, '基本理解'], [4, '能够运用'], [5, '熟练掌握'],
    ].map(([value, label]) => <button type="button" key={value} className={answers[question.id] === value ? 'selected' : ''} aria-pressed={answers[question.id] === value} onClick={() => setAnswers((current) => ({ ...current, [question.id]: value }))}>{label}</button>)}</div>}
    <div className="swm-battle-actions">
      <Button disabled={index === 0} onClick={() => setIndex((value) => value - 1)}>上一题</Button>
      {index < assessment.questions.length - 1 ? <Button type="primary" disabled={answers[question.id] === undefined} onClick={() => setIndex((value) => value + 1)}>下一题</Button> : <Button type="primary" loading={busy} disabled={answered !== assessment.questions.length} onClick={async () => {
        setBusy(true);
        try {
          const completed = await submitDiagnostic(organizationId, applicationId, assessment.id, assessment.questions.map((item) => ({
            question_id: item.id,
            ...(item.question_type === 'objective' ? { selected_option_id: String(answers[item.id]) } : { self_rating: Number(answers[item.id]) }),
          })));
          setAssessment(completed);
          message.success('诊断完成，未来七天计划已更新');
          await onCompleted();
        } catch (error) { message.error(errorText(error, '提交诊断失败')); }
        finally { setBusy(false); }
      }}>完成诊断</Button>}
    </div>
  </section>;
}

export function WeeklyQuizPanel({ subject, organizationId, applicationId, onCompleted }: {
  subject: StudySubject;
  organizationId: string;
  applicationId: string;
  onCompleted: () => Promise<void>;
}) {
  const [history, setHistory] = useState<WeeklyQuiz[]>([]);
  const [quiz, setQuiz] = useState<WeeklyQuiz | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setQuiz(null); setAnswers({}); setIndex(0);
    void listWeeklyQuizzes(organizationId, applicationId, subject)
      .then((items) => { if (!cancelled) { setHistory(items); setQuiz(items.find((item) => item.status === 'ready') || null); } })
      .catch((error) => { if (!cancelled) message.error(errorText(error, '加载周测失败')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [applicationId, organizationId, subject]);

  const question = quiz?.questions[index];
  const answered = quiz?.questions.filter((item) => answers[item.id]).length || 0;
  const completedHistory = useMemo(() => history.filter((item) => item.status === 'completed').slice(0, 4), [history]);
  if (loading) return <Skeleton active paragraph={{ rows: 5 }} />;
  if (!quiz) return <section className="swm-weekly-quiz-empty">
    <ClipboardCheck size={30} aria-hidden="true" /><h2>{subjectLabels[subject]}周测</h2>
    <p>从近期错题中抽取最多 5 题；客观题由服务端判分，主观题在看过参考答案后自评。</p>
    <Button type="primary" loading={busy} onClick={async () => {
      setBusy(true);
      try { const created = await generateWeeklyQuiz(organizationId, applicationId, subject); setQuiz(created); setAnswers({}); setIndex(0); }
      catch (error) { message.error(errorText(error, '至少记录一道错题后才能生成周测')); }
      finally { setBusy(false); }
    }}>生成本周周测</Button>
    {completedHistory.length > 0 && <div className="swm-quiz-history"><strong>最近成绩</strong>{completedHistory.map((item) => <Tag key={item.id}>{item.week_start} · {item.score ?? 0} 分</Tag>)}</div>}
  </section>;
  if (quiz.status === 'completed') return <section className="swm-answer-card-result"><CheckCircle2 size={32} aria-hidden="true" /><span className="swm-eyebrow">周测已完成</span><strong>{quiz.score ?? 0} 分</strong><p>错题、复习节奏和未来计划已经同步更新。</p><Button icon={<RotateCcw size={17} />} onClick={() => setQuiz(null)}>查看历史或重新生成</Button></section>;
  if (!question) return <Empty description="周测没有可用题目" />;
  const selected = answers[question.id];
  return <section className="swm-quick-quiz swm-weekly-quiz" aria-labelledby="swm-weekly-question">
    <div className="swm-module-progress"><span>{subjectLabels[subject]}本周复盘</span><span>{answered}/{quiz.questions.length}</span></div>
    <Progress percent={Math.round((answered / quiz.questions.length) * 100)} showInfo={false} />
    <div className="swm-quick-question"><span>第 {index + 1} 题 · {question.question_type === 'objective' ? '服务端判分' : '自主复盘'}</span><h2 id="swm-weekly-question">{question.prompt}</h2></div>
    {question.question_type === 'objective' ? <div className="swm-answer-options">{question.options.map((option) => <button type="button" key={option.id} className={selected === option.id ? 'selected' : ''} aria-pressed={selected === option.id} onClick={() => setAnswers((current) => ({ ...current, [question.id]: option.id }))}><b>{option.id}</b><span>{option.text}</span></button>)}</div> : <>
      {!revealed[question.id] ? <Button block onClick={() => setRevealed((current) => ({ ...current, [question.id]: true }))}>查看参考答案并自评</Button> : <div className="swm-self-review"><div><span className="swm-eyebrow">参考答案</span><p>{question.reference_answer || '请对照原题解析和自己的作答过程。'}</p></div><div className="swm-rating-grid" role="group" aria-label="选择掌握程度">{([['again', '不会'], ['hard', '模糊'], ['good', '会了']] as Array<[ReviewRating, string]>).map(([value, label]) => <button type="button" key={value} className={selected === value ? 'selected' : ''} aria-pressed={selected === value} onClick={() => setAnswers((current) => ({ ...current, [question.id]: value }))}>{label}</button>)}</div></div>}
    </>}
    <div className="swm-battle-actions"><Button disabled={index === 0} onClick={() => setIndex((value) => value - 1)}>上一题</Button>{index < quiz.questions.length - 1 ? <Button type="primary" disabled={!selected} onClick={() => setIndex((value) => value + 1)}>下一题</Button> : <Button type="primary" loading={busy} disabled={answered !== quiz.questions.length} onClick={async () => {
      setBusy(true);
      try {
        const completed = await submitWeeklyQuiz(organizationId, applicationId, quiz.id, quiz.questions.map((item) => ({
          question_id: item.id,
          ...(item.question_type === 'objective' ? { selected_option_id: answers[item.id] } : { rating: answers[item.id] as ReviewRating }),
        })));
        setQuiz(completed); setHistory((items) => [completed, ...items.filter((item) => item.id !== completed.id)]);
        message.success('周测完成，学习计划已重新计算');
        await onCompleted();
      } catch (error) { message.error(errorText(error, '提交周测失败')); }
      finally { setBusy(false); }
    }}>提交周测</Button>}</div>
  </section>;
}
