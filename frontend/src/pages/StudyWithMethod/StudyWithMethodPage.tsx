import {
  useCallback, useEffect, useMemo, useRef, useState,
  type CSSProperties, type Dispatch, type MutableRefObject, type SetStateAction,
} from 'react';
import { Button, Collapse, Empty, Input, message, Modal, Progress, Select, Skeleton, Slider, Tag } from 'antd';
import {
  ArrowLeft, BookOpenCheck, CalendarDays, Camera, Check, CheckCircle2, ChevronRight,
  CircleUserRound, Clock3, Compass, Download, Flame, ImagePlus, ListChecks, MessageCircle,
  RefreshCcw, Send, Settings2,
  Sparkles, Trash2, UserRoundPlus,
} from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import {
  addGuardianLink, completeStudyReview, createTutorSession, deleteStudyData,
  exportStudyData, generateWeeklyQuiz, generateWeeklyReport, getMistakeCheckInSummary,
  getWeeklyReportSummary, importStudyMistake,
  listGuardianLinks, listStudyMistakes, listStudyReviews, listStudyTutors, listTutorSessions,
  listWeeklyQuizzes, loadStudyCatalog, loadStudyDashboard, removeGuardianLink, saveStudyProfile,
  submitStudyAttempt, submitWeeklyQuiz, updateStudyEnrollment, updateStudyTask,
} from '@/services/studyWithMethod';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type {
  GradeStage, GuardianLink, StudyCatalog, StudyDashboard, StudyMistake,
  StudyMistakeCheckInSummary, StudyProblem,
  StudyReportSummary, StudyReview, StudySubject, StudyTutor, StudyTutorSession,
  WeeklyReport, WeeklyQuiz,
} from '@/types/studyWithMethod';
import { calculateStudyImageOutput } from './studyImage';
import {
  FlashcardDeck,
  KnowledgeMapPanel,
  LearningActionCards,
  ReviewModulePicker,
  type FlashcardRating,
} from './StudyLearningModules';
import type { ReviewMode } from './learningModules';
import { MethodologyEntry, StudyMethodologyCenter } from './StudyMethodologyCenter';
import StudyTutorChat from './StudyTutorChat';
import { recommendStudyMethod, type StudyMethodAction } from './studyMethodology';
import './StudyWithMethodPage.css';

type StudentTab = 'today' | 'tutor' | 'mistakes' | 'review' | 'me';
type TutorMode = 'hub' | 'photo' | 'chat';
type MistakeFilterMode = 'week' | 'all' | 'month' | 'date';

const tabs: StudentTab[] = ['today', 'tutor', 'mistakes', 'review', 'me'];
const subjectLabels: Record<StudySubject, string> = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', politics: '思想政治', history: '历史', geography: '地理',
};
const gradeLabels: Record<GradeStage, string> = { high_1: '高一', high_2: '高二', high_3: '高三' };
const quickReplies = ['我没思路', '再提示一点', '检查这一步', '换个讲法', '给我完整解析', '出一道同类题'];
const causeOptions = [
  ['concept', '概念不清'], ['formula', '公式遗忘'], ['memory', '记忆不牢'],
  ['reading', '审题错误'], ['calculation', '计算错误'], ['method', '方法选择'],
  ['expression', '表达不规范'], ['experiment', '实验分析'], ['careless', '粗心'],
] as const;

function tabFromSearch(params: URLSearchParams): StudentTab {
  const value = params.get('view');
  return tabs.includes(value as StudentTab) ? value as StudentTab : 'today';
}

function errorText(error: unknown, fallback: string) {
  if (typeof error === 'object' && error && 'response' in error) {
    const data = (error as { response?: { data?: Record<string, unknown> } }).response?.data;
    if (data) return String(data.detail || Object.values(data)[0] || fallback);
  }
  return error instanceof Error ? error.message : fallback;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(value));
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function localMonthKey(date = new Date()) {
  return localDateKey(date).slice(0, 7);
}

function mistakeFilterFromSearch(params: URLSearchParams): MistakeFilterMode {
  if (params.get('date')) return 'date';
  if (params.get('month')) return 'month';
  if (params.get('scope') === 'all') return 'all';
  return 'week';
}

function mistakeDateFromSearch(params: URLSearchParams) {
  const value = params.get('date');
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return localDateKey();
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? localDateKey() : value;
}

function mistakeMonthFromSearch(params: URLSearchParams) {
  const value = params.get('month');
  return value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? value : localMonthKey();
}

function formatLongDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
  }).format(new Date(`${value}T00:00:00`));
}

function formatMonth(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long' })
    .format(new Date(`${value}-01T00:00:00`));
}

function currentWeekDateKeys() {
  const today = new Date();
  const mondayOffset = (today.getDay() + 6) % 7;
  const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - mondayOffset);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setDate(monday.getDate() + index);
    return localDateKey(date);
  });
}

async function compressStudyImage(file: File) {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('无法读取图片'));
    });
    const size = calculateStudyImageOutput(image.naturalWidth, image.naturalHeight, 0, 100);
    const canvas = document.createElement('canvas');
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法处理图片');
    context.drawImage(image, 0, 0, size.width, size.height);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('无法生成图片')),
      'image/jpeg', 0.86,
    ));
  } finally { URL.revokeObjectURL(url); }
}

function SubjectChips({ catalog, selected, enabled, onChange }: {
  catalog: StudyCatalog;
  selected: StudySubject;
  enabled?: StudySubject[];
  onChange: (subject: StudySubject) => void;
}) {
  const subjects = catalog.subjects.filter((item) => !enabled || enabled.includes(item.value));
  return <div className="swm-subject-chips" aria-label="选择学科">{subjects.map((item) => <button
    type="button" key={item.value} className={selected === item.value ? 'active' : ''}
    aria-pressed={selected === item.value} style={{ '--subject-color': item.color } as CSSProperties}
    onClick={() => onChange(item.value)}
  >{item.label}</button>)}</div>;
}

function Onboarding({ catalog, saving, onSave }: {
  catalog: StudyCatalog;
  saving: boolean;
  onSave: (value: { grade: GradeStage; subjects: StudySubject[]; focus: StudySubject[]; minutes: number }) => Promise<boolean | void>;
}) {
  const [step, setStep] = useState(0);
  const [grade, setGrade] = useState<GradeStage>('high_2');
  const [subjects, setSubjects] = useState<StudySubject[]>(['math']);
  const [focus, setFocus] = useState<StudySubject[]>(['math']);
  const [minutes, setMinutes] = useState(45);
  const toggleSubject = (subject: StudySubject) => {
    setSubjects((current) => current.includes(subject)
      ? current.length > 1 ? current.filter((item) => item !== subject) : current
      : [...current, subject]);
    setFocus((current) => current.filter((item) => item !== subject));
  };
  const toggleFocus = (subject: StudySubject) => setFocus((current) => current.includes(subject)
    ? current.length > 1 ? current.filter((item) => item !== subject) : current
    : current.length < 3 ? [...current, subject] : current);
  return <main className="swm-page swm-onboarding">
    <div className="swm-onboarding-brand"><span><Compass size={28} /></span><div><strong>学之有道</strong><small>少一点填写，多一点专注</small></div></div>
    <div className="swm-step-indicator" aria-label={`建档第 ${step + 1} 步，共 3 步`}>{[0, 1, 2].map((item) => <span key={item} className={item <= step ? 'active' : ''} />)}</div>
    {step === 0 && <section className="swm-onboarding-step"><span className="swm-eyebrow">第 1 步 · 选择年级</span><h1>现在读几年级？</h1><p>之后可以随时修改，我们会据此安排合适的学习节奏。</p><div className="swm-choice-grid swm-grade-grid">{catalog.grades.map((item) => <button type="button" key={item.value} className={grade === item.value ? 'active' : ''} onClick={() => setGrade(item.value)}><strong>{item.label}</strong><span>高中学习阶段</span></button>)}</div></section>}
    {step === 1 && <section className="swm-onboarding-step"><span className="swm-eyebrow">第 2 步 · 选择学科</span><h1>这学期关注哪些科目？</h1><p>先选择在学科目，再点亮 1–3 门重点科。教材与章节可以之后再补。</p><div className="swm-choice-grid swm-subject-grid">{catalog.subjects.map((item) => <button type="button" key={item.value} className={subjects.includes(item.value) ? 'active' : ''} style={{ '--subject-color': item.color } as CSSProperties} aria-pressed={subjects.includes(item.value)} onClick={() => toggleSubject(item.value)}><span className="swm-subject-dot" /><strong>{item.label}</strong><small>{subjects.includes(item.value) ? '已选择' : '点按选择'}</small></button>)}</div><div className="swm-focus-picker"><strong>重点科（最多 3 门）</strong><div>{subjects.map((subject) => <button type="button" key={subject} className={focus.includes(subject) ? 'active' : ''} onClick={() => toggleFocus(subject)}>{subjectLabels[subject]}</button>)}</div></div></section>}
    {step === 2 && <section className="swm-onboarding-step"><span className="swm-eyebrow">第 3 步 · 安排时间</span><h1>每天准备学习多久？</h1><p>这是全部科目的总时长，系统会优先安排重点科并让其他科轮换出现。</p><div className="swm-time-value"><strong>{minutes}</strong><span>分钟 / 天</span></div><Slider min={15} max={120} step={5} value={minutes} onChange={setMinutes} marks={{ 30: '30', 60: '60', 90: '90', 120: '120' }} /><div className="swm-time-presets">{[30, 45, 60, 90].map((value) => <button type="button" key={value} onClick={() => setMinutes(value)}>{value} 分钟</button>)}</div><div className="swm-onboarding-summary"><Check size={20} /><span>{gradeLabels[grade]} · {subjects.length} 门学科 · 重点关注 {focus.map((item) => subjectLabels[item]).join('、')}</span></div></section>}
    <div className="swm-onboarding-actions">{step > 0 && <Button size="large" onClick={() => setStep((value) => value - 1)}>上一步</Button>}{step < 2 ? <Button type="primary" size="large" onClick={() => setStep((value) => value + 1)}>继续</Button> : <Button type="primary" size="large" loading={saving} onClick={() => onSave({ grade, subjects, focus, minutes })}>生成我的学习计划</Button>}</div>
  </main>;
}

function ReportOverview({ summary }: { summary: StudyReportSummary }) {
  const metrics = summary.overall_metrics;
  return <div className="swm-report-stack"><article className="swm-report-overview"><span className="swm-eyebrow">本周学习总览</span><div><section><strong>{metrics.completion_rate ?? 0}%</strong><span>计划完成</span></section><section><strong>{metrics.correct_rate ?? 0}%</strong><span>练习正确</span></section><section><strong>{metrics.due_review_count ?? 0}</strong><span>待复习</span></section></div></article>{summary.subjects.map((report) => <article className="swm-subject-report" key={report.id}><div><Tag>{subjectLabels[report.subject]}</Tag><strong>{report.summary}</strong></div><p>{report.next_week_advice}</p></article>)}</div>;
}

export default function StudyWithMethodPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [searchParams, setSearchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const navigate = useNavigate();
  const photoInput = useRef<HTMLInputElement | null>(null);
  const mistakeInput = useRef<HTMLInputElement>(null);
  const [dashboard, setDashboard] = useState<StudyDashboard | null>(null);
  const [catalog, setCatalog] = useState<StudyCatalog | null>(null);
  const [tab, setTab] = useState<StudentTab>(() => tabFromSearch(searchParams));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState('');
  const [activeSubject, setActiveSubject] = useState<StudySubject>('math');
  const [tutorMode, setTutorMode] = useState<TutorMode>('hub');
  const [tutors, setTutors] = useState<StudyTutor[]>([]);
  const [sessions, setSessions] = useState<StudyTutorSession[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [activeProblem, setActiveProblem] = useState<StudyProblem | null>(null);
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string } | null>(null);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoUrl, setPhotoUrl] = useState('');
  const [mistakes, setMistakes] = useState<StudyMistake[]>([]);
  const [mistakeFilter, setMistakeFilter] = useState<MistakeFilterMode>(() => mistakeFilterFromSearch(searchParams));
  const [mistakeDate, setMistakeDate] = useState(() => mistakeDateFromSearch(searchParams));
  const [mistakeMonth, setMistakeMonth] = useState(() => mistakeMonthFromSearch(searchParams));
  const [mistakesLoading, setMistakesLoading] = useState(false);
  const [checkInSummary, setCheckInSummary] = useState<StudyMistakeCheckInSummary | null>(null);
  const [reviews, setReviews] = useState<StudyReview[]>([]);
  const [quiz, setQuiz] = useState<WeeklyQuiz | null>(null);
  const [quizAnswers, setQuizAnswers] = useState<Record<string, boolean>>({});
  const [reviewMode, setReviewMode] = useState<ReviewMode>('due');
  const [reportSummary, setReportSummary] = useState<StudyReportSummary | null>(null);
  const [guardians, setGuardians] = useState<GuardianLink[]>([]);
  const [enrollmentOpen, setEnrollmentOpen] = useState(false);
  const [profileSettingsOpen, setProfileSettingsOpen] = useState(false);
  const [profileGrade, setProfileGrade] = useState<GradeStage>('high_2');
  const [profileSubjects, setProfileSubjects] = useState<StudySubject[]>(['math']);
  const [profileFocus, setProfileFocus] = useState<StudySubject[]>(['math']);
  const [profileMinutes, setProfileMinutes] = useState(45);
  const [curriculumVersion, setCurriculumVersion] = useState('');
  const [currentChapter, setCurrentChapter] = useState('');
  const [mistakeOpen, setMistakeOpen] = useState(false);
  const [mistakeFile, setMistakeFile] = useState<File | null>(null);
  const [mistakeUrl, setMistakeUrl] = useState('');
  const [mistakeCause, setMistakeCause] = useState('concept');
  const [mistakeText, setMistakeText] = useState('');
  const [mistakeNotes, setMistakeNotes] = useState('');
  const [methodologyOpen, setMethodologyOpen] = useState(false);

  const studentDashboard = dashboard?.mode === 'student' ? dashboard : null;
  const enabledSubjects = studentDashboard?.profile.enrollments.map((item) => item.subject) || [];
  const subjectConfig = catalog?.subjects.find((item) => item.value === activeSubject);
  const activeEnrollment = studentDashboard?.profile.enrollments.find((item) => item.subject === activeSubject);
  const activeTutor = tutors.find((item) => item.subject === activeSubject) || null;

  const changeTab = useCallback((next: StudentTab) => {
    setTab(next);
    setSearchParams((current) => { const value = new URLSearchParams(current); value.set('view', next); return value; }, { replace: true });
  }, [setSearchParams]);

  const reload = useCallback(async () => {
    if (!organizationId || !applicationId) return;
    setLoading(true);
    try {
      const [nextDashboard, nextCatalog] = await Promise.all([loadStudyDashboard(organizationId, applicationId), loadStudyCatalog(organizationId, applicationId)]);
      setDashboard(nextDashboard); setCatalog(nextCatalog);
      if (nextDashboard.mode === 'student') setActiveSubject(nextDashboard.profile.last_tutor_subject || nextDashboard.profile.focus_subjects[0] || nextDashboard.profile.enrollments[0]?.subject || 'math');
    } catch (error) { message.error(errorText(error, '加载学习空间失败')); } finally { setLoading(false); }
  }, [applicationId, organizationId]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => () => { if (photoUrl) URL.revokeObjectURL(photoUrl); }, [photoUrl]);
  useEffect(() => () => { if (mistakeUrl) URL.revokeObjectURL(mistakeUrl); }, [mistakeUrl]);
  useEffect(() => {
    if (!organizationId || !applicationId || dashboard?.mode !== 'student') return;
    if (tab === 'tutor') void Promise.all([listStudyTutors(organizationId, applicationId), listTutorSessions(organizationId, applicationId)]).then(([nextTutors, nextSessions]) => { setTutors(nextTutors); setSessions(nextSessions); });
    let cancelled = false;
    if (tab === 'mistakes') {
      setMistakesLoading(true);
      const weekDates = currentWeekDateKeys();
      const mistakeQuery = {
        subject: activeSubject,
        ...(mistakeFilter === 'week' ? { start_date: weekDates[0], end_date: weekDates[6] } : {}),
        ...(mistakeFilter === 'date' ? { date: mistakeDate } : {}),
        ...(mistakeFilter === 'month' ? { month: mistakeMonth } : {}),
      };
      void Promise.all([
        listStudyMistakes(organizationId, applicationId, mistakeQuery),
        listStudyReviews(organizationId, applicationId, { subject: activeSubject, dueOnly: false }),
        getMistakeCheckInSummary(organizationId, applicationId, activeSubject),
      ]).then(([nextMistakes, nextReviews, nextCheckIn]) => {
        if (cancelled) return;
        setMistakes(nextMistakes);
        setReviews(nextReviews);
        setCheckInSummary(nextCheckIn);
      }).catch((error) => {
        if (!cancelled) message.error(errorText(error, '加载错题记录失败'));
      }).finally(() => {
        if (!cancelled) setMistakesLoading(false);
      });
    }
    if (tab === 'review') void Promise.all([
      listStudyReviews(organizationId, applicationId, { dueOnly: false }),
      listWeeklyQuizzes(organizationId, applicationId, activeSubject),
      listStudyMistakes(organizationId, applicationId),
    ]).then(([nextReviews, quizzes, nextMistakes]) => {
      setReviews(nextReviews);
      setQuiz(quizzes[0] || null);
      setMistakes(nextMistakes);
      setQuizAnswers({});
    });
    if (tab === 'me') void Promise.all([getWeeklyReportSummary(organizationId, applicationId), listGuardianLinks(organizationId, applicationId)]).then(([summary, links]) => { setReportSummary(summary); setGuardians(links); });
    return () => { cancelled = true; };
  }, [activeSubject, applicationId, dashboard?.mode, mistakeDate, mistakeFilter, mistakeMonth, organizationId, tab]);

  const changeMistakeFilter = useCallback((mode: MistakeFilterMode) => {
    setMistakeFilter(mode);
    setSearchParams((current) => {
      const value = new URLSearchParams(current);
      value.delete('date');
      value.delete('month');
      value.delete('scope');
      if (mode === 'all') value.set('scope', 'all');
      if (mode === 'date') value.set('date', mistakeDate);
      if (mode === 'month') value.set('month', mistakeMonth);
      return value;
    }, { replace: true });
  }, [mistakeDate, mistakeMonth, setSearchParams]);

  const changeMistakeDate = useCallback((date: string) => {
    setMistakeDate(date);
    setSearchParams((current) => {
      const value = new URLSearchParams(current);
      value.delete('month');
      value.delete('scope');
      value.set('date', date);
      return value;
    }, { replace: true });
  }, [setSearchParams]);

  const changeMistakeMonth = useCallback((month: string) => {
    setMistakeMonth(month);
    setSearchParams((current) => {
      const value = new URLSearchParams(current);
      value.delete('date');
      value.delete('scope');
      value.set('month', month);
      return value;
    }, { replace: true });
  }, [setSearchParams]);

  const saveProfile = async (value: { grade: GradeStage; subjects: StudySubject[]; focus: StudySubject[]; minutes: number }) => {
    if (!organizationId || !applicationId) return false;
    setSaving(true);
    try { await saveStudyProfile(organizationId, applicationId, { grade_stage: value.grade, subjects: value.subjects, focus_subjects: value.focus, daily_minutes: value.minutes }); message.success('学习设置已保存'); await reload(); return true; }
    catch (error) { message.error(errorText(error, '保存学习档案失败')); return false; } finally { setSaving(false); }
  };

  const openTutor = (mode: 'photo' | 'chat', subject = activeSubject) => { setActiveSubject(subject); setConversationId(null); setActiveProblem(null); setTutorMode(mode); changeTab('tutor'); };
  const openReviewModule = (mode: ReviewMode, subject = activeSubject) => {
    setActiveSubject(subject);
    setReviewMode(mode);
    changeTab('review');
  };
  const openTopicTutor = (subject: StudySubject, topic: string) => {
    setDraftRequest({ id: Date.now(), text: `我想复习“${topic}”，请先用一道小问题检查我。` });
    openTutor('chat', subject);
  };
  const handleMethodAction = (action: StudyMethodAction) => {
    setMethodologyOpen(false);
    if (action === 'mistakes') changeTab('mistakes');
    else if (action === 'review') openReviewModule('due');
    else openTutor('chat');
  };
  const openProfileSettings = () => {
    if (!studentDashboard) return;
    setProfileGrade(studentDashboard.profile.grade_stage);
    setProfileSubjects(studentDashboard.profile.enrollments.map((item) => item.subject));
    setProfileFocus(studentDashboard.profile.focus_subjects);
    setProfileMinutes(studentDashboard.profile.daily_minutes);
    setProfileSettingsOpen(true);
  };
  const startChat = async (tutor: StudyTutor) => {
    if (!organizationId || !applicationId) return;
    setBusy('chat');
    try { const result = await createTutorSession(organizationId, applicationId, { mode: 'chat', subject: tutor.subject, agentId: tutor.id }); setActiveSubject(tutor.subject); setConversationId(result.conversation?.id ? String(result.conversation.id) : null); setTutorMode('chat'); }
    catch (error) { message.error(errorText(error, '创建辅导对话失败')); } finally { setBusy(''); }
  };
  const choosePhoto = (file?: File) => { if (!file) return; if (photoUrl) URL.revokeObjectURL(photoUrl); setPhotoFile(file); setPhotoUrl(URL.createObjectURL(file)); };
  const startPhoto = async () => {
    if (!organizationId || !applicationId || !photoFile || !activeTutor) return;
    setBusy('photo');
    try { const image = await compressStudyImage(photoFile); const result = await createTutorSession(organizationId, applicationId, { mode: 'photo', subject: activeSubject, agentId: activeTutor.id, image }); setConversationId(result.conversation?.id ? String(result.conversation.id) : null); setActiveProblem(result.problem || null); setTutorMode('chat'); setPhotoFile(null); setPhotoUrl(''); }
    catch (error) { message.error(errorText(error, '发起拍照辅导失败')); } finally { setBusy(''); }
  };
  const recordPhotoResult = async (isCorrect: boolean) => {
    if (!organizationId || !applicationId || !activeProblem) return;
    setBusy('result');
    try {
      await submitStudyAttempt(organizationId, applicationId, activeProblem.id, { response: '', studentThought: '', isCorrect });
      message.success(isCorrect ? '已记录为掌握，可以继续下一题' : '已加入错题本并安排复习');
      setActiveProblem(null);
      setConversationId(null);
      setTutorMode('photo');
      await reload();
    }
    catch (error) { message.error(errorText(error, '记录结果失败')); } finally { setBusy(''); }
  };
  const saveEnrollment = async () => {
    if (!organizationId || !applicationId) return;
    setBusy('enrollment');
    try { await updateStudyEnrollment(organizationId, applicationId, activeSubject, { curriculum_version: curriculumVersion, current_chapter: currentChapter }); message.success('学科进度已更新'); setEnrollmentOpen(false); await reload(); }
    catch (error) { message.error(errorText(error, '更新学科进度失败')); } finally { setBusy(''); }
  };
  const saveMistake = async () => {
    if (!organizationId || !applicationId || (!mistakeFile && !mistakeText.trim())) return;
    setBusy('mistake');
    try {
      const image = mistakeFile ? await compressStudyImage(mistakeFile) : undefined;
      const created = await importStudyMistake(organizationId, applicationId, { problemText: mistakeText.trim(), image, knowledgeSummary: '', cause: mistakeCause, notes: mistakeNotes.trim(), correctAnswer: '', similarProblemTypes: [] }, activeSubject, studentDashboard?.profile.grade_stage || 'high_2');
      const today = localDateKey();
      const visibleInCurrentFilter = mistakeFilter === 'all'
        || mistakeFilter === 'week'
        || (mistakeFilter === 'date' && mistakeDate === today)
        || (mistakeFilter === 'month' && mistakeMonth === today.slice(0, 7));
      if (visibleInCurrentFilter) setMistakes((items) => [created, ...items]);
      setCheckInSummary(await getMistakeCheckInSummary(organizationId, applicationId, activeSubject));
      setMistakeOpen(false); setMistakeFile(null); setMistakeUrl(''); setMistakeText(''); setMistakeNotes('');
      message.success('错题已收好，今日打卡完成');
      await reload();
    }
    catch (error) { message.error(errorText(error, '录入错题失败')); } finally { setBusy(''); }
  };

  const navItems = useMemo(() => [
    { key: 'today' as const, label: '今日', icon: ListChecks }, { key: 'tutor' as const, label: '辅导', icon: Sparkles },
    { key: 'mistakes' as const, label: '错题', icon: BookOpenCheck }, { key: 'review' as const, label: '复习', icon: RefreshCcw },
    { key: 'me' as const, label: '我的', icon: CircleUserRound },
  ], []);

  if (!organizationId || !applicationId) return <Empty description="请选择组织后打开学之有道" />;
  if (loading || !dashboard || !catalog) return <div className="swm-page swm-loading"><Skeleton active paragraph={{ rows: 7 }} /></div>;
  if (dashboard.mode === 'onboarding') return <Onboarding catalog={catalog} saving={saving} onSave={saveProfile} />;
  if (dashboard.mode === 'guardian') return <main className="swm-page swm-guardian"><span className="swm-eyebrow">家长只读视图</span><h1>看见进步，不打扰过程</h1><p>这里只展示学习趋势与建议，不公开题目图片、对话和逐题操作。</p>{dashboard.reports.map((report: WeeklyReport) => <article className="swm-subject-report" key={report.id}><Tag>{subjectLabels[report.subject]}</Tag><strong>{report.summary}</strong><p>{report.next_week_advice}</p></article>)}</main>;

  return <div className="swm-page">
    {showApplicationHeader && <header className="swm-platform-header"><Button type="text" icon={<ArrowLeft size={18} />} onClick={() => navigate('/apps')}>应用中心</Button><div className="swm-wordmark"><Compass size={20} />学之有道</div></header>}
    <main className="swm-student-shell">
      <header className="swm-mobile-header"><div><span className="swm-eyebrow">{gradeLabels[dashboard.profile.grade_stage]} · {dashboard.profile.enrollments.length} 门学科</span><h1>{tab === 'today' ? `今天也稳稳向前，${dashboard.profile.display_name || dashboard.profile.student_name}` : navItems.find((item) => item.key === tab)?.label}</h1></div><div className="swm-logo"><Compass size={24} /></div></header>
      {tab === 'today' && <TodayView dashboard={dashboard} onTutor={openTutor} onReview={() => openReviewModule('due', dashboard.due_reviews[0]?.subject)} onOpenModule={openReviewModule} onMethodology={() => setMethodologyOpen(true)} organizationId={organizationId} applicationId={applicationId} reload={reload} />}
      {tab === 'tutor' && <TutorView catalog={catalog} enabledSubjects={enabledSubjects} activeSubject={activeSubject} setActiveSubject={setActiveSubject} activeEnrollment={activeEnrollment} activeTutor={activeTutor} tutors={tutors} sessions={sessions} tutorMode={tutorMode} setTutorMode={setTutorMode} conversationId={conversationId} setConversationId={setConversationId} activeProblem={activeProblem} busy={busy} photoUrl={photoUrl} photoInput={photoInput} choosePhoto={choosePhoto} startPhoto={startPhoto} startChat={startChat} recordPhotoResult={recordPhotoResult} draftRequest={draftRequest} setDraftRequest={setDraftRequest} openEnrollment={() => { setCurriculumVersion(activeEnrollment?.curriculum_version || '通用高中课程'); setCurrentChapter(activeEnrollment?.current_chapter || ''); setEnrollmentOpen(true); }} />}
      {tab === 'mistakes' && <MistakesView catalog={catalog} enabledSubjects={enabledSubjects} activeSubject={activeSubject} setActiveSubject={setActiveSubject} mistakes={mistakes} reviews={reviews} setReviews={setReviews} filterMode={mistakeFilter} mistakeDate={mistakeDate} mistakeMonth={mistakeMonth} onFilterChange={changeMistakeFilter} onDateChange={changeMistakeDate} onMonthChange={changeMistakeMonth} loading={mistakesLoading} checkInSummary={checkInSummary} open={() => setMistakeOpen(true)} onTutor={(subject) => openTutor('chat', subject)} organizationId={organizationId} applicationId={applicationId} />}
      {tab === 'review' && <ReviewView dashboard={dashboard} catalog={catalog} enabledSubjects={enabledSubjects} activeSubject={activeSubject} setActiveSubject={setActiveSubject} reviews={reviews} setReviews={setReviews} mistakes={mistakes} quiz={quiz} setQuiz={setQuiz} quizAnswers={quizAnswers} setQuizAnswers={setQuizAnswers} reviewMode={reviewMode} setReviewMode={setReviewMode} onTopicTutor={openTopicTutor} organizationId={organizationId} applicationId={applicationId} />}
      {tab === 'me' && <ProfileView dashboard={dashboard} reportSummary={reportSummary} setReportSummary={setReportSummary} guardians={guardians} setGuardians={setGuardians} organizationId={organizationId} applicationId={applicationId} setActiveSubject={setActiveSubject} onEditProfile={openProfileSettings} openEnrollment={(item) => { setActiveSubject(item.subject); setCurriculumVersion(item.curriculum_version || '通用高中课程'); setCurrentChapter(item.current_chapter); setEnrollmentOpen(true); }} reload={reload} />}
    </main>
    <nav className="swm-bottom-nav" aria-label="学之有道功能导航">{navItems.map(({ key, label, icon: Icon }) => <button type="button" key={key} className={tab === key ? 'active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => changeTab(key)}><Icon size={21} /><span>{label}</span></button>)}</nav>
    <Modal title={`完善${subjectLabels[activeSubject]}进度`} open={enrollmentOpen} okText="保存" cancelText="稍后再说" confirmLoading={busy === 'enrollment'} onOk={() => void saveEnrollment()} onCancel={() => setEnrollmentOpen(false)}><div className="swm-progress-form"><label>教材版本<Select value={curriculumVersion || undefined} placeholder="选择教材版本" options={(subjectConfig?.curriculum_versions || []).map((value) => ({ value, label: value }))} onChange={setCurriculumVersion} /></label><label>当前章节<Select value={currentChapter || undefined} placeholder="选择当前章节" options={(subjectConfig?.chapters || []).map((value) => ({ value, label: value }))} onChange={setCurrentChapter} /></label></div></Modal>
    <Modal
      title="学习设置"
      open={profileSettingsOpen}
      okText="保存并重排未来计划"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: profileSubjects.length < 1 || profileFocus.length < 1 }}
      onCancel={() => setProfileSettingsOpen(false)}
      onOk={async () => {
        const saved = await saveProfile({ grade: profileGrade, subjects: profileSubjects, focus: profileFocus, minutes: profileMinutes });
        if (saved) setProfileSettingsOpen(false);
      }}
    >
      <div className="swm-profile-settings">
        <fieldset><legend>年级</legend><div className="swm-modal-choice-row">{catalog.grades.map((item) => <button type="button" key={item.value} className={profileGrade === item.value ? 'active' : ''} onClick={() => setProfileGrade(item.value)}>{item.label}</button>)}</div></fieldset>
        <fieldset><legend>在学科目</legend><div className="swm-modal-subject-grid">{catalog.subjects.map((item) => <button type="button" key={item.value} className={profileSubjects.includes(item.value) ? 'active' : ''} onClick={() => { setProfileSubjects((current) => current.includes(item.value) ? current.length > 1 ? current.filter((value) => value !== item.value) : current : [...current, item.value]); setProfileFocus((current) => current.filter((value) => value !== item.value)); }}>{item.label}</button>)}</div></fieldset>
        <fieldset><legend>重点科（1–3 门）</legend><div className="swm-modal-choice-row">{profileSubjects.map((subject) => <button type="button" key={subject} className={profileFocus.includes(subject) ? 'active' : ''} onClick={() => setProfileFocus((current) => current.includes(subject) ? current.length > 1 ? current.filter((value) => value !== subject) : current : current.length < 3 ? [...current, subject] : current)}>{subjectLabels[subject]}</button>)}</div></fieldset>
        <fieldset><legend>每日全科总时长：{profileMinutes} 分钟</legend><Slider min={15} max={120} step={5} value={profileMinutes} onChange={setProfileMinutes} /></fieldset>
      </div>
    </Modal>
    <Modal title={`录入${subjectLabels[activeSubject]}错题`} open={mistakeOpen} okText="保存并安排复习" cancelText="取消" confirmLoading={busy === 'mistake'} okButtonProps={{ disabled: !mistakeFile && !mistakeText.trim() }} onOk={() => void saveMistake()} onCancel={() => setMistakeOpen(false)}><div className="swm-mistake-form">{mistakeUrl ? <div className="swm-mistake-preview"><img src={mistakeUrl} alt="待录入错题" /><Button onClick={() => mistakeInput.current?.click()}>重新选择</Button></div> : <button type="button" className="swm-upload-tile" onClick={() => mistakeInput.current?.click()}><ImagePlus /><strong>拍照或选择题图</strong><small>可使用相机，也可从相册选择</small></button>}<input ref={mistakeInput} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) { if (mistakeUrl) URL.revokeObjectURL(mistakeUrl); setMistakeFile(file); setMistakeUrl(URL.createObjectURL(file)); } event.target.value = ''; }} /><div><strong>主要错因</strong><div className="swm-cause-grid">{causeOptions.map(([value, label]) => <button type="button" key={value} className={mistakeCause === value ? 'active' : ''} onClick={() => setMistakeCause(value)}>{label}</button>)}</div></div><Collapse ghost items={[{ key: 'more', label: '没有题图或想补充说明', children: <div className="swm-extra-fields"><label>题目文字<Input.TextArea value={mistakeText} onChange={(event) => setMistakeText(event.target.value)} rows={3} /></label><label>补充说明<Input.TextArea value={mistakeNotes} onChange={(event) => setMistakeNotes(event.target.value)} rows={2} /></label></div> }]} /></div></Modal>
    <Modal title="学习方法" open={methodologyOpen} footer={null} width={760} getContainer={false} rootClassName="swm-methodology-modal" onCancel={() => setMethodologyOpen(false)}>
      <StudyMethodologyCenter
        storageKey={`study-methodology:${dashboard.profile.id}`}
        recommendedGuideId={recommendStudyMethod(dashboard.mistake_count, dashboard.due_review_count)}
        onAction={handleMethodAction}
      />
    </Modal>
  </div>;
}

function TodayView({ dashboard, onTutor, onReview, onOpenModule, onMethodology, organizationId, applicationId, reload }: { dashboard: Extract<StudyDashboard, { mode: 'student' }>; onTutor: (mode: 'photo' | 'chat', subject?: StudySubject) => void; onReview: () => void; onOpenModule: (mode: ReviewMode, subject?: StudySubject) => void; onMethodology: () => void; organizationId: string; applicationId: string; reload: () => Promise<void> }) {
  const resolvedCount = dashboard.tasks.filter((item) => item.status !== 'pending').length;
  return <section className="swm-view"><article className="swm-hero-card"><div><span>今日进度</span><h2>{resolvedCount} / {dashboard.tasks.length} 项</h2><p>重点科：{dashboard.profile.focus_subjects.map((item) => subjectLabels[item]).join('、')}</p></div><Progress type="circle" size={82} strokeColor="#e9c46a" trailColor="rgba(255,255,255,.18)" percent={dashboard.tasks.length ? Math.round(100 * resolvedCount / dashboard.tasks.length) : 0} /></article>{dashboard.due_review_count > 0 && <button type="button" className="swm-due-review" onClick={onReview}><RefreshCcw aria-hidden="true" /><span><strong>先复习到期错题</strong><small>{dashboard.due_review_count} 道题已到复习时间，完成后再开始新任务</small></span><ChevronRight aria-hidden="true" /></button>}<div className="swm-quick-start"><button type="button" onClick={() => onTutor('photo')}><span><Camera size={24} /></span><div><strong>拍题问老师</strong><small>拍下题目，直接开始辅导</small></div><ChevronRight /></button><button type="button" onClick={() => onTutor('chat')}><span><MessageCircle size={24} /></span><div><strong>和老师聊聊</strong><small>选一位学科老师自由提问</small></div><ChevronRight /></button></div><LearningActionCards dashboard={dashboard} onOpen={onOpenModule} /><MethodologyEntry mistakeCount={dashboard.mistake_count} dueReviewCount={dashboard.due_review_count} onOpen={onMethodology} /><div className="swm-section-title"><div><span className="swm-eyebrow">按重点科优先轮换</span><h2>今日学习</h2></div><Tag>{dashboard.tasks.reduce((sum, item) => sum + item.duration_minutes, 0)} 分钟</Tag></div><div className="swm-task-list">{dashboard.tasks.map((task) => <article className={`swm-task ${task.status !== 'pending' ? 'is-done' : ''}`} key={task.id}><button type="button" className="swm-task-check" aria-label={`${task.status === 'completed' ? '已完成' : task.status === 'skipped' ? '已跳过' : '完成'}${task.title}`} disabled={task.status !== 'pending'} onClick={async () => { await updateStudyTask(organizationId, applicationId, task.id, 'completed'); await reload(); }}>{task.status === 'completed' && <Check size={17} />}</button><div><span>{subjectLabels[task.subject]} · {task.duration_minutes} 分钟{task.status === 'skipped' ? ' · 已跳过' : ''}</span><h3>{task.title}</h3></div><div className="swm-task-actions">{task.status === 'pending' && <button type="button" className="swm-task-skip" onClick={async () => { await updateStudyTask(organizationId, applicationId, task.id, 'skipped'); await reload(); }}>跳过</button>}<button type="button" className="swm-task-start" aria-label={`开始${task.title}`} onClick={() => onTutor('chat', task.subject)}><ChevronRight size={19} /></button></div></article>)}</div><div className="swm-insights"><article><BookOpenCheck /><strong>{dashboard.mistake_count}</strong><span>累计错题</span></article><article><RefreshCcw /><strong>{dashboard.due_review_count}</strong><span>到期复习</span></article><article><Sparkles /><strong>{dashboard.masteries[0]?.score ?? 0}%</strong><span>薄弱点掌握</span></article></div></section>;
}

function TutorView(props: {
  catalog: StudyCatalog;
  enabledSubjects: StudySubject[];
  activeSubject: StudySubject;
  setActiveSubject: (value: StudySubject) => void;
  activeEnrollment?: Extract<StudyDashboard, { mode: 'student' }>['profile']['enrollments'][number];
  activeTutor: StudyTutor | null;
  tutors: StudyTutor[];
  sessions: StudyTutorSession[];
  tutorMode: TutorMode;
  setTutorMode: (mode: TutorMode) => void;
  conversationId: string | null;
  setConversationId: (id: string | null) => void;
  activeProblem: StudyProblem | null;
  busy: string;
  photoUrl: string;
  photoInput: MutableRefObject<HTMLInputElement | null>;
  choosePhoto: (file?: File) => void;
  startPhoto: () => Promise<void>;
  startChat: (tutor: StudyTutor) => Promise<void>;
  recordPhotoResult: (correct: boolean) => Promise<void>;
  draftRequest: { id: number; text: string } | null;
  setDraftRequest: (request: { id: number; text: string }) => void;
  openEnrollment: () => void;
}) {
  const p = props;

  if (p.conversationId) {
    return <section className="swm-view swm-tutor-view">
      <StudyTutorChat
        conversationId={p.conversationId}
        tutor={p.activeTutor}
        subjectLabel={subjectLabels[p.activeSubject]}
        activeProblem={p.activeProblem}
        resultBusy={p.busy === 'result'}
        draftRequest={p.draftRequest}
        quickReplies={quickReplies}
        onBack={() => {
            p.setConversationId(null);
            p.setTutorMode('hub');
        }}
        onDraftRequest={p.setDraftRequest}
        onRecordResult={(correct) => void p.recordPhotoResult(correct)}
      />
    </section>;
  }

  let content;
  if (p.tutorMode === 'photo') {
    content = <div className="swm-photo-flow">
      {p.photoUrl ? <>
        <div className="swm-photo-preview"><img src={p.photoUrl} alt="待发送题目" /></div>
        <div className="swm-photo-actions">
          <Button onClick={() => p.photoInput.current?.click()}>重新选择</Button>
          <Button
            type="primary"
            icon={<Send size={17} />}
            loading={p.busy === 'photo'}
            disabled={!p.activeTutor}
            onClick={() => void p.startPhoto()}
          >发给{p.activeTutor?.name || '老师'}</Button>
        </div>
      </> : <button type="button" className="swm-camera-card" onClick={() => p.photoInput.current?.click()}>
        <span><Camera size={30} aria-hidden="true" /></span>
        <strong>添加{subjectLabels[p.activeSubject]}题图</strong>
        <small>可以调用相机拍摄，也可以从相册选择</small>
      </button>}
      <input
        ref={(node) => { p.photoInput.current = node; }}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        hidden
        onChange={(event) => {
          p.choosePhoto(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      <Button type="text" onClick={() => p.setTutorMode('hub')}>返回选择辅导方式</Button>
    </div>;
  } else if (p.tutorMode === 'chat') {
    const availableTutors = p.tutors.filter((item) => p.enabledSubjects.includes(item.subject));
    content = <div className="swm-tutor-list">
      <div className="swm-section-title">
        <div><span className="swm-eyebrow">本会话固定老师</span><h2>选择辅导老师</h2></div>
      </div>
      {availableTutors.map((tutor) => <button
        type="button"
        key={tutor.id}
        className={tutor.subject === p.activeSubject ? 'active' : ''}
        disabled={p.busy === 'chat'}
        onClick={() => void p.startChat(tutor)}
      >
        <span>{tutor.subject_label.slice(0, 1)}</span>
        <div><strong>{tutor.name}</strong><small>{tutor.description}</small></div>
        <ChevronRight aria-hidden="true" />
      </button>)}
      {!availableTutors.length && <Empty description="暂时没有可用的辅导老师" />}
      <Button type="text" onClick={() => p.setTutorMode('hub')}>返回选择辅导方式</Button>
    </div>;
  } else {
    content = <>
      <div className="swm-tutor-entry-grid">
        <button type="button" onClick={() => p.setTutorMode('photo')}>
          <span><Camera aria-hidden="true" /></span>
          <strong>拍照辅导</strong>
          <small>拍下题目，直接在对话中获得提示</small>
          <em>现在拍题 <ChevronRight size={17} aria-hidden="true" /></em>
        </button>
        <button type="button" onClick={() => p.setTutorMode('chat')}>
          <span><MessageCircle aria-hidden="true" /></span>
          <strong>对话辅导</strong>
          <small>选择老师，聊概念、方法或复习计划</small>
          <em>选择老师 <ChevronRight size={17} aria-hidden="true" /></em>
        </button>
      </div>
      {p.sessions.length > 0 && <>
        <div className="swm-section-title">
          <div><span className="swm-eyebrow">接着上次学习</span><h2>最近辅导</h2></div>
        </div>
        <div className="swm-session-list">
          {p.sessions.slice(0, 5).map((session) => <button
            type="button"
            key={session.id}
            onClick={() => {
              p.setActiveSubject(session.subject || 'math');
              p.setConversationId(String(session.id));
              p.setTutorMode('chat');
            }}
          >
            <MessageCircle aria-hidden="true" />
            <span>
              <strong>{session.title}</strong>
              <small>{session.agent?.name || subjectLabels[session.subject]} · {formatDate(session.updated_at)}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>)}
        </div>
      </>}
    </>;
  }

  return <section className="swm-view swm-tutor-view">
    <SubjectChips
      catalog={p.catalog}
      selected={p.activeSubject}
      enabled={p.enabledSubjects}
      onChange={p.setActiveSubject}
    />
    {!p.activeEnrollment?.setup_completed && <div className="swm-setup-banner">
      <div>
        <Settings2 aria-hidden="true" />
        <span>
          <strong>完善{subjectLabels[p.activeSubject]}进度</strong>
          <small>选择教材和章节，计划会更贴合校内进度</small>
        </span>
      </div>
      <Button onClick={p.openEnrollment}>去选择</Button>
    </div>}
    {p.tutorMode === 'photo' && !p.activeTutor && <div className="swm-inline-notice" role="status">
      这门学科的辅导老师暂未部署，请稍后再试或联系管理员。
    </div>}
    {content}
  </section>;
}

function MistakesView({
  catalog, enabledSubjects, activeSubject, setActiveSubject, mistakes, reviews, setReviews,
  filterMode, mistakeDate, mistakeMonth, onFilterChange, onDateChange, onMonthChange,
  loading, checkInSummary, open, onTutor, organizationId, applicationId,
}: {
  catalog: StudyCatalog;
  enabledSubjects: StudySubject[];
  activeSubject: StudySubject;
  setActiveSubject: (value: StudySubject) => void;
  mistakes: StudyMistake[];
  reviews: StudyReview[];
  setReviews: Dispatch<SetStateAction<StudyReview[]>>;
  filterMode: MistakeFilterMode;
  mistakeDate: string;
  mistakeMonth: string;
  onFilterChange: (value: MistakeFilterMode) => void;
  onDateChange: (value: string) => void;
  onMonthChange: (value: string) => void;
  loading: boolean;
  checkInSummary: StudyMistakeCheckInSummary | null;
  open: () => void;
  onTutor: (subject: StudySubject) => void;
  organizationId: string;
  applicationId: string;
}) {
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [masteredIds, setMasteredIds] = useState<string[]>([]);
  const filtered = mistakes.filter((item) => item.subject === activeSubject && !masteredIds.includes(item.id));
  const today = localDateKey();
  const activeCheckInSummary = checkInSummary?.subject === activeSubject ? checkInSummary : null;
  const weekDates = currentWeekDateKeys();
  const checkedDateKeys = new Set(activeCheckInSummary?.check_ins.map((item) => item.checked_on) || []);
  const checkedThisWeek = weekDates.filter((date) => checkedDateKeys.has(date)).length;
  const filterDescription = filterMode === 'week'
    ? '本周错题'
    : filterMode === 'all' ? '全部错题'
      : filterMode === 'month' ? formatMonth(mistakeMonth) : formatLongDate(mistakeDate);
  const markMastered = async (mistake: StudyMistake) => {
    const review = reviews.find((item) => item.mistake.id === mistake.id);
    if (review) {
      await completeStudyReview(organizationId, applicationId, review.id, true);
      setReviews((items) => items.filter((item) => item.id !== review.id));
    }
    setMasteredIds((items) => [...items, mistake.id]);
    message.success(review ? '已更新掌握度，并安排下次复习' : '本次已标记为会做');
  };
  return <section className="swm-view">
    <SubjectChips catalog={catalog} selected={activeSubject} enabled={enabledSubjects} onChange={(subject) => { setActiveSubject(subject); setOpenedId(null); }} />
    <div className="swm-section-title"><div><span className="swm-eyebrow">错题不是终点</span><h2>错题再战</h2></div><Button type="primary" icon={<Camera size={17} />} onClick={open}>拍照录入</Button></div>
    <p className="swm-section-description">新增一道错题即完成当天打卡；先遮住解析再做一次，逐步把错题变成会做的题。</p>
    <article className="swm-week-check-in" aria-label={`本周已打卡 ${checkedThisWeek} 天`}>
      <div className="swm-week-check-in-heading">
        <span className="swm-check-in-icon"><Flame size={22} aria-hidden="true" /></span>
        <div><strong>本周打卡</strong><span>{subjectLabels[activeSubject]} · 新增错题自动打卡</span></div>
        <div><strong>{checkedThisWeek}<small> / 7 天</small></strong><span>连续 {activeCheckInSummary?.streak ?? 0} 天</span></div>
      </div>
      <div className="swm-week-days">
        {weekDates.map((date, index) => {
          const checked = checkedDateKeys.has(date);
          const future = date > today;
          return <div key={date} aria-current={date === today ? 'date' : undefined} className={`${checked ? 'is-checked' : ''} ${date === today ? 'is-today' : ''} ${future ? 'is-future' : ''}`}>
            <span>周{['一', '二', '三', '四', '五', '六', '日'][index]}</span>
            <strong>{Number(date.slice(-2))}</strong>
            <small>{checked ? <><CheckCircle2 size={13} aria-hidden="true" />已打卡</> : future ? '未到' : '未打卡'}</small>
          </div>;
        })}
      </div>
    </article>
    <div className="swm-mistake-filter-panel">
      <div className="swm-mistake-filter-modes" role="group" aria-label="错题时间范围">
        {([['week', '本周'], ['all', '全部'], ['month', '按月份'], ['date', '按日期']] as const).map(([value, label]) => <button
          type="button"
          key={value}
          className={filterMode === value ? 'active' : ''}
          aria-pressed={filterMode === value}
          onClick={() => onFilterChange(value)}
        >{label}</button>)}
      </div>
      {filterMode === 'month' && <label htmlFor="swm-mistake-month"><span>选择月份</span><input id="swm-mistake-month" type="month" value={mistakeMonth} max={localMonthKey()} onChange={(event) => { if (event.target.value) onMonthChange(event.target.value); }} /></label>}
      {filterMode === 'date' && <label htmlFor="swm-mistake-date"><span>选择日期</span><input id="swm-mistake-date" type="date" value={mistakeDate} max={today} onChange={(event) => { if (event.target.value) onDateChange(event.target.value); }} /></label>}
      <span className="swm-filter-result" role="status">正在查看：{filterDescription}</span>
    </div>
    {loading && <div className="swm-mistake-loading" aria-busy="true" aria-label="正在加载错题"><Skeleton active paragraph={{ rows: 3 }} /></div>}
    {!loading && filtered.map((mistake) => {
      const opened = openedId === mistake.id;
      const answer = mistake.correct_answer || mistake.knowledge_summary;
      return <article className={`swm-mistake-card swm-battle-card ${opened ? 'is-open' : ''}`} key={mistake.id}>
        <div className="swm-card-heading"><div><Tag>{mistake.cause_label}</Tag><span className="swm-muted">记录于 {formatDate(mistake.created_at)}</span></div><span>掌握度 {mistake.mastery}%</span></div>
        {mistake.problem.source_image_url && <img src={mistake.problem.source_image_url} alt={`${subjectLabels[mistake.subject]}错题`} />}
        <p>{mistake.problem.confirmed_text || mistake.problem.original_text || '看题图，先独立重做这道题'}</p>
        {!opened ? <Button size="large" block onClick={() => setOpenedId(mistake.id)}>开始再做一次</Button> : <>
          <div className="swm-answer-panel"><span className="swm-eyebrow">解析与复盘要点</span><p>{answer || '这道题暂时没有文字解析，可以继续问老师，或根据题图回忆正确步骤。'}</p></div>
          <div className="swm-battle-actions">
            <Button onClick={() => onTutor(mistake.subject)}>继续问老师</Button>
            <Button onClick={() => { setOpenedId(null); message.info('已保留在错题再战列表'); }}>还不会</Button>
            <Button type="primary" onClick={() => void markMastered(mistake)}>已经会做</Button>
          </div>
        </>}
        <span className="swm-muted">下次复习：{mistake.next_review_at ? formatDate(mistake.next_review_at) : '待安排'}</span>
      </article>;
    })}
    {!loading && !filtered.length && <div className="swm-module-empty"><Empty description={`${filterDescription}没有待再战的${subjectLabels[activeSubject]}错题`} />{masteredIds.length > 0 ? <Button icon={<RefreshCcw size={17} />} onClick={() => setMasteredIds([])}>重新查看</Button> : filterMode !== 'all' ? <Button icon={<CalendarDays size={17} />} onClick={() => onFilterChange('all')}>查看全部错题</Button> : <Button type="primary" icon={<Camera size={17} />} onClick={open}>录入第一道错题</Button>}</div>}
  </section>;
}

function QuickQuizPanel({ activeSubject, quiz, setQuiz, quizAnswers, setQuizAnswers, organizationId, applicationId }: { activeSubject: StudySubject; quiz: WeeklyQuiz | null; setQuiz: (quiz: WeeklyQuiz | null) => void; quizAnswers: Record<string, boolean>; setQuizAnswers: Dispatch<SetStateAction<Record<string, boolean>>>; organizationId: string; applicationId: string }) {
  const [questionIndex, setQuestionIndex] = useState(0);
  const currentQuiz = quiz?.subject === activeSubject ? quiz : null;
  const currentQuestion = currentQuiz?.questions[questionIndex];
  const answered = currentQuiz?.questions.filter((item) => item.id in quizAnswers).length || 0;

  useEffect(() => { setQuestionIndex(0); }, [activeSubject, currentQuiz?.id]);

  if (!currentQuiz) return <div className="swm-quiz-empty">
    <Clock3 size={30} aria-hidden="true" />
    <strong>用 3 分钟检查近期薄弱点</strong>
    <span>题目来自你的错题记录，做完只需点选“会不会”。</span>
    <Button type="primary" size="large" onClick={async () => {
      try { setQuiz(await generateWeeklyQuiz(organizationId, applicationId, activeSubject)); }
      catch (error) { message.info(errorText(error, '记录错题后即可生成小测')); }
    }}>生成 3 分钟小测</Button>
  </div>;

  if (currentQuiz.status === 'completed') return <div className="swm-quiz-result">
    <Check size={28} aria-hidden="true" /><span className="swm-eyebrow">本周小测已完成</span>
    <strong>{currentQuiz.score ?? 0} 分</strong><p>结果已计入学情，下周会根据新的错题重新出题。</p>
  </div>;

  if (!currentQuestion) return <Empty description="这次小测暂时没有题目" />;

  const choose = (value: boolean) => {
    setQuizAnswers((answers) => ({ ...answers, [currentQuestion.id]: value }));
    if (questionIndex < currentQuiz.questions.length - 1) setQuestionIndex((index) => index + 1);
  };

  return <article className="swm-quick-quiz">
    <div className="swm-module-progress"><span>{subjectLabels[activeSubject]} · 3 分钟小测</span><span>{answered} / {currentQuiz.questions.length}</span></div>
    <Progress percent={Math.round((answered / currentQuiz.questions.length) * 100)} showInfo={false} />
    <div className="swm-quick-question"><span>第 {questionIndex + 1} 题</span><p>{currentQuestion.prompt}</p><small>{currentQuestion.knowledge_point || '近期错题'}</small></div>
    <div className="swm-quiz-self-check"><Button onClick={() => choose(false)}>没做出来</Button><Button onClick={() => choose(false)}>有点模糊</Button><Button type="primary" onClick={() => choose(true)}>做对了</Button></div>
    <div className="swm-quiz-pagination">{currentQuiz.questions.map((question, index) => <button type="button" key={question.id} className={`${index === questionIndex ? 'active' : ''} ${question.id in quizAnswers ? 'answered' : ''}`} aria-label={`查看第 ${index + 1} 题`} aria-current={index === questionIndex ? 'step' : undefined} onClick={() => setQuestionIndex(index)}>{index + 1}</button>)}</div>
    {answered === currentQuiz.questions.length && <Button type="primary" size="large" block onClick={async () => setQuiz(await submitWeeklyQuiz(organizationId, applicationId, currentQuiz.id, currentQuiz.questions.map((item) => ({ question_id: item.id, is_correct: quizAnswers[item.id] }))))}>提交小测结果</Button>}
  </article>;
}

function ReviewView({ dashboard, catalog, enabledSubjects, activeSubject, setActiveSubject, reviews, setReviews, mistakes, quiz, setQuiz, quizAnswers, setQuizAnswers, reviewMode, setReviewMode, onTopicTutor, organizationId, applicationId }: { dashboard: Extract<StudyDashboard, { mode: 'student' }>; catalog: StudyCatalog; enabledSubjects: StudySubject[]; activeSubject: StudySubject; setActiveSubject: (value: StudySubject) => void; reviews: StudyReview[]; setReviews: Dispatch<SetStateAction<StudyReview[]>>; mistakes: StudyMistake[]; quiz: WeeklyQuiz | null; setQuiz: (quiz: WeeklyQuiz | null) => void; quizAnswers: Record<string, boolean>; setQuizAnswers: Dispatch<SetStateAction<Record<string, boolean>>>; reviewMode: ReviewMode; setReviewMode: (mode: ReviewMode) => void; onTopicTutor: (subject: StudySubject, topic: string) => void; organizationId: string; applicationId: string }) {
  const filtered = reviews.filter((item) => (
    item.subject === activeSubject && new Date(item.next_review_at).getTime() <= Date.now()
  ));
  const enrollment = dashboard.profile.enrollments.find((item) => item.subject === activeSubject);
  const rateFlashcard = async (_mistakeId: string, reviewId: string | undefined, rating: FlashcardRating) => {
    if (reviewId) {
      await completeStudyReview(organizationId, applicationId, reviewId, rating === 'remembered');
      setReviews((items) => items.filter((item) => item.id !== reviewId));
    }
    message.success(rating === 'remembered' ? '已记住，复习间隔会自动延长' : '已加入近期巩固');
  };
  return <section className="swm-view">
    <SubjectChips catalog={catalog} selected={activeSubject} enabled={enabledSubjects} onChange={setActiveSubject} />
    <ReviewModulePicker active={reviewMode} dueCount={filtered.length} onChange={setReviewMode} />
    {reviewMode === 'due' && <div className="swm-module-content"><div className="swm-section-title"><div><span className="swm-eyebrow">1 · 3 · 7 · 14 天</span><h2>今天到期的复习</h2></div></div>{filtered.map((review) => <article className="swm-review-card" key={review.id}><span className="swm-eyebrow">第 {review.completed_reviews + 1} 次复习</span><p>{review.mistake.problem.confirmed_text || review.mistake.problem.original_text || '查看题图后再做一次'}</p><div><Button onClick={async () => { await completeStudyReview(organizationId, applicationId, review.id, false); setReviews((items) => items.filter((item) => item.id !== review.id)); }}>还不会</Button><Button type="primary" onClick={async () => { await completeStudyReview(organizationId, applicationId, review.id, true); setReviews((items) => items.filter((item) => item.id !== review.id)); }}>这次做对了</Button></div></article>)}{!filtered.length && <Empty description="今天没有到期复习" />}</div>}
    {reviewMode === 'quiz' && <div className="swm-module-content"><QuickQuizPanel activeSubject={activeSubject} quiz={quiz} setQuiz={setQuiz} quizAnswers={quizAnswers} setQuizAnswers={setQuizAnswers} organizationId={organizationId} applicationId={applicationId} /></div>}
    {reviewMode === 'cards' && <div className="swm-module-content"><FlashcardDeck subject={activeSubject} mistakes={mistakes} reviews={reviews} onRate={rateFlashcard} /></div>}
    {reviewMode === 'map' && <div className="swm-module-content"><KnowledgeMapPanel subject={activeSubject} enrollment={enrollment} masteries={dashboard.masteries} onPractice={(topic) => onTopicTutor(activeSubject, topic)} /></div>}
  </section>;
}

function ProfileView({ dashboard, reportSummary, setReportSummary, guardians, setGuardians, organizationId, applicationId, onEditProfile, openEnrollment, reload }: { dashboard: Extract<StudyDashboard, { mode: 'student' }>; reportSummary: StudyReportSummary | null; setReportSummary: (value: StudyReportSummary | null) => void; guardians: GuardianLink[]; setGuardians: Dispatch<SetStateAction<GuardianLink[]>>; organizationId: string; applicationId: string; setActiveSubject: (value: StudySubject) => void; onEditProfile: () => void; openEnrollment: (item: Extract<StudyDashboard, { mode: 'student' }>['profile']['enrollments'][number]) => void; reload: () => Promise<void> }) {
  return <section className="swm-view"><article className="swm-profile-card"><div className="swm-avatar">{(dashboard.profile.display_name || dashboard.profile.student_name).slice(0, 1)}</div><div><h2>{dashboard.profile.display_name || dashboard.profile.student_name}</h2><p>{gradeLabels[dashboard.profile.grade_stage]} · 每日 {dashboard.profile.daily_minutes} 分钟 · {dashboard.profile.enrollments.length} 科</p></div><Button onClick={onEditProfile}>学习设置</Button></article><div className="swm-section-title"><div><span className="swm-eyebrow">本周回顾</span><h2>学习周报</h2></div><Button onClick={async () => setReportSummary(await generateWeeklyReport(organizationId, applicationId))}>更新周报</Button></div>{reportSummary ? <ReportOverview summary={reportSummary} /> : <Empty description="开始学习后，这里会出现周报" />}<div className="swm-section-title"><div><span className="swm-eyebrow">渐进完善</span><h2>学科进度</h2></div></div><div className="swm-enrollment-list">{dashboard.profile.enrollments.map((item) => <button type="button" key={item.id} onClick={() => openEnrollment(item)}><span><strong>{item.subject_label}</strong><small>{item.current_chapter || '尚未选择当前章节'}</small></span><Tag color={item.setup_completed ? 'green' : 'default'}>{item.setup_completed ? '已完善' : '待完善'}</Tag><ChevronRight /></button>)}</div><div className="swm-section-title"><div><span className="swm-eyebrow">隐私友好的陪伴</span><h2>家长只读账号</h2></div><Button icon={<UserRoundPlus size={17} />} onClick={() => { let identifier = ''; Modal.confirm({ title: '关联家长账号', content: <Input aria-label="家长用户名或邮箱" placeholder="家长用户名或邮箱" onChange={(event) => { identifier = event.target.value; }} />, okText: '关联', cancelText: '取消', onOk: async () => { if (!identifier.trim()) throw new Error('请输入账号'); const link = await addGuardianLink(organizationId, applicationId, identifier.trim()); setGuardians((items) => [link, ...items.filter((item) => item.id !== link.id)]); } }); }}>添加</Button></div><div className="swm-guardian-list">{guardians.map((guardian) => <div key={guardian.id}><span><strong>{guardian.guardian_name}</strong><small>{guardian.guardian_email}</small></span><Button type="text" danger aria-label={`移除家长 ${guardian.guardian_name}`} icon={<Trash2 size={17} />} onClick={async () => { await removeGuardianLink(organizationId, applicationId, guardian.id); setGuardians((items) => items.filter((item) => item.id !== guardian.id)); }} /></div>)}</div><div className="swm-data-actions"><Button icon={<Download size={17} />} onClick={async () => { const data = await exportStudyData(organizationId, applicationId); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `学之有道-${new Date().toISOString().slice(0, 10)}.json`; anchor.click(); URL.revokeObjectURL(url); }}>导出学习数据</Button><Button danger icon={<Trash2 size={17} />} onClick={() => Modal.confirm({ title: '删除全部学习数据？', content: '学习档案、题图、计划、错题和周报将永久删除。', okText: '确认删除', okButtonProps: { danger: true }, onOk: async () => { await deleteStudyData(organizationId, applicationId); await reload(); } })}>删除我的数据</Button></div></section>;
}
