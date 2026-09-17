import {
  BarChart3,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  Factory,
  FilePenLine,
  Flame,
  Gauge,
  ImagePlus,
  Lightbulb,
  LockKeyhole,
  Megaphone,
  Menu,
  Newspaper,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  Settings2,
  Sparkles,
  TrendingUp,
  UserRound,
  UsersRound,
  Video,
  WandSparkles,
  X,
} from 'lucide-react';
import {
  FormEvent,
  ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';

import './styles.css';

type ViewKey = 'topics' | 'factory' | 'ip' | 'drafts' | 'publish' | 'data' | 'settings';
type LineType = 'article' | 'social' | 'voiceover' | 'short-drama';
type TopicStatus = 'todo' | 'producing' | 'done';

interface Topic {
  id: string;
  title: string;
  note: string;
  lineType?: LineType;
  source: 'manual' | 'hot';
  status: TopicStatus;
  createdAt: string;
}

interface ProductionTask {
  id: string;
  topicId: string;
  lineType: LineType;
  progress: number;
  stage: string;
}

interface Character {
  id: string;
  name: string;
  persona: string;
  accent: string;
  videoCount: number;
  locked: boolean;
}

interface Draft {
  id: string;
  title: string;
  lineType: LineType;
  body: string;
  updatedAt: string;
  status: 'review' | 'ready';
}

interface PublishRecord {
  id: string;
  draftId: string;
  title: string;
  lineType: LineType;
  platform: string;
  publishedAt: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
}

interface Settings {
  model: string;
  hotWindow: number;
  hitPercentile: number;
  speed: 'steady' | 'fast';
}

interface WorkbenchState {
  topics: Topic[];
  tasks: ProductionTask[];
  characters: Character[];
  drafts: Draft[];
  records: PublishRecord[];
  settings: Settings;
}

interface NewMediaWorkbenchAppProps {
  showHeader?: boolean;
  onBack?: () => void;
}

const STORAGE_KEY = 'agent-studio:newmedia-workbench:v1';

const lineMeta: Record<LineType, { label: string; short: string; color: string; stages: string[] }> = {
  article: {
    label: '长图文', short: '公众号 · 深度内容', color: 'blue',
    stages: ['生文写稿', '配图', '自动排版'],
  },
  social: {
    label: '短图文', short: '小红书 · 图文笔记', color: 'red',
    stages: ['封面大字', '图文生成', '正文润色'],
  },
  voiceover: {
    label: '口播短视频', short: '时事评论 · 约 1 分钟', color: 'amber',
    stages: ['口播稿', 'AI 配音', '形象合成'],
  },
  'short-drama': {
    label: '微短剧', short: '剧情演绎 · 约 1 分钟', color: 'green',
    stages: ['剧本分镜', '画面生成', '剪辑合成'],
  },
};

const hotTopics = [
  { title: 'AI 智能体正在重写一人公司的工作流', source: '36Kr', heat: '98.6w' },
  { title: '年轻人开始用数字分身经营个人品牌', source: '小红书', heat: '76.2w' },
  { title: '内容团队为什么都在搭建自己的素材中台', source: '微信', heat: '53.4w' },
  { title: '短视频脚本的黄金 3 秒又变了', source: '抖音', heat: '41.8w' },
  { title: '从流量思维到信任资产：品牌内容的新周期', source: '知乎', heat: '32.9w' },
  { title: '一条内容如何改写成四个平台版本', source: '微博', heat: '28.7w' },
];

const initialState: WorkbenchState = {
  topics: [
    {
      id: 'topic-1', title: 'AI 会替代内容创作者吗？真正被替代的是这三种工作方式',
      note: '结合个人工作流给出具体方法', lineType: 'article', source: 'manual', status: 'todo',
      createdAt: '2026-09-17T09:20:00.000Z',
    },
    {
      id: 'topic-2', title: '我用一周搭了一支不会下班的内容团队',
      note: '用第一人称展示完整流程', lineType: 'voiceover', source: 'hot', status: 'producing',
      createdAt: '2026-09-16T15:40:00.000Z',
    },
    {
      id: 'topic-3', title: '新媒体人必存：一份内容复用检查清单',
      note: '做成适合收藏的清单卡片', lineType: 'social', source: 'manual', status: 'done',
      createdAt: '2026-09-15T10:10:00.000Z',
    },
  ],
  tasks: [
    { id: 'task-1', topicId: 'topic-2', lineType: 'voiceover', progress: 68, stage: 'AI 配音中' },
  ],
  characters: [
    { id: 'ip-1', name: '主理人小新', persona: '冷静、犀利，擅长把复杂工具讲得简单。', accent: '#1d5cff', videoCount: 12, locked: true },
    { id: 'ip-2', name: '灵感搭子', persona: '轻松、有梗，适合趋势观察和案例拆解。', accent: '#ff4d2e', videoCount: 0, locked: false },
    { id: 'ip-3', name: '数据侦探', persona: '理性克制，用数据验证内容判断。', accent: '#0fa968', videoCount: 4, locked: true },
  ],
  drafts: [
    {
      id: 'draft-1', title: '新媒体人必存：一份内容复用检查清单', lineType: 'social',
      body: '同一个观点，不该只活在一条内容里。先提取核心结论，再按平台语境重组结构：公众号讲逻辑，小红书讲场景，视频讲冲突。',
      updatedAt: '今天 10:42', status: 'review',
    },
    {
      id: 'draft-2', title: '内容中台不是资料库，而是你的第二大脑', lineType: 'article',
      body: '真正有效的内容中台，不是把文件放在一起，而是让选题、素材、成品和数据之间建立可检索、可复用的关系。',
      updatedAt: '昨天 18:20', status: 'ready',
    },
  ],
  records: [
    { id: 'pub-1', draftId: 'published-1', title: '一个人也能跑起来的 AI 内容流水线', lineType: 'article', platform: '微信公众号', publishedAt: '2026-09-16 20:00', views: 12840, likes: 896, comments: 146, shares: 512 },
    { id: 'pub-2', draftId: 'published-2', title: '别再让好选题只发一次', lineType: 'social', platform: '小红书', publishedAt: '2026-09-15 12:30', views: 8920, likes: 1260, comments: 82, shares: 634 },
    { id: 'pub-3', draftId: 'published-3', title: '我把内容团队装进了电脑里', lineType: 'voiceover', platform: '抖音', publishedAt: '2026-09-13 18:10', views: 23750, likes: 2180, comments: 235, shares: 784 },
  ],
  settings: { model: '本地智能引擎', hotWindow: 3, hitPercentile: 80, speed: 'steady' },
};

const navItems: Array<{ key: ViewKey; label: string; icon: typeof Lightbulb }> = [
  { key: 'topics', label: '选题中心', icon: Lightbulb },
  { key: 'factory', label: '内容工厂', icon: Factory },
  { key: 'ip', label: 'IP 形象库', icon: UsersRound },
  { key: 'drafts', label: '草稿箱', icon: FilePenLine },
  { key: 'publish', label: '发布中心', icon: Send },
  { key: 'data', label: '数据看板', icon: BarChart3 },
  { key: 'settings', label: '系统设置', icon: Settings2 },
];

const uid = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const number = (value: number) => new Intl.NumberFormat('zh-CN', { notation: value > 9999 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value);

function loadState(): WorkbenchState {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved ? { ...initialState, ...JSON.parse(saved) as WorkbenchState } : initialState;
  } catch {
    return initialState;
  }
}

function Tag({ children, tone = 'gray' }: { children: ReactNode; tone?: string }) {
  return <span className={`nmw-tag nmw-tag--${tone}`}>{children}</span>;
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    focusable()[0]?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('keydown', handleKey);
      returnFocus?.focus();
    };
  }, [onClose]);
  return (
    <div className="nmw-modal-mask" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="nmw-modal" role="dialog" aria-modal="true" aria-labelledby="nmw-modal-title">
        <header><h2 id="nmw-modal-title">{title}</h2><button className="nmw-icon-button" onClick={onClose} aria-label="关闭弹窗"><X /></button></header>
        {children}
      </section>
    </div>
  );
}

function PageTitle({ title, kicker, actions }: { title: string; kicker?: string; actions?: ReactNode }) {
  return (
    <header className="nmw-page-title">
      <div><p>{kicker}</p><h1>{title}</h1></div>
      {actions && <div className="nmw-page-actions">{actions}</div>}
    </header>
  );
}

function StatCard({ value, label, detail, tone }: { value: string | number; label: string; detail: string; tone?: string }) {
  return (
    <article className="nmw-card nmw-stat-card">
      <span className={`nmw-stat-accent ${tone ? `is-${tone}` : ''}`} />
      <strong>{value}</strong><span>{label}</span><small>{detail}</small>
    </article>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="nmw-empty"><CircleDot /><strong>{title}</strong><span>{detail}</span></div>;
}

export function NewMediaWorkbenchApp({ showHeader = false, onBack }: NewMediaWorkbenchAppProps) {
  const [state, setState] = useState<WorkbenchState>(loadState);
  const [view, setView] = useState<ViewKey>('topics');
  const [mobileNav, setMobileNav] = useState(false);
  const [topicFilter, setTopicFilter] = useState<TopicStatus | 'all'>('todo');
  const [hotOffset, setHotOffset] = useState(0);
  const [modal, setModal] = useState<'topic' | 'start' | 'ip' | 'publish' | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<string | null>(null);
  const [toast, setToast] = useState('');

  useEffect(() => window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state)), [state]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!state.tasks.length) return;
    const timer = window.setInterval(() => {
      setState((current) => {
        let changed = false;
        const completed: ProductionTask[] = [];
        const tasks = current.tasks.flatMap((task) => {
          const progress = Math.min(100, task.progress + 4);
          changed = changed || progress !== task.progress;
          if (progress >= 100) {
            completed.push(task);
            return [];
          }
          const stages = lineMeta[task.lineType].stages;
          const stage = stages[Math.min(stages.length - 1, Math.floor(progress / 34))];
          return [{ ...task, progress, stage: `${stage}中` }];
        });
        if (!changed) return current;
        const topics = current.topics.map((topic) => completed.some((task) => task.topicId === topic.id) ? { ...topic, status: 'done' as const } : topic);
        const newDrafts = completed.map((task) => {
          const topic = current.topics.find((item) => item.id === task.topicId)!;
          return {
            id: uid('draft'), title: topic.title, lineType: task.lineType,
            body: `${topic.note || '围绕核心观点展开内容。'}\n\n这是一份由内容工厂生成的初稿，已完成结构、表达和平台语气适配，请在发布前完成最终把关。`,
            updatedAt: '刚刚', status: 'review' as const,
          };
        });
        return { ...current, tasks, topics, drafts: [...newDrafts, ...current.drafts] };
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [state.tasks.length]);

  const notify = (message: string) => setToast(message);
  const go = (key: ViewKey) => { setView(key); setMobileNav(false); };

  const addTopic = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const title = String(form.get('title') || '').trim();
    if (!title) return;
    const topic: Topic = {
      id: uid('topic'), title, note: String(form.get('note') || '').trim(),
      lineType: (form.get('lineType') || undefined) as LineType | undefined,
      source: 'manual', status: 'todo', createdAt: new Date().toISOString(),
    };
    setState((current) => ({ ...current, topics: [topic, ...current.topics] }));
    setTopicFilter('todo'); setModal(null); notify('选题已加入选题池');
  };

  const addHotTopic = (title: string) => {
    const topic: Topic = { id: uid('topic'), title, note: '来自今日热点', source: 'hot', status: 'todo', createdAt: new Date().toISOString() };
    setState((current) => ({ ...current, topics: [topic, ...current.topics] }));
    notify('热点已转为选题');
  };

  const startProduction = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedTopic) return;
    const form = new FormData(event.currentTarget);
    const lineType = String(form.get('lineType') || 'article') as LineType;
    const task: ProductionTask = { id: uid('task'), topicId: selectedTopic, lineType, progress: 8, stage: `${lineMeta[lineType].stages[0]}中` };
    setState((current) => ({
      ...current,
      topics: current.topics.map((topic) => topic.id === selectedTopic ? { ...topic, status: 'producing', lineType } : topic),
      tasks: [task, ...current.tasks],
    }));
    setModal(null); go('factory'); notify('制作任务已启动');
  };

  const saveCharacter = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get('name') || '').trim();
    const persona = String(form.get('persona') || '').trim();
    if (!name || !persona) return;
    const accents = ['#1d5cff', '#ff4d2e', '#0fa968', '#e8a013'];
    const character: Character = { id: uid('ip'), name, persona, accent: accents[state.characters.length % accents.length], videoCount: 0, locked: false };
    setState((current) => ({ ...current, characters: [...current.characters, character] }));
    setModal(null); notify('新 IP 形象已保存');
  };

  const updateDraft = (draftId: string, status: Draft['status']) => {
    setState((current) => ({ ...current, drafts: current.drafts.map((draft) => draft.id === draftId ? { ...draft, status, updatedAt: '刚刚' } : draft) }));
    notify(status === 'ready' ? '已通过审核，等待发布' : '已打回到修改队列');
  };

  const publishDraft = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const draft = state.drafts.find((item) => item.id === selectedDraft);
    if (!draft) return;
    const form = new FormData(event.currentTarget);
    const platform = String(form.get('platform') || '微信公众号');
    const record: PublishRecord = {
      id: uid('pub'), draftId: draft.id, title: draft.title, lineType: draft.lineType,
      platform, publishedAt: new Date().toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-'),
      views: 0, likes: 0, comments: 0, shares: 0,
    };
    setState((current) => ({ ...current, drafts: current.drafts.filter((item) => item.id !== draft.id), records: [record, ...current.records] }));
    setModal(null); go('publish'); notify(`已登记发布到${platform}`);
  };

  const resetDemo = () => {
    setState(initialState);
    notify('演示数据已恢复');
  };

  const renderTopics = () => {
    const visibleTopics = state.topics.filter((topic) => topicFilter === 'all' || topic.status === topicFilter);
    const stats = {
      todo: state.topics.filter((topic) => topic.status === 'todo').length,
      producing: state.topics.filter((topic) => topic.status === 'producing').length,
      done: state.topics.filter((topic) => topic.status === 'done').length,
    };
    const hot = [0, 1, 2, 3].map((index) => hotTopics[(index + hotOffset) % hotTopics.length]);
    return <>
      <PageTitle title="今天发什么？" kicker="TOPIC DESK · 选题编辑台" actions={<>
        <button className="nmw-button nmw-button--ghost" onClick={() => setHotOffset((value) => (value + 1) % hotTopics.length)}><RefreshCw />换一批热点</button>
        <button className="nmw-button nmw-button--primary" onClick={() => setModal('topic')}><Plus />记一个新选题</button>
      </>} />
      <div className="nmw-stat-grid">
        <StatCard value={stats.todo} label="待做选题" detail="灵感等待开工" tone="red" />
        <StatCard value={stats.producing} label="制作中" detail="AI 产线正在运行" tone="blue" />
        <StatCard value={stats.done} label="本周完成" detail="持续稳定输出" tone="green" />
        <StatCard value={state.records.length} label="已发布" detail="全平台内容资产" tone="amber" />
      </div>
      <div className="nmw-two-column">
        <section className="nmw-card">
          <div className="nmw-card-head"><div><span className="nmw-overline">TOPIC POOL</span><h2>选题池</h2></div>
            <label className="nmw-select-label"><span className="sr-only">筛选选题状态</span><select value={topicFilter} onChange={(event) => setTopicFilter(event.target.value as TopicStatus | 'all')}><option value="todo">待做</option><option value="producing">制作中</option><option value="done">已完成</option><option value="all">全部</option></select></label>
          </div>
          <div className="nmw-topic-list">
            {visibleTopics.length === 0 ? <EmptyState title="这个分组还没有选题" detail="记录灵感，或从右侧热点快速转入。" /> : visibleTopics.map((topic) => (
              <article className="nmw-topic-row" key={topic.id}>
                <span className={`nmw-status-dot is-${topic.status}`} />
                <div><h3>{topic.title}</h3><p>{topic.note || '暂未补充创作角度'}</p><div className="nmw-topic-meta">
                  <Tag tone={topic.source === 'hot' ? 'amber' : 'gray'}>{topic.source === 'hot' ? '热点转入' : '手动记录'}</Tag>
                  {topic.lineType && <Tag tone={lineMeta[topic.lineType].color}>{lineMeta[topic.lineType].label}</Tag>}
                  <span>{new Date(topic.createdAt).toLocaleDateString('zh-CN')}</span>
                </div></div>
                {topic.status === 'todo' && <button className="nmw-button nmw-button--ink nmw-button--small" onClick={() => { setSelectedTopic(topic.id); setModal('start'); }}>开工<ChevronRight /></button>}
                {topic.status === 'producing' && <Tag tone="blue">制作中</Tag>}
                {topic.status === 'done' && <Tag tone="green"><Check />已完成</Tag>}
              </article>
            ))}
          </div>
        </section>
        <section className="nmw-card">
          <div className="nmw-card-head"><div><span className="nmw-overline">HOT NOW</span><h2>今日热点</h2></div><Tag tone="amber"><Flame />实时更新</Tag></div>
          <div className="nmw-hot-list">{hot.map((item, index) => <article key={item.title}>
            <span className="nmw-rank">0{index + 1}</span><div><h3>{item.title}</h3><p>{item.source} · 热度 {item.heat}</p></div>
            <button className="nmw-icon-button" onClick={() => addHotTopic(item.title)} aria-label={`将“${item.title}”转为选题`}><Plus /></button>
          </article>)}</div>
        </section>
      </div>
    </>;
  };

  const renderFactory = () => <>
    <PageTitle title="内容工厂 · 四条产线" kicker="AI PRODUCTION FLOOR" actions={<Tag tone="green"><CircleDot />引擎在线</Tag>} />
    <div className="nmw-line-grid">{(Object.entries(lineMeta) as Array<[LineType, typeof lineMeta[LineType]]>).map(([key, meta], index) => {
      const Icon = [Newspaper, ImagePlus, Megaphone, Video][index];
      return <article className={`nmw-card nmw-line-card is-${meta.color}`} key={key}>
        <span className="nmw-line-number">0{index + 1}</span><span className="nmw-line-icon"><Icon /></span><h2>{meta.label}</h2><p>{meta.short}</p>
        <div className="nmw-flow">{meta.stages.map((stage, stageIndex) => <span key={stage}>{stageIndex > 0 && <ChevronRight />}<b>{stage}</b></span>)}</div>
      </article>;
    })}</div>
    <section className="nmw-card nmw-queue">
      <div className="nmw-card-head"><div><span className="nmw-overline">PRODUCTION QUEUE</span><h2>制作任务</h2></div><Tag tone="blue">{state.tasks.length} 条运行中</Tag></div>
      {state.tasks.length === 0 ? <EmptyState title="产线空闲" detail="从选题中心选择一个题目开始制作。" /> : state.tasks.map((task) => {
        const topic = state.topics.find((item) => item.id === task.topicId);
        return <article className="nmw-task-row" key={task.id}><span className={`nmw-line-chip is-${lineMeta[task.lineType].color}`}>{lineMeta[task.lineType].label}</span><div className="nmw-task-copy"><h3>{topic?.title}</h3><p>{task.stage}</p></div><div className="nmw-progress" aria-label={`制作进度 ${task.progress}%`}><i style={{ width: `${task.progress}%` }} /></div><strong>{task.progress}%</strong></article>;
      })}
    </section>
  </>;

  const renderIp = () => <>
    <PageTitle title="IP 形象库" kicker="CHARACTER BIBLE" actions={<button className="nmw-button nmw-button--primary" onClick={() => setModal('ip')}><Plus />创建新形象</button>} />
    <div className="nmw-ip-grid">{state.characters.map((character) => <article className="nmw-card nmw-ip-card" key={character.id}>
      <div className="nmw-avatar" style={{ '--avatar-accent': character.accent } as React.CSSProperties}><UserRound /><span>{character.name.slice(0, 1)}</span>{character.locked && <Tag tone="gray"><LockKeyhole />已锁定</Tag>}</div>
      <h2>{character.name}</h2><p>{character.persona}</p><footer><span><Video />出演 {character.videoCount} 条</span><button className="nmw-button nmw-button--ghost nmw-button--small" disabled={character.locked}>{character.locked ? '定妆锁定' : '编辑设定'}</button></footer>
    </article>)}</div>
    <aside className="nmw-notice"><LockKeyhole /><p><strong>一致性规则</strong>形象一旦出演过视频，定妆信息会自动锁定。需要更换造型时，请新建形象，保留历史内容的一致性。</p></aside>
  </>;

  const renderDrafts = () => <>
    <PageTitle title="草稿箱 · 把关中心" kicker="EDITORIAL REVIEW" actions={<Tag tone="red">{state.drafts.filter((draft) => draft.status === 'review').length} 篇待审核</Tag>} />
    <div className="nmw-draft-list">{state.drafts.length === 0 ? <section className="nmw-card"><EmptyState title="草稿箱已清空" detail="新的制作任务完成后会自动进入这里。" /></section> : state.drafts.map((draft) => <article className="nmw-card nmw-draft-card" key={draft.id}>
      <header><div><Tag tone={lineMeta[draft.lineType].color}>{lineMeta[draft.lineType].label}</Tag><h2>{draft.title}</h2><span>{draft.updatedAt}更新</span></div><Tag tone={draft.status === 'review' ? 'red' : 'green'}>{draft.status === 'review' ? '待把关' : '可发布'}</Tag></header>
      <p className="nmw-draft-body">{draft.body}</p>
      <footer>
        {draft.status === 'review' ? <><button className="nmw-button nmw-button--ghost" onClick={() => updateDraft(draft.id, 'review')}><RotateCcw />打回重做</button><button className="nmw-button nmw-button--primary" onClick={() => updateDraft(draft.id, 'ready')}><Check />审核通过</button></> : <button className="nmw-button nmw-button--ink" onClick={() => { setSelectedDraft(draft.id); setModal('publish'); }}><Send />去发布</button>}
      </footer>
    </article>)}</div>
  </>;

  const renderPublish = () => {
    const ready = state.drafts.filter((draft) => draft.status === 'ready');
    return <>
      <PageTitle title="发布中心" kicker="DISTRIBUTION DESK" actions={<Tag tone="green"><Check />渠道状态正常</Tag>} />
      <div className="nmw-two-column nmw-publish-layout">
        <section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">READY TO SHIP</span><h2>待发布</h2></div><Tag tone="amber">{ready.length} 篇</Tag></div>
          {ready.length === 0 ? <EmptyState title="没有待发布内容" detail="在草稿箱审核通过后即可发布。" /> : ready.map((draft) => <article className="nmw-ready-row" key={draft.id}><span className={`nmw-line-icon is-${lineMeta[draft.lineType].color}`}><Send /></span><div><h3>{draft.title}</h3><p>{lineMeta[draft.lineType].label} · 已完成审核</p></div><button className="nmw-button nmw-button--primary nmw-button--small" onClick={() => { setSelectedDraft(draft.id); setModal('publish'); }}>选择渠道</button></article>)}
        </section>
        <section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">PUBLISH LOG</span><h2>发布记录</h2></div></div>
          <div className="nmw-publish-log">{state.records.slice(0, 6).map((record) => <article key={record.id}><span className="nmw-platform-mark">{record.platform.slice(0, 1)}</span><div><h3>{record.title}</h3><p>{record.platform} · {record.publishedAt}</p></div><Tag tone="green">已发布</Tag></article>)}</div>
        </section>
      </div>
    </>;
  };

  const renderData = () => {
    const totals = state.records.reduce((result, record) => ({ views: result.views + record.views, likes: result.likes + record.likes, shares: result.shares + record.shares }), { views: 0, likes: 0, shares: 0 });
    const maxViews = Math.max(1, ...state.records.map((record) => record.views));
    const lineStats = (Object.keys(lineMeta) as LineType[]).map((line) => ({ line, views: state.records.filter((record) => record.lineType === line).reduce((sum, record) => sum + record.views, 0) }));
    return <>
      <PageTitle title="数据看板" kicker="PERFORMANCE REVIEW" actions={<Tag tone="blue"><Gauge />近 7 天</Tag>} />
      <div className="nmw-stat-grid"><StatCard value={state.records.length} label="发布内容" detail="跨平台累计" tone="blue" /><StatCard value={number(totals.views)} label="阅读 / 播放" detail="总曝光量" tone="red" /><StatCard value={number(totals.likes)} label="点赞" detail="内容认可度" tone="green" /><StatCard value={number(totals.shares)} label="转发 / 收藏" detail="高价值互动" tone="amber" /></div>
      <div className="nmw-two-column nmw-data-layout"><section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">LINE PERFORMANCE</span><h2>产线表现</h2></div></div>
        <div className="nmw-bar-chart">{lineStats.map((item) => <div key={item.line}><span>{lineMeta[item.line].label}</span><div><i className={`is-${lineMeta[item.line].color}`} style={{ width: `${Math.max(4, item.views / maxViews * 100)}%` }} /></div><strong>{number(item.views)}</strong></div>)}</div>
        <aside className="nmw-insight"><TrendingUp /><p><strong>本周洞察</strong>口播短视频带来最高曝光。建议把表现最好的观点继续拆成短图文，延长内容生命周期。</p></aside>
      </section><section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">TOP CONTENT</span><h2>内容排行</h2></div></div>
        <div className="nmw-ranking">{[...state.records].sort((a, b) => b.views - a.views).slice(0, 5).map((record, index) => <article key={record.id}><span>{index + 1}</span><div><h3>{record.title}</h3><p>{record.platform} · {lineMeta[record.lineType].label}</p></div><strong>{number(record.views)}</strong></article>)}</div>
      </section></div>
      <section className="nmw-card nmw-table-card"><div className="nmw-card-head"><div><span className="nmw-overline">CONTENT METRICS</span><h2>内容明细</h2></div></div><div className="nmw-table-scroll"><table><thead><tr><th>内容</th><th>产线</th><th>平台</th><th>阅读/播放</th><th>点赞</th><th>评论</th><th>转发/收藏</th></tr></thead><tbody>{state.records.map((record) => <tr key={record.id}><td>{record.title}</td><td>{lineMeta[record.lineType].label}</td><td>{record.platform}</td><td>{number(record.views)}</td><td>{number(record.likes)}</td><td>{number(record.comments)}</td><td>{number(record.shares)}</td></tr>)}</tbody></table></div></section>
    </>;
  };

  const renderSettings = () => <>
    <PageTitle title="系统设置" kicker="WORKBENCH PREFERENCES" />
    <div className="nmw-settings-grid"><section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">CONTENT ENGINE</span><h2>内容引擎</h2></div><Bot /></div>
      <label className="nmw-field"><span>默认模型</span><select value={state.settings.model} onChange={(event) => setState((current) => ({ ...current, settings: { ...current.settings, model: event.target.value } }))}><option>本地智能引擎</option><option>OpenAI 兼容模型</option><option>自定义 API</option></select><small>切换后将用于新启动的制作任务。</small></label>
      <div className="nmw-setting-row"><div><strong>生成速度</strong><span>稳定模式质量优先，快速模式适合批量草稿。</span></div><div className="nmw-segment"><button className={state.settings.speed === 'steady' ? 'active' : ''} onClick={() => setState((current) => ({ ...current, settings: { ...current.settings, speed: 'steady' } }))}>稳定</button><button className={state.settings.speed === 'fast' ? 'active' : ''} onClick={() => setState((current) => ({ ...current, settings: { ...current.settings, speed: 'fast' } }))}>快速</button></div></div>
    </section><section className="nmw-card"><div className="nmw-card-head"><div><span className="nmw-overline">DATA RULES</span><h2>数据规则</h2></div><Gauge /></div>
      <label className="nmw-field"><span>热点时间窗口</span><div className="nmw-number-input"><input type="number" min="1" max="30" value={state.settings.hotWindow} onChange={(event) => setState((current) => ({ ...current, settings: { ...current.settings, hotWindow: Number(event.target.value) } }))} /><b>天</b></div><small>选题中心优先抓取这个时间范围内的热点。</small></label>
      <label className="nmw-field"><span>爆款判定分位</span><div className="nmw-number-input"><input type="number" min="50" max="99" value={state.settings.hitPercentile} onChange={(event) => setState((current) => ({ ...current, settings: { ...current.settings, hitPercentile: Number(event.target.value) } }))} /><b>%</b></div><small>高于历史内容该分位的数据会标记为爆款候选。</small></label>
    </section><section className="nmw-card nmw-danger-card"><div><span className="nmw-overline">LOCAL DATA</span><h2>演示数据</h2><p>工作台数据保存在当前浏览器中。重置会恢复为初始示例内容。</p></div><button className="nmw-button nmw-button--danger" onClick={resetDemo}><RotateCcw />恢复演示数据</button></section></div>
  </>;

  const content: Record<ViewKey, () => ReactNode> = { topics: renderTopics, factory: renderFactory, ip: renderIp, drafts: renderDrafts, publish: renderPublish, data: renderData, settings: renderSettings };
  const activeLabel = navItems.find((item) => item.key === view)?.label;

  return (
    <div className="nmw-app">
      <a className="nmw-skip-link" href="#nmw-main">跳到主要内容</a>
      <aside className={`nmw-sidebar ${mobileNav ? 'is-open' : ''}`}>
        <div className="nmw-brand"><span>新</span><div><strong>新媒体工作台</strong><small>AI CONTENT FACTORY</small></div><button className="nmw-icon-button nmw-mobile-close" onClick={() => setMobileNav(false)} aria-label="关闭导航"><X /></button></div>
        {showHeader && onBack && <button className="nmw-back-button" onClick={onBack}><ChevronRight />返回应用中心</button>}
        <nav aria-label="应用导航">{navItems.map((item) => { const Icon = item.icon; return <button key={item.key} className={view === item.key ? 'active' : ''} onClick={() => go(item.key)} aria-current={view === item.key ? 'page' : undefined}><Icon /><span>{item.label}</span>{item.key === 'drafts' && state.drafts.some((draft) => draft.status === 'review') && <b>{state.drafts.filter((draft) => draft.status === 'review').length}</b>}</button>; })}</nav>
        <footer><span><i />本地引擎在线</span><p>数据本地保存 · 随时可恢复</p></footer>
      </aside>
      {mobileNav && <button className="nmw-nav-scrim" aria-label="关闭导航" onClick={() => setMobileNav(false)} />}
      <main id="nmw-main" className="nmw-main" tabIndex={-1}>
        <div className="nmw-mobile-bar"><button className="nmw-icon-button" onClick={() => setMobileNav(true)} aria-label="打开导航"><Menu /></button><span>{activeLabel}</span><div className="nmw-mobile-mark">新</div></div>
        <div className="nmw-content">{content[view]()}</div>
      </main>
      {modal === 'topic' && <Modal title="记一个新选题" onClose={() => setModal(null)}><form onSubmit={addTopic} className="nmw-form"><label><span>选题标题 <b>*</b></span><input name="title" autoFocus maxLength={100} required placeholder="一句话说清要做什么" /></label><label><span>预设内容形式</span><select name="lineType" defaultValue=""><option value="">开工时再选</option>{(Object.entries(lineMeta) as Array<[LineType, typeof lineMeta[LineType]]>).map(([key, value]) => <option value={key} key={key}>{value.label}</option>)}</select></label><label><span>想法备注</span><textarea name="note" maxLength={500} placeholder="创作角度、核心观点、参考素材……" /></label><footer><button type="button" className="nmw-button nmw-button--ghost" onClick={() => setModal(null)}>取消</button><button className="nmw-button nmw-button--primary"><Plus />保存选题</button></footer></form></Modal>}
      {modal === 'start' && <Modal title="启动内容产线" onClose={() => setModal(null)}><form onSubmit={startProduction} className="nmw-form"><p className="nmw-modal-lead">为这个选题选择最合适的内容形式，AI 会按对应产线完成初稿。</p><fieldset><legend>内容形式</legend><div className="nmw-radio-grid">{(Object.entries(lineMeta) as Array<[LineType, typeof lineMeta[LineType]]>).map(([key, value], index) => <label key={key}><input type="radio" name="lineType" value={key} defaultChecked={(state.topics.find((topic) => topic.id === selectedTopic)?.lineType || 'article') === key} /><span><b>0{index + 1} · {value.label}</b><small>{value.short}</small></span></label>)}</div></fieldset><footer><button type="button" className="nmw-button nmw-button--ghost" onClick={() => setModal(null)}>取消</button><button className="nmw-button nmw-button--primary"><WandSparkles />开始制作</button></footer></form></Modal>}
      {modal === 'ip' && <Modal title="创建新形象" onClose={() => setModal(null)}><form onSubmit={saveCharacter} className="nmw-form"><label><span>形象名称 <b>*</b></span><input name="name" autoFocus required maxLength={20} placeholder="例如：趋势观察员" /></label><label><span>人设描述 <b>*</b></span><textarea name="persona" required minLength={10} maxLength={500} placeholder="外貌、性格、表达风格和擅长领域……" /></label><div className="nmw-avatar-preview"><Sparkles /><span>保存后将自动生成形象识别色</span></div><footer><button type="button" className="nmw-button nmw-button--ghost" onClick={() => setModal(null)}>取消</button><button className="nmw-button nmw-button--primary"><Plus />保存形象</button></footer></form></Modal>}
      {modal === 'publish' && <Modal title="选择发布渠道" onClose={() => setModal(null)}><form onSubmit={publishDraft} className="nmw-form"><p className="nmw-modal-lead">发布登记后，内容数据将进入统一看板。</p><fieldset><legend>发布平台</legend><div className="nmw-platform-grid">{['微信公众号', '小红书', '抖音', '视频号', '知乎'].map((platform, index) => <label key={platform}><input type="radio" name="platform" value={platform} defaultChecked={index === 0} /><span>{platform.slice(0, 1)}<b>{platform}</b></span></label>)}</div></fieldset><footer><button type="button" className="nmw-button nmw-button--ghost" onClick={() => setModal(null)}>取消</button><button className="nmw-button nmw-button--primary"><Send />确认发布登记</button></footer></form></Modal>}
      <div className={`nmw-toast ${toast ? 'show' : ''}`} role="status" aria-live="polite"><Check />{toast}</div>
    </div>
  );
}

export default NewMediaWorkbenchApp;
