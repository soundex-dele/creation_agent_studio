import { useEffect, useMemo, useState } from 'react';
import { Button, Empty, Progress, Tag } from 'antd';
import {
  BookMarked, Brain, Check, ChevronRight, CircleAlert, CircleCheck,
  CircleDotDashed, Clock3, Map, RotateCcw, Sparkles,
} from 'lucide-react';

import type {
  CurriculumTree,
  StudyDashboard,
  StudyMastery,
  StudyMistake,
  StudyReview,
  StudySubject,
  SubjectEnrollment,
} from '@/types/studyWithMethod';
import {
  buildFlashcards,
  buildKnowledgeMapNodes,
  buildLearningActions,
  type KnowledgeNodeStatus,
  type ReviewMode,
} from './learningModules';

const subjectLabels: Record<StudySubject, string> = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', politics: '思想政治', history: '历史', geography: '地理',
};

const actionIcons = { quiz: Clock3, cards: BookMarked, map: Map } as const;

export function LearningActionCards({ dashboard, onOpen }: {
  dashboard: Extract<StudyDashboard, { mode: 'student' }>;
  onOpen: (mode: Exclude<ReviewMode, 'due'>, subject: StudySubject) => void;
}) {
  const actions = buildLearningActions(dashboard);
  return <section className="swm-action-section" aria-labelledby="swm-action-title">
    <div className="swm-section-title">
      <div><span className="swm-eyebrow">系统已替你挑好</span><h2 id="swm-action-title">现在做什么</h2></div>
      <span className="swm-section-hint">点一下就开始</span>
    </div>
    <div className="swm-action-grid">
      {actions.map((action) => {
        const Icon = actionIcons[action.id];
        return <button type="button" key={action.id} onClick={() => onOpen(action.mode, action.subject)}>
          <span className={`swm-action-icon is-${action.id}`}><Icon size={21} aria-hidden="true" /></span>
          <span className="swm-action-copy">
            <small>{subjectLabels[action.subject]} · {action.badge}</small>
            <strong>{action.title}</strong>
            <em>{action.description}</em>
          </span>
          <ChevronRight size={19} aria-hidden="true" />
        </button>;
      })}
    </div>
  </section>;
}

const reviewModules: Array<{
  mode: ReviewMode;
  label: string;
  hint: string;
  icon: typeof Clock3;
}> = [
  { mode: 'due', label: '到期复习', hint: '按记忆节奏', icon: RotateCcw },
  { mode: 'quiz', label: '3 分钟小测', hint: '点选结果', icon: Clock3 },
  { mode: 'cards', label: '必背卡片', hint: '翻面自评', icon: BookMarked },
  { mode: 'map', label: '知识点地图', hint: '看清薄弱点', icon: Map },
];

export function ReviewModulePicker({ active, dueCount, onChange }: {
  active: ReviewMode;
  dueCount: number;
  onChange: (mode: ReviewMode) => void;
}) {
  return <div className="swm-module-picker" aria-label="选择复习方式">
    {reviewModules.map(({ mode, label, hint, icon: Icon }) => <button
      type="button"
      key={mode}
      className={active === mode ? 'active' : ''}
      aria-pressed={active === mode}
      onClick={() => onChange(mode)}
    >
      <Icon size={20} aria-hidden="true" />
      <span><strong>{label}</strong><small>{mode === 'due' && dueCount ? `${dueCount} 项待完成` : hint}</small></span>
    </button>)}
  </div>;
}

export type FlashcardRating = 'again' | 'vague' | 'remembered';

export function FlashcardDeck({ subject, mistakes, reviews, onRate }: {
  subject: StudySubject;
  mistakes: StudyMistake[];
  reviews: StudyReview[];
  onRate: (mistakeId: string, reviewId: string | undefined, rating: FlashcardRating) => Promise<void>;
}) {
  const allCards = useMemo(
    () => buildFlashcards(subject, mistakes, reviews),
    [mistakes, reviews, subject],
  );
  const [ratedIds, setRatedIds] = useState<string[]>([]);
  const [revealed, setRevealed] = useState(false);
  const [saving, setSaving] = useState(false);
  const cards = allCards.filter((card) => !ratedIds.includes(card.id));
  const card = cards[0];

  useEffect(() => {
    setRatedIds([]);
    setRevealed(false);
  }, [subject]);

  if (!card) return <div className="swm-module-empty"><Empty description={
    allCards.length ? '这组卡片已经复习完成' : `还没有可生成卡片的${subjectLabels[subject]}错题`
  } />{allCards.length > 0 && <Button icon={<RotateCcw size={17} />} onClick={() => setRatedIds([])}>再复习一遍</Button>}</div>;

  const rate = async (rating: FlashcardRating) => {
    setSaving(true);
    try {
      await onRate(card.id, card.reviewId, rating);
      setRatedIds((ids) => [...ids, card.id]);
      setRevealed(false);
    } finally { setSaving(false); }
  };

  return <section className="swm-flashcard-stage" aria-labelledby="swm-flashcard-title">
    <div className="swm-module-progress">
      <span id="swm-flashcard-title">{subjectLabels[subject]}记忆卡</span>
      <span>{ratedIds.length + 1} / {allCards.length}</span>
    </div>
    <Progress percent={Math.round((ratedIds.length / allCards.length) * 100)} showInfo={false} />
    <article className={`swm-flashcard ${revealed ? 'is-revealed' : ''}`}>
      <div className="swm-flashcard-meta"><Tag>{card.knowledgeLabel}</Tag><span>掌握度 {card.mastery}%</span></div>
      {card.imageUrl && !revealed && <img src={card.imageUrl} alt="记忆卡关联错题" />}
      <span className="swm-eyebrow">{revealed ? '答案与要点' : '先在心里回答'}</span>
      <p>{revealed ? card.answer : card.question}</p>
      {!revealed ? <Button type="primary" size="large" block onClick={() => setRevealed(true)}>点击翻面</Button> : <div className="swm-flashcard-ratings" aria-label="选择掌握程度">
        <Button disabled={saving} onClick={() => void rate('again')}>不会</Button>
        <Button disabled={saving} onClick={() => void rate('vague')}>有点模糊</Button>
        <Button type="primary" loading={saving} onClick={() => void rate('remembered')}>记住了</Button>
      </div>}
    </article>
  </section>;
}

const nodeMeta: Record<KnowledgeNodeStatus, { label: string; icon: typeof Check }> = {
  unstarted: { label: '未开始', icon: CircleDotDashed },
  'needs-work': { label: '需巩固', icon: CircleAlert },
  learning: { label: '学习中', icon: CircleDotDashed },
  mastered: { label: '已掌握', icon: CircleCheck },
  current: { label: '当前章节', icon: Sparkles },
};

export function KnowledgeMapPanel({ subject, enrollment, masteries, curriculum, onPractice }: {
  subject: StudySubject;
  enrollment?: SubjectEnrollment;
  masteries: StudyMastery[];
  curriculum?: CurriculumTree | null;
  onPractice: (topic: string) => void;
}) {
  const nodes = buildKnowledgeMapNodes(enrollment, subject, masteries, curriculum);
  const mastered = nodes.filter((node) => node.status === 'mastered').length;
  const learning = nodes.filter((node) => node.status === 'learning' || node.status === 'current').length;
  const weak = nodes.filter((node) => node.status === 'needs-work').length;
  const unstarted = nodes.filter((node) => node.status === 'unstarted').length;
  const groups = Array.from(nodes.reduce((result, node) => {
    const group = node.group || '';
    result.set(group, [...(result.get(group) || []), node]);
    return result;
  }, new globalThis.Map<string, typeof nodes>()));
  const nodeIndex = new globalThis.Map(nodes.map((node, index) => [node.id, index + 1]));

  return <section className="swm-knowledge-map" aria-labelledby="swm-map-title">
    <div className="swm-map-summary">
      <div><strong>{mastered}</strong><span>已掌握</span></div>
      <div><strong>{learning}</strong><span>学习中</span></div>
      <div><strong>{weak}</strong><span>需巩固</span></div>
      <div><strong>{unstarted}</strong><span>未开始</span></div>
    </div>
    <div className="swm-section-title swm-map-heading">
      <div><span className="swm-eyebrow">{curriculum?.label || enrollment?.current_chapter || '尚未选择章节'}</span><h2 id="swm-map-title">{subjectLabels[subject]}知识路径</h2></div>
    </div>
    {nodes.length ? <div className="swm-map-groups">{groups.map(([group, groupNodes]) => <section key={group || 'default'} className="swm-map-group">
      {group && <h3 className="swm-map-group-title">{group}</h3>}
      <div className="swm-map-list">{groupNodes.map((node) => {
        const status = nodeMeta[node.status];
        const Icon = status.icon;
        return <button type="button" key={node.id} className={`is-${node.status}`} onClick={() => onPractice(node.label)}>
          <span className="swm-map-index">{nodeIndex.get(node.id)}</span>
          <Icon size={20} aria-hidden="true" />
          <span className="swm-map-copy"><strong>{node.label}</strong><small>{node.detail}</small></span>
          <span className="swm-map-state">{node.score === null ? status.label : `${node.score}% · ${status.label}`}</span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>;
      })}</div>
    </section>)}</div> : <div className="swm-module-empty"><Brain size={28} aria-hidden="true" /><strong>暂无可展示的知识点</strong><span>数学和历史会展示当前教材的完整知识点，其他学科将在题库上线后开放。</span></div>}
  </section>;
}
