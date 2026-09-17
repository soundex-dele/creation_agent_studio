import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Progress,
  Select,
  Skeleton,
  Slider,
  Tag,
} from 'antd';
import {
  ArrowLeft,
  BookOpenCheck,
  Camera,
  Check,
  ChevronRight,
  CircleUserRound,
  Compass,
  Download,
  ImagePlus,
  Lightbulb,
  ListChecks,
  MessageCircle,
  Plus,
  RefreshCcw,
  RotateCw,
  Sparkles,
  Trash2,
  UserRoundPlus,
  X,
} from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import {
  addGuardianLink,
  completeStudyReview,
  confirmStudyProblem,
  createStudyProblem,
  deleteStudyData,
  exportStudyData,
  generateWeeklyReport,
  generateWeeklyQuiz,
  getTutorRun,
  importStudyMistake,
  listGuardianLinks,
  listStudyMistakes,
  listStudyReviews,
  listWeeklyReports,
  listWeeklyQuizzes,
  loadStudyDashboard,
  removeGuardianLink,
  requestVariantProblem,
  requestTutorHint,
  saveStudyProfile,
  submitStudyAttempt,
  submitWeeklyQuiz,
  updateStudyMistake,
  updateStudyTask,
} from '@/services/studyWithMethod';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type {
  GuardianLink,
  StudyDashboard,
  StudyMistake,
  StudyProblem,
  StudyProfileInput,
  StudyReview,
  TutorHint,
  WeeklyReport,
  WeeklyQuiz,
} from '@/types/studyWithMethod';
import { calculateStudyImageOutput } from './studyImage';
import './StudyWithMethodPage.css';


type StudentTab = 'today' | 'tutor' | 'mistakes' | 'review' | 'me';

interface ManualMistakeFormValues {
  problemText?: string;
  knowledgeSummary?: string;
  cause: string;
  notes?: string;
  correctAnswer?: string;
  similarProblemTypes?: string;
}

const studentTabs: StudentTab[] = ['today', 'tutor', 'mistakes', 'review', 'me'];

function studentTabFromSearch(searchParams: URLSearchParams): StudentTab {
  const requestedTab = searchParams.get('view');
  return studentTabs.includes(requestedTab as StudentTab)
    ? requestedTab as StudentTab
    : 'today';
}

const causeOptions = [
  { value: 'concept', label: '概念不清' },
  { value: 'formula', label: '公式遗忘' },
  { value: 'reading', label: '审题错误' },
  { value: 'calculation', label: '计算错误' },
  { value: 'method', label: '方法选择' },
  { value: 'careless', label: '粗心' },
];

const textbookOptions = [
  '人教A版（2019）',
  '人教B版（2019）',
  '北师大版（2019）',
  '苏教版（2019）',
  '湘教版（2019）',
];

function errorText(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : fallback;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' })
    .format(new Date(value));
}

async function transformImage(file: File, rotation: number, cropPercent: number) {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('无法读取图片'));
    });
    const outputSize = calculateStudyImageOutput(
      image.naturalWidth,
      image.naturalHeight,
      rotation,
      cropPercent,
    );
    const output = document.createElement('canvas');
    output.width = outputSize.width;
    output.height = outputSize.height;
    const context = output.getContext('2d');
    if (!context) throw new Error('无法处理图片');
    context.translate(output.width / 2, output.height / 2);
    context.scale(outputSize.scale, outputSize.scale);
    context.rotate(outputSize.radians);
    context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
    return await new Promise<Blob>((resolve, reject) => output.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('无法生成裁剪后的图片')),
      'image/jpeg',
      0.86,
    ));
  } finally {
    URL.revokeObjectURL(url);
  }
}

function ReportCard({ report }: { report: WeeklyReport }) {
  const metrics = report.metrics;
  return (
    <article className="swm-report-card">
      <div className="swm-card-heading">
        <div>
          <span className="swm-eyebrow">{formatDate(report.week_start)} 起</span>
          <h3>{report.student_name || '本周'}的数学学习周报</h3>
        </div>
        <Tag color="green">高二数学</Tag>
      </div>
      <div className="swm-report-stats">
        <div><strong>{metrics.completion_rate ?? 0}%</strong><span>计划完成</span></div>
        <div><strong>{metrics.correct_rate ?? 0}%</strong><span>练习正确</span></div>
        <div><strong>{metrics.due_review_count ?? 0}</strong><span>待复习</span></div>
      </div>
      <p>{report.summary}</p>
      <div className="swm-advice"><Lightbulb size={18} />{report.next_week_advice}</div>
    </article>
  );
}

function Onboarding({ saving, onSave }: {
  saving: boolean;
  onSave: (value: StudyProfileInput) => Promise<void>;
}) {
  const [form] = Form.useForm<StudyProfileInput>();
  return (
    <main className="swm-onboarding">
      <div className="swm-onboarding-mark"><Compass size={38} /></div>
      <span className="swm-eyebrow">先了解你，再制定计划</span>
      <h1>欢迎来到学之有道</h1>
      <p className="swm-lead">用两分钟完成学习档案。首版专注高二数学，之后的计划会贴合你的教材和校内进度。</p>
      <Form
        form={form}
        layout="vertical"
        className="swm-onboarding-form"
        initialValues={{
          daily_minutes: 45,
          subject: 'math',
          grade_stage: 'high_2',
          curriculum_version: textbookOptions[0],
          weak_topics: [],
        }}
        onFinish={(values) => onSave(values)}
      >
        <div className="swm-form-grid">
          <Form.Item name="display_name" label="怎么称呼你"><Input placeholder="例如：小宇" maxLength={80} /></Form.Item>
          <Form.Item name="region" label="所在地区"><Input placeholder="例如：上海市" maxLength={120} /></Form.Item>
          <Form.Item name="curriculum_version" label="数学教材" rules={[{ required: true }]}>
            <Select options={textbookOptions.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="current_chapter" label="学校当前进度" rules={[{ required: true, message: '请填写当前章节' }]}>
            <Input placeholder="例如：选择性必修一 · 圆锥曲线" maxLength={160} />
          </Form.Item>
          <Form.Item name="latest_score" label="最近成绩（满分150）"><InputNumber min={0} max={150} precision={1} /></Form.Item>
          <Form.Item name="target_score" label="目标成绩（满分150）"><InputNumber min={0} max={150} precision={1} /></Form.Item>
        </div>
        <Form.Item name="daily_minutes" label="每天可用于数学的时间" rules={[{ required: true }]}>
          <Slider min={15} max={120} step={5} marks={{ 15: '15 分', 45: '45 分', 90: '90 分', 120: '120 分' }} />
        </Form.Item>
        <Form.Item name="weak_topics" label="目前感觉薄弱的内容">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车，例如：导数、圆锥曲线" />
        </Form.Item>
        <Form.Item name="subject" hidden><Input /></Form.Item>
        <Form.Item name="grade_stage" hidden><Input /></Form.Item>
        <Button type="primary" htmlType="submit" size="large" block loading={saving}>
          生成我的首周计划
        </Button>
      </Form>
    </main>
  );
}

function GuardianDashboard({ reports }: { reports: WeeklyReport[] }) {
  return (
    <main className="swm-guardian">
      <span className="swm-eyebrow">家长只读视图</span>
      <h1>看见进步，不打扰过程</h1>
      <p className="swm-lead">这里只展示学习趋势与下一步建议，不公开孩子的题目图片、对话和逐题操作。</p>
      {reports.length ? reports.map((report) => <ReportCard key={report.id} report={report} />) : (
        <Empty description="孩子完成一周学习后，这里会出现周报" />
      )}
    </main>
  );
}

export default function StudyWithMethodPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [searchParams, setSearchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const manualImageInput = useRef<HTMLInputElement>(null);
  const [manualMistakeForm] = Form.useForm<ManualMistakeFormValues>();

  const [dashboard, setDashboard] = useState<StudyDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<StudentTab>(() => studentTabFromSearch(searchParams));
  const [mistakes, setMistakes] = useState<StudyMistake[]>([]);
  const [reviews, setReviews] = useState<StudyReview[]>([]);
  const [reports, setReports] = useState<WeeklyReport[]>([]);
  const [quiz, setQuiz] = useState<WeeklyQuiz | null>(null);
  const [quizAnswers, setQuizAnswers] = useState<Record<string, boolean>>({});
  const [guardians, setGuardians] = useState<GuardianLink[]>([]);
  const [problemText, setProblemText] = useState('');
  const [studentThought, setStudentThought] = useState('');
  const [answerText, setAnswerText] = useState('');
  const [currentProblem, setCurrentProblem] = useState<StudyProblem | null>(null);
  const [hint, setHint] = useState<TutorHint | null>(null);
  const [aiOutput, setAiOutput] = useState('');
  const [tutorRunId, setTutorRunId] = useState<string | null>(null);
  const [attemptRecorded, setAttemptRecorded] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState('');
  const [rotation, setRotation] = useState(0);
  const [cropPercent, setCropPercent] = useState(100);
  const [manualMistakeOpen, setManualMistakeOpen] = useState(false);
  const [manualImageFile, setManualImageFile] = useState<File | null>(null);
  const [manualImageUrl, setManualImageUrl] = useState('');
  const [manualRotation, setManualRotation] = useState(0);
  const [manualCropPercent, setManualCropPercent] = useState(100);

  const changeTab = useCallback((nextTab: StudentTab) => {
    setTab(nextTab);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('view', nextTab);
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const reload = useCallback(async () => {
    if (!organizationId || !applicationId) return;
    setLoading(true);
    try {
      setDashboard(await loadStudyDashboard(organizationId, applicationId));
    } catch (error) {
      message.error(errorText(error, '加载学习空间失败'));
    } finally {
      setLoading(false);
    }
  }, [applicationId, organizationId]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => () => { if (imageUrl) URL.revokeObjectURL(imageUrl); }, [imageUrl]);
  useEffect(
    () => () => { if (manualImageUrl) URL.revokeObjectURL(manualImageUrl); },
    [manualImageUrl],
  );

  useEffect(() => {
    if (!organizationId || !tutorRunId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const run = await getTutorRun(organizationId, tutorRunId);
        if (cancelled) return;
        if (run.status === 'succeeded') {
          const result = run.output_summary?.result || '智能辅导已完成。';
          setAiOutput(result);
          if (currentProblem?.status === 'needs_confirmation') {
            try {
              const normalized = result.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
              const parsed = JSON.parse(normalized) as { recognized_problem?: string };
              if (parsed.recognized_problem?.trim()) setProblemText(parsed.recognized_problem.trim());
            } catch {
              // Keep the raw tutor output visible and let the student type the question manually.
            }
          }
          setTutorRunId(null);
        } else if (['failed', 'cancelled'].includes(run.status)) {
          setAiOutput(run.error_message || '智能辅导暂时不可用，请使用页面提示继续思考。');
          setTutorRunId(null);
        }
      } catch {
        if (!cancelled) setTutorRunId(null);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [currentProblem?.status, organizationId, tutorRunId]);

  useEffect(() => {
    if (!organizationId || !applicationId || dashboard?.mode !== 'student') return;
    if (tab === 'mistakes') void listStudyMistakes(organizationId, applicationId).then(setMistakes);
    if (tab === 'review') {
      void Promise.all([
        listStudyReviews(organizationId, applicationId),
        listWeeklyQuizzes(organizationId, applicationId),
      ]).then(([nextReviews, quizzes]) => {
        setReviews(nextReviews);
        setQuiz(quizzes[0] ?? null);
      });
    }
    if (tab === 'me') {
      void Promise.all([
        listWeeklyReports(organizationId, applicationId),
        listGuardianLinks(organizationId, applicationId),
      ]).then(([nextReports, nextGuardians]) => {
        setReports(nextReports);
        setGuardians(nextGuardians);
      });
    }
  }, [applicationId, dashboard?.mode, organizationId, tab]);

  const saveProfile = async (value: StudyProfileInput) => {
    if (!organizationId || !applicationId) return;
    setSaving(true);
    try {
      await saveStudyProfile(organizationId, applicationId, value);
      message.success('学习档案已建立，首周计划已经生成');
      await reload();
    } catch (error) {
      message.error(errorText(error, '保存学习档案失败'));
    } finally {
      setSaving(false);
    }
  };

  const chooseImage = (file?: File) => {
    if (!file) return;
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setImageFile(file);
    setImageUrl(URL.createObjectURL(file));
    setRotation(0);
    setCropPercent(100);
  };

  const chooseManualImage = (file?: File) => {
    if (!file) return;
    if (manualImageUrl) URL.revokeObjectURL(manualImageUrl);
    setManualImageFile(file);
    setManualImageUrl(URL.createObjectURL(file));
    setManualRotation(0);
    setManualCropPercent(100);
  };

  const closeManualMistake = () => {
    if (busyAction === 'manual-mistake') return;
    setManualMistakeOpen(false);
    setManualImageFile(null);
    setManualImageUrl('');
    setManualRotation(0);
    setManualCropPercent(100);
    manualMistakeForm.resetFields();
  };

  const createManualMistake = async () => {
    if (!organizationId || !applicationId) return;
    let values: ManualMistakeFormValues;
    try {
      values = await manualMistakeForm.validateFields();
    } catch {
      return;
    }
    if (!values.problemText?.trim() && !manualImageFile) {
      manualMistakeForm.setFields([{
        name: 'problemText',
        errors: ['请输入题目文字或上传题目图片'],
      }]);
      return;
    }

    setBusyAction('manual-mistake');
    try {
      const image = manualImageFile
        ? await transformImage(manualImageFile, manualRotation, manualCropPercent)
        : undefined;
      const mistake = await importStudyMistake(organizationId, applicationId, {
        problemText: values.problemText?.trim() || '',
        image,
        knowledgeSummary: values.knowledgeSummary?.trim() || '',
        cause: values.cause,
        notes: values.notes?.trim() || '',
        correctAnswer: values.correctAnswer?.trim() || '',
        similarProblemTypes: (values.similarProblemTypes || '')
          .split(/\r?\n|[,，]/)
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setMistakes((items) => [mistake, ...items.filter((item) => item.id !== mistake.id)]);
      message.success('错题已录入，并安排首次复习');
      setManualMistakeOpen(false);
      setManualImageFile(null);
      setManualImageUrl('');
      setManualRotation(0);
      setManualCropPercent(100);
      manualMistakeForm.resetFields();
      await reload();
    } catch (error) {
      message.error(errorText(error, '录入错题失败'));
    } finally {
      setBusyAction('');
    }
  };

  const createProblem = async () => {
    if (!organizationId || !applicationId || (!problemText.trim() && !imageFile)) return;
    setBusyAction('create-problem');
    try {
      const image = imageFile ? await transformImage(imageFile, rotation, cropPercent) : undefined;
      const problem = await createStudyProblem(organizationId, applicationId, {
        problemText: problemText.trim(),
        image,
        source: imageFile ? 'camera' : 'manual',
      });
      setCurrentProblem(problem);
      setProblemText(problem.confirmed_text);
      setTutorRunId(problem.latest_run_id);
      setHint(null);
      setAiOutput('');
      setAttemptRecorded(false);
    } catch (error) {
      message.error(errorText(error, '保存题目失败'));
    } finally {
      setBusyAction('');
    }
  };

  const confirmProblem = async () => {
    if (!organizationId || !applicationId || !currentProblem) return;
    setBusyAction('confirm-problem');
    try {
      const problem = await confirmStudyProblem(
        organizationId, applicationId, currentProblem.id, problemText.trim(),
      );
      setCurrentProblem(problem);
      setTutorRunId(problem.latest_run_id);
      message.success('题目文字已确认');
    } catch (error) {
      message.error(errorText(error, '确认题目失败'));
    } finally {
      setBusyAction('');
    }
  };

  const askHint = async (level?: number) => {
    if (!organizationId || !applicationId || !currentProblem) return;
    setBusyAction('hint');
    try {
      const result = await requestTutorHint(
        organizationId, applicationId, currentProblem.id, studentThought, level,
      );
      setHint(result);
      setTutorRunId(result.tutor_run_id);
      setCurrentProblem({
        ...currentProblem,
        max_hint_level: Math.max(currentProblem.max_hint_level, result.hint_level),
      });
    } catch (error) {
      message.error(errorText(error, '获取提示失败'));
    } finally {
      setBusyAction('');
    }
  };

  const markAttempt = async (isCorrect: boolean) => {
    if (!organizationId || !applicationId || !currentProblem) return;
    setBusyAction('attempt');
    try {
      await submitStudyAttempt(organizationId, applicationId, currentProblem.id, {
        response: answerText,
        studentThought,
        isCorrect,
      });
      message.success(isCorrect ? '已记录，继续保持' : '已加入错题本，并安排复习');
      setCurrentProblem({ ...currentProblem, status: 'completed' });
      setAttemptRecorded(true);
      await reload();
    } catch (error) {
      message.error(errorText(error, '记录练习结果失败'));
    } finally {
      setBusyAction('');
    }
  };

  const navItems = useMemo(() => [
    { key: 'today' as const, label: '今日', icon: ListChecks },
    { key: 'tutor' as const, label: '辅导', icon: Camera },
    { key: 'mistakes' as const, label: '错题', icon: BookOpenCheck },
    { key: 'review' as const, label: '复习', icon: RefreshCcw },
    { key: 'me' as const, label: '我的', icon: CircleUserRound },
  ], []);

  if (!organizationId || !applicationId) return <Empty description="请选择组织后打开学之有道" />;
  if (loading && !dashboard) return <div className="swm-loading"><Skeleton active paragraph={{ rows: 7 }} /></div>;

  return (
    <div className="swm-page">
      {showApplicationHeader && (
        <header className="swm-platform-header">
          <Button type="text" icon={<ArrowLeft size={18} />} onClick={() => navigate('/apps')}>应用中心</Button>
          <div className="swm-wordmark"><span><Compass size={20} /></span>学之有道</div>
        </header>
      )}

      {dashboard?.mode === 'onboarding' && <Onboarding saving={saving} onSave={saveProfile} />}
      {dashboard?.mode === 'guardian' && <GuardianDashboard reports={dashboard.reports} />}

      {dashboard?.mode === 'student' && (
        <>
          <main className="swm-student-shell">
            <header className="swm-mobile-header">
              <div>
                <span className="swm-eyebrow">高二数学 · {dashboard.profile.enrollment.curriculum_version}</span>
                <h1>{tab === 'today' ? `今天也稳稳向前，${dashboard.profile.display_name || dashboard.profile.student_name}` : navItems.find((item) => item.key === tab)?.label}</h1>
              </div>
              <div className="swm-logo"><Compass size={25} /></div>
            </header>

            {tab === 'today' && (
              <section className="swm-view">
                <article className="swm-hero-card">
                  <div>
                    <span>今日进度</span>
                    <h2>{dashboard.tasks.filter((task) => task.status === 'completed').length} / {dashboard.tasks.length} 项</h2>
                    <p>{dashboard.profile.enrollment.current_chapter}</p>
                  </div>
                  <Progress
                    type="circle"
                    size={82}
                    strokeColor="#e9c46a"
                    trailColor="rgba(255,255,255,.18)"
                    percent={dashboard.tasks.length ? Math.round(
                      100 * dashboard.tasks.filter((task) => task.status === 'completed').length / dashboard.tasks.length,
                    ) : 0}
                  />
                </article>
                <div className="swm-section-title"><div><span className="swm-eyebrow">按自己的节奏</span><h2>今日学习</h2></div><Tag>{dashboard.tasks.reduce((sum, task) => sum + task.duration_minutes, 0)} 分钟</Tag></div>
                <div className="swm-task-list">
                  {dashboard.tasks.map((task) => (
                    <article key={task.id} className={`swm-task ${task.status === 'completed' ? 'is-done' : ''}`}>
                      <button
                        className="swm-task-check"
                        aria-label={task.status === 'completed' ? '已完成' : '完成任务'}
                        disabled={task.status === 'completed'}
                        onClick={async () => {
                          await updateStudyTask(organizationId, applicationId, task.id, 'completed');
                          await reload();
                        }}
                      >{task.status === 'completed' ? <Check size={17} /> : null}</button>
                      <div><span>{task.task_type_label} · {task.duration_minutes} 分钟</span><h3>{task.title}</h3></div>
                      <ChevronRight size={20} />
                    </article>
                  ))}
                </div>
                <div className="swm-insights">
                  <article><BookOpenCheck size={21} /><strong>{dashboard.mistake_count}</strong><span>累计错题</span></article>
                  <article><RefreshCcw size={21} /><strong>{dashboard.due_review_count}</strong><span>到期复习</span></article>
                  <article><Sparkles size={21} /><strong>{dashboard.masteries[0]?.score ?? 0}%</strong><span>薄弱点掌握</span></article>
                </div>
              </section>
            )}

            {tab === 'tutor' && (
              <section className="swm-view swm-tutor-view">
                {!currentProblem ? (
                  <>
                    <div
                      className="swm-camera-card"
                      onClick={() => fileInput.current?.click()}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          fileInput.current?.click();
                        }
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="swm-camera-icon"><Camera size={30} /></div>
                      <h2>拍一道数学题</h2>
                      <p>画面尽量只保留一道题，识别会更准确</p>
                      <Button
                        type="primary"
                        size="large"
                        onClick={(event) => {
                          event.stopPropagation();
                          fileInput.current?.click();
                        }}
                      >打开相机</Button>
                      <input
                        ref={fileInput}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        capture="environment"
                        hidden
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => chooseImage(event.target.files?.[0])}
                      />
                    </div>
                    {imageUrl && (
                      <div className="swm-image-editor">
                        <div className="swm-image-stage" style={{ '--crop': `${cropPercent}%` } as CSSProperties}>
                          <img src={imageUrl} alt="待上传题目" style={{ transform: `rotate(${rotation}deg) scale(${100 / cropPercent})` }} />
                        </div>
                        <div className="swm-image-tools">
                          <Button icon={<RotateCw size={17} />} onClick={() => setRotation((value) => (value + 90) % 360)}>旋转</Button>
                          <div><span>裁剪范围</span><Slider min={55} max={100} value={cropPercent} onChange={setCropPercent} /></div>
                          <Button type="text" danger icon={<X size={17} />} onClick={() => { setImageFile(null); setImageUrl(''); }}>移除</Button>
                        </div>
                      </div>
                    )}
                    <div className="swm-or"><span>或者手动录题</span></div>
                    <Input.TextArea
                      value={problemText}
                      onChange={(event) => setProblemText(event.target.value)}
                      rows={5}
                      placeholder="输入题目内容。拍照后也建议补充或校正识别文字。"
                    />
                    <Button
                      type="primary"
                      size="large"
                      block
                      disabled={!problemText.trim() && !imageFile}
                      loading={busyAction === 'create-problem'}
                      onClick={createProblem}
                    >开始辅导</Button>
                  </>
                ) : (
                  <div className="swm-tutor-session">
                    {(imageUrl || currentProblem.source_image_url) && (
                      <div className="swm-current-problem-image">
                        <img
                          src={imageUrl || currentProblem.source_image_url}
                          alt="当前辅导题目"
                          style={imageUrl ? {
                            maxWidth: `${cropPercent}%`,
                            maxHeight: `${cropPercent}%`,
                            transform: `rotate(${rotation}deg) scale(${100 / cropPercent})`,
                          } : undefined}
                        />
                      </div>
                    )}
                    <div className="swm-card-heading"><div><span className="swm-eyebrow">{currentProblem.knowledge_point_name || '数学题'}</span><h2>先确认题目，再说说你的思路</h2></div><Tag color="green">提示 {currentProblem.max_hint_level}/4</Tag></div>
                    <Input.TextArea value={problemText} onChange={(event) => setProblemText(event.target.value)} rows={5} />
                    {(currentProblem.status === 'needs_confirmation' || problemText !== currentProblem.confirmed_text) && (
                      <Button loading={busyAction === 'confirm-problem'} onClick={confirmProblem}>确认题目文字</Button>
                    )}
                    <Input.TextArea
                      value={studentThought}
                      onChange={(event) => setStudentThought(event.target.value)}
                      rows={3}
                      placeholder="我已经想到…… / 我卡在……"
                    />
                    <div className="swm-hint-actions">
                      <Button type="primary" icon={<Lightbulb size={17} />} loading={busyAction === 'hint'} onClick={() => askHint()}>给我一点提示</Button>
                      <Button disabled={currentProblem.max_hint_level < 2} onClick={() => askHint(4)}>查看完整解析</Button>
                    </div>
                    {hint && <Alert type="success" showIcon message={`第 ${hint.hint_level} 级提示`} description={hint.hint} />}
                    {tutorRunId && <div className="swm-ai-loading"><Sparkles size={17} />智能辅导老师正在复核这道题…</div>}
                    {aiOutput && <div className="swm-ai-output"><span className="swm-eyebrow">智能辅导结果</span><pre>{aiOutput}</pre></div>}
                    {currentProblem.conversation_id && (
                      <Button
                        type="link"
                        icon={<MessageCircle size={17} />}
                        onClick={() => navigate(`/chat?conversation=${currentProblem.conversation_id}`)}
                      >查看辅导对话记录</Button>
                    )}
                    <Input value={answerText} onChange={(event) => setAnswerText(event.target.value)} placeholder="可选：记录你的最终答案" />
                    {!attemptRecorded ? (
                      <div className="swm-result-actions">
                        <Button icon={<Check size={17} />} loading={busyAction === 'attempt'} onClick={() => markAttempt(true)}>我做对了</Button>
                        <Button danger icon={<X size={17} />} loading={busyAction === 'attempt'} onClick={() => markAttempt(false)}>这题做错了</Button>
                      </div>
                    ) : (
                      <div className="swm-result-actions">
                        <Button type="primary" icon={<Sparkles size={17} />} onClick={async () => {
                          const result = await requestVariantProblem(organizationId, applicationId, currentProblem.id);
                          setAiOutput('');
                          setTutorRunId(result.tutor_run_id);
                        }}>生成同类巩固题</Button>
                        <Button onClick={() => {
                          setCurrentProblem(null);
                          setProblemText('');
                          setStudentThought('');
                          setAnswerText('');
                          setHint(null);
                          setAiOutput('');
                          setImageFile(null);
                          setImageUrl('');
                          setAttemptRecorded(false);
                        }}>继续下一题</Button>
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}

            {tab === 'mistakes' && (
              <section className="swm-view">
                <div className="swm-section-title">
                  <div><span className="swm-eyebrow">错题不是终点</span><h2>找到反复失分的原因</h2></div>
                  <div className="swm-section-actions">
                    <Tag>{mistakes.length} 题</Tag>
                    <Button
                      type="primary"
                      icon={<Plus size={17} />}
                      onClick={() => setManualMistakeOpen(true)}
                    >录入错题</Button>
                  </div>
                </div>
                {mistakes.length ? mistakes.map((mistake) => (
                  <article className="swm-mistake-card" key={mistake.id}>
                    <div className="swm-card-heading">
                      <div>
                        <span className="swm-eyebrow">{mistake.knowledge_summary || mistake.problem.knowledge_point_name || '待补充知识点'}</span>
                        <div><Tag color="orange">{mistake.cause_label}</Tag></div>
                      </div>
                      <span>掌握度 {mistake.mastery}%</span>
                    </div>
                    {mistake.problem.source_image_url && (
                      <img className="swm-mistake-image" src={mistake.problem.source_image_url} alt="错题题图" />
                    )}
                    <p>{mistake.problem.confirmed_text || mistake.problem.original_text || '图片错题'}</p>
                    <Select
                      value={mistake.cause}
                      options={causeOptions}
                      onChange={async (cause) => {
                        const next = await updateStudyMistake(
                          organizationId, applicationId, mistake.id, { cause },
                        );
                        setMistakes((items) => items.map((item) => item.id === next.id ? next : item));
                      }}
                    />
                    {mistake.notes && <div className="swm-mistake-detail"><strong>为什么做错</strong><p>{mistake.notes}</p></div>}
                    {mistake.correct_answer && <div className="swm-mistake-detail"><strong>正确答案</strong><p>{mistake.correct_answer}</p></div>}
                    {mistake.similar_problem_types.length > 0 && (
                      <div className="swm-mistake-detail">
                        <strong>同类题型</strong>
                        <div className="swm-similar-types">
                          {mistake.similar_problem_types.map((item) => <Tag key={item}>{item}</Tag>)}
                        </div>
                      </div>
                    )}
                    <span className="swm-muted">下次复习：{mistake.next_review_at ? formatDate(mistake.next_review_at) : '待安排'}</span>
                  </article>
                )) : <Empty description="还没有错题。认真记录，比追求零错误更重要。" />}
              </section>
            )}

            {tab === 'review' && (
              <section className="swm-view">
                <div className="swm-section-title"><div><span className="swm-eyebrow">1 · 3 · 7 · 14 天</span><h2>今天到期的复习</h2></div></div>
                {reviews.length ? reviews.map((review) => (
                  <article className="swm-review-card" key={review.id}>
                    <span className="swm-eyebrow">第 {review.completed_reviews + 1} 次复习</span>
                    <p>{review.mistake.problem.confirmed_text || review.mistake.problem.original_text}</p>
                    <div className="swm-result-actions">
                      <Button onClick={async () => {
                        await completeStudyReview(organizationId, applicationId, review.id, false);
                        setReviews((items) => items.filter((item) => item.id !== review.id));
                      }}>还不会</Button>
                      <Button type="primary" onClick={async () => {
                        await completeStudyReview(organizationId, applicationId, review.id, true);
                        setReviews((items) => items.filter((item) => item.id !== review.id));
                      }}>这次做对了</Button>
                    </div>
                  </article>
                )) : <Empty description="今天没有到期错题，可以安心学习新内容" />}
                <div className="swm-section-title"><div><span className="swm-eyebrow">来自本周错题</span><h2>数学周测</h2></div>{!quiz && <Button onClick={async () => {
                  try {
                    const next = await generateWeeklyQuiz(organizationId, applicationId);
                    setQuiz(next);
                    setQuizAnswers({});
                  } catch (error) {
                    message.info(errorText(error, '记录错题后即可生成周测'));
                  }
                }}>生成周测</Button>}</div>
                {quiz && (
                  <article className="swm-quiz-card">
                    <div className="swm-card-heading"><span>{quiz.question_count} 道错题回测</span>{quiz.status === 'completed' && <Tag color="green">得分 {quiz.score}</Tag>}</div>
                    {quiz.questions.map((question, index) => (
                      <div className="swm-quiz-question" key={question.id}>
                        <span>{index + 1}</span>
                        <p>{question.prompt}</p>
                        {quiz.status !== 'completed' && <div><Button size="small" type={quizAnswers[question.id] === false ? 'primary' : 'default'} onClick={() => setQuizAnswers((value) => ({ ...value, [question.id]: false }))}>未做对</Button><Button size="small" type={quizAnswers[question.id] === true ? 'primary' : 'default'} onClick={() => setQuizAnswers((value) => ({ ...value, [question.id]: true }))}>做对了</Button></div>}
                      </div>
                    ))}
                    {quiz.status !== 'completed' && <Button type="primary" block disabled={Object.keys(quizAnswers).length !== quiz.questions.length} onClick={async () => {
                      const completed = await submitWeeklyQuiz(
                        organizationId,
                        applicationId,
                        quiz.id,
                        quiz.questions.map((question) => ({ question_id: question.id, is_correct: quizAnswers[question.id] })),
                      );
                      setQuiz(completed);
                      await reload();
                    }}>提交周测结果</Button>}
                  </article>
                )}
              </section>
            )}

            {tab === 'me' && (
              <section className="swm-view">
                <article className="swm-profile-card">
                  <div className="swm-avatar">{(dashboard.profile.display_name || dashboard.profile.student_name).slice(0, 1)}</div>
                  <div><h2>{dashboard.profile.display_name || dashboard.profile.student_name}</h2><p>{dashboard.profile.region || '未填写地区'} · 每日 {dashboard.profile.daily_minutes} 分钟</p></div>
                  <Tag color="green">高二数学</Tag>
                </article>
                <div className="swm-section-title"><div><span className="swm-eyebrow">本周回顾</span><h2>家长周报</h2></div><Button onClick={async () => {
                  const report = await generateWeeklyReport(organizationId, applicationId);
                  setReports((items) => [report, ...items.filter((item) => item.id !== report.id)]);
                }}>更新周报</Button></div>
                {reports[0] ? <ReportCard report={reports[0]} /> : <Empty description="点击更新周报生成本周学习总结" />}
                <div className="swm-section-title"><div><span className="swm-eyebrow">隐私友好的陪伴</span><h2>家长只读账号</h2></div><Button icon={<UserRoundPlus size={17} />} onClick={() => {
                  let identifier = '';
                  Modal.confirm({
                    title: '关联家长账号',
                    content: <Input placeholder="家长用户名或邮箱" onChange={(event) => { identifier = event.target.value; }} />,
                    okText: '关联',
                    cancelText: '取消',
                    onOk: async () => {
                      const normalizedIdentifier = identifier.trim();
                      if (!normalizedIdentifier) {
                        message.warning('请输入家长用户名或邮箱');
                        throw new Error('guardian identifier is required');
                      }
                      try {
                        const link = await addGuardianLink(
                          organizationId,
                          applicationId,
                          normalizedIdentifier,
                        );
                        setGuardians((items) => [
                          link,
                          ...items.filter((item) => item.id !== link.id),
                        ]);
                        message.success('家长账号已关联');
                      } catch (error) {
                        message.error(errorText(error, '关联家长账号失败'));
                        throw error;
                      }
                    },
                  });
                }}>添加</Button></div>
                <div className="swm-guardian-list">
                  {guardians.map((guardian) => <div key={guardian.id}><div><strong>{guardian.guardian_name}</strong><span>{guardian.guardian_email || '只读周报'}</span></div><Button type="text" danger icon={<Trash2 size={16} />} onClick={async () => {
                    await removeGuardianLink(organizationId, applicationId, guardian.id);
                    setGuardians((items) => items.filter((item) => item.id !== guardian.id));
                  }} /></div>)}
                </div>
                <div className="swm-data-actions">
                  <Button icon={<Download size={17} />} onClick={async () => {
                    const data = await exportStudyData(organizationId, applicationId);
                    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
                    const anchor = document.createElement('a');
                    anchor.href = url;
                    anchor.download = `学之有道-${new Date().toISOString().slice(0, 10)}.json`;
                    anchor.click();
                    URL.revokeObjectURL(url);
                  }}>导出学习数据</Button>
                  <Button danger icon={<Trash2 size={17} />} onClick={() => Modal.confirm({
                    title: '删除全部学习数据？',
                    content: '题目图片、计划、错题、复习记录和周报将永久删除，此操作无法撤销。',
                    okText: '确认删除',
                    okButtonProps: { danger: true },
                    cancelText: '取消',
                    onOk: async () => {
                      await deleteStudyData(organizationId, applicationId);
                      await reload();
                    },
                  })}>删除我的数据</Button>
                </div>
              </section>
            )}
          </main>

          <nav className="swm-bottom-nav" aria-label="学之有道功能导航">
            {navItems.map(({ key, label, icon: Icon }) => (
              <button type="button" key={key} className={tab === key ? 'active' : ''} onClick={() => changeTab(key)}>
                <Icon size={21} /><span>{label}</span>
              </button>
            ))}
          </nav>
        </>
      )}

      <Modal
        className="swm-mistake-modal"
        title="手动录入错题"
        open={manualMistakeOpen}
        okText="保存并安排复习"
        cancelText="取消"
        confirmLoading={busyAction === 'manual-mistake'}
        onOk={() => void createManualMistake()}
        onCancel={closeManualMistake}
      >
        <Form
          form={manualMistakeForm}
          layout="vertical"
          initialValues={{ cause: 'concept' }}
        >
          <Form.Item label="题目图片">
            <input
              ref={manualImageInput}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              hidden
              onChange={(event) => chooseManualImage(event.target.files?.[0])}
            />
            {manualImageUrl ? (
              <div className="swm-manual-image">
                <div className="swm-image-stage" style={{ '--crop': `${manualCropPercent}%` } as CSSProperties}>
                  <img src={manualImageUrl} alt="待录入错题" style={{ transform: `rotate(${manualRotation}deg) scale(${100 / manualCropPercent})` }} />
                </div>
                <div className="swm-image-tools">
                  <Button icon={<RotateCw size={17} />} onClick={() => setManualRotation((value) => (value + 90) % 360)}>旋转</Button>
                  <div><span>裁剪范围</span><Slider min={55} max={100} value={manualCropPercent} onChange={setManualCropPercent} /></div>
                  <Button type="text" danger onClick={() => { setManualImageFile(null); setManualImageUrl(''); }}>移除</Button>
                </div>
              </div>
            ) : (
              <Button icon={<ImagePlus size={17} />} onClick={() => manualImageInput.current?.click()}>
                选择题目图片
              </Button>
            )}
          </Form.Item>
          <Form.Item name="problemText" label="题目文字" extra="图片和文字至少填写一项">
            <Input.TextArea rows={4} placeholder="可直接输入或补充校正题目内容" />
          </Form.Item>
          <Form.Item name="knowledgeSummary" label="考察知识点">
            <Input placeholder="例如：函数单调性、椭圆的离心率" />
          </Form.Item>
          <Form.Item name="cause" label="错因分类" rules={[{ required: true, message: '请选择错因' }]}>
            <Select options={causeOptions} />
          </Form.Item>
          <Form.Item name="notes" label="为什么做错">
            <Input.TextArea rows={3} placeholder="例如：忽略定义域，套错公式，计算时漏掉负号" />
          </Form.Item>
          <Form.Item name="correctAnswer" label="正确答案">
            <Input.TextArea rows={3} placeholder="填写答案或关键解题步骤" />
          </Form.Item>
          <Form.Item name="similarProblemTypes" label="同类题型" extra="多个题型请换行或用逗号分隔">
            <Input.TextArea rows={3} placeholder={'含参数函数的单调性\n根据单调性求参数范围'} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
