import { useMemo, useState } from 'react';
import { Button, Progress, Tag } from 'antd';
import {
  ArrowLeft, BookOpenCheck, CalendarClock, Check, ChevronRight, ClipboardCheck,
  Lightbulb, ListChecks, NotebookPen, RotateCcw, TriangleAlert,
} from 'lucide-react';

import {
  methodCompletion,
  recommendStudyMethod,
  studyMethodCategories,
  studyMethodGuides,
  type StudyMethodAction,
  type StudyMethodCategory,
} from './studyMethodology';
import './StudyMethodology.css';

const guideIcons = {
  'mistake-book': NotebookPen,
  'preview-10': BookOpenCheck,
  'listen-class': Lightbulb,
  'spaced-review': RotateCcw,
  'targeted-practice': ListChecks,
  'exam-review': ClipboardCheck,
} as const;

type MethodProgress = Record<string, string[]>;

function readProgress(storageKey: string): MethodProgress {
  try {
    const value = globalThis.localStorage?.getItem(storageKey);
    return value ? JSON.parse(value) as MethodProgress : {};
  } catch { return {}; }
}

export function MethodologyEntry({ mistakeCount, dueReviewCount, onOpen }: {
  mistakeCount: number;
  dueReviewCount: number;
  onOpen: () => void;
}) {
  const guideId = recommendStudyMethod(mistakeCount, dueReviewCount);
  const guide = studyMethodGuides.find((item) => item.id === guideId) || studyMethodGuides[0];
  const GuideIcon = guideIcons[guide.id as keyof typeof guideIcons] || NotebookPen;
  return <section className="swm-method-entry" aria-labelledby="swm-method-entry-title">
    <div className="swm-section-title">
      <div><span className="swm-eyebrow">会学习，也是一种能力</span><h2 id="swm-method-entry-title">学习方法</h2></div>
      <Button type="text" onClick={onOpen}>查看全部</Button>
    </div>
    <button type="button" className="swm-method-recommendation" onClick={onOpen}>
      <span className="swm-method-recommendation-icon"><GuideIcon size={24} aria-hidden="true" /></span>
      <span>
        <small>为你推荐 · {guide.duration}</small>
        <strong>{guide.title}</strong>
        <em>{guide.subtitle}</em>
      </span>
      <ChevronRight size={20} aria-hidden="true" />
    </button>
  </section>;
}

export function StudyMethodologyCenter({ storageKey, recommendedGuideId, onAction }: {
  storageKey: string;
  recommendedGuideId: string;
  onAction: (action: StudyMethodAction) => void;
}) {
  const [category, setCategory] = useState<'all' | StudyMethodCategory>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [progress, setProgress] = useState<MethodProgress>(() => readProgress(storageKey));
  const recommended = studyMethodGuides.find((guide) => guide.id === recommendedGuideId)
    || studyMethodGuides[0];
  const selected = studyMethodGuides.find((guide) => guide.id === selectedId) || null;
  const filtered = useMemo(() => studyMethodGuides.filter(
    (guide) => category === 'all' || guide.category === category,
  ), [category]);

  const updateProgress = (guideId: string, stepId: string) => {
    setProgress((current) => {
      const existing = current[guideId] || [];
      const nextSteps = existing.includes(stepId)
        ? existing.filter((id) => id !== stepId)
        : [...existing, stepId];
      const next = { ...current, [guideId]: nextSteps };
      try { globalThis.localStorage?.setItem(storageKey, JSON.stringify(next)); } catch { /* noop */ }
      return next;
    });
  };

  if (selected) {
    const Icon = guideIcons[selected.id as keyof typeof guideIcons] || BookOpenCheck;
    const completedSteps = progress[selected.id] || [];
    const percent = methodCompletion(completedSteps, selected);
    return <div className="swm-method-detail">
      <button type="button" className="swm-method-back" onClick={() => setSelectedId(null)}><ArrowLeft size={18} aria-hidden="true" />返回方法库</button>
      <header className="swm-method-detail-header">
        <span className="swm-method-detail-icon"><Icon size={28} aria-hidden="true" /></span>
        <div><Tag>{selected.duration}</Tag><h2>{selected.title}</h2><p>{selected.subtitle}</p></div>
      </header>
      <div className="swm-method-progress"><div><strong>照着做</strong><span>{completedSteps.length} / {selected.steps.length} 步</span></div><Progress percent={percent} showInfo={false} /></div>
      <div className="swm-method-steps">
        {selected.steps.map((step, index) => {
          const completed = completedSteps.includes(step.id);
          return <button type="button" key={step.id} className={completed ? 'is-completed' : ''} aria-pressed={completed} onClick={() => updateProgress(selected.id, step.id)}>
            <span className="swm-method-step-index">{completed ? <Check size={18} aria-hidden="true" /> : index + 1}</span>
            <span><strong>{step.title}</strong><em>{step.description}</em><small>{completed ? '已完成' : `完成标准：${step.check}`}</small></span>
          </button>;
        })}
      </div>
      <div className="swm-method-notes">
        <details>
          <summary><Lightbulb size={19} aria-hidden="true" /><span>为什么这样做</span><ChevronRight size={18} aria-hidden="true" /></summary>
          <p>{selected.principle}</p>
        </details>
        <details>
          <summary><TriangleAlert size={19} aria-hidden="true" /><span>常见误区</span><ChevronRight size={18} aria-hidden="true" /></summary>
          <ul>{selected.pitfalls.map((pitfall) => <li key={pitfall}>{pitfall}</li>)}</ul>
        </details>
      </div>
      <Button type="primary" size="large" block onClick={() => onAction(selected.action.target)}>{selected.action.label}</Button>
    </div>;
  }

  const RecommendedIcon = guideIcons[recommended.id as keyof typeof guideIcons] || CalendarClock;
  return <div className="swm-method-library">
    <header><span className="swm-eyebrow">先看方法，再开始用力</span><h2>学习方法库</h2><p>不需要写心得，选择一个场景，照着步骤做一遍。</p></header>
    <button type="button" className="swm-method-featured" onClick={() => setSelectedId(recommended.id)}>
      <span><RecommendedIcon size={27} aria-hidden="true" /></span>
      <div><small>根据当前学情推荐</small><strong>{recommended.title}</strong><em>{recommended.outcome} · {recommended.duration}</em></div>
      <ChevronRight size={20} aria-hidden="true" />
    </button>
    <div className="swm-method-categories" aria-label="筛选学习方法">
      {studyMethodCategories.map((item) => <button type="button" key={item.value} className={category === item.value ? 'active' : ''} aria-pressed={category === item.value} onClick={() => setCategory(item.value)}>{item.label}</button>)}
    </div>
    <div className="swm-method-grid">
      {filtered.map((guide) => {
        const Icon = guideIcons[guide.id as keyof typeof guideIcons] || BookOpenCheck;
        const percent = methodCompletion(progress[guide.id] || [], guide);
        return <button type="button" key={guide.id} onClick={() => setSelectedId(guide.id)}>
          <span className="swm-method-card-icon"><Icon size={22} aria-hidden="true" /></span>
          <span><small>{guide.duration}</small><strong>{guide.title}</strong><em>{guide.subtitle}</em>{percent > 0 && <span className="swm-method-card-progress">已完成 {percent}%</span>}</span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>;
      })}
    </div>
  </div>;
}
