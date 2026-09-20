import type {
  CurriculumKnowledgeItem,
  CurriculumTree,
  StudyDashboard,
  StudyMastery,
  StudyMistake,
  StudyReview,
  StudySubject,
  SubjectEnrollment,
} from '@/types/studyWithMethod';

export type ReviewMode = 'due' | 'quiz' | 'cards' | 'map';

export interface LearningAction {
  id: 'quiz' | 'cards' | 'map';
  mode: Exclude<ReviewMode, 'due'>;
  subject: StudySubject;
  title: string;
  description: string;
  badge: string;
}

export interface StudyFlashcard {
  id: string;
  subject: StudySubject;
  question: string;
  answer: string;
  imageUrl: string;
  knowledgeLabel: string;
  mastery: number;
  reviewId?: string;
}

export type KnowledgeNodeStatus = 'unstarted' | 'needs-work' | 'learning' | 'mastered' | 'current';

export interface KnowledgeMapNode {
  id: string;
  label: string;
  score: number | null;
  status: KnowledgeNodeStatus;
  detail: string;
  group?: string;
  summary?: string;
  objectives?: string[];
  prerequisites?: string[];
  commonMistakes?: string[];
  keywords?: string[];
  competencyTags?: string[];
  knowledgeItems?: CurriculumKnowledgeItem[];
}

const subjectLabels: Record<StudySubject, string> = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', politics: '思想政治', history: '历史', geography: '地理',
};

function preferredSubject(dashboard: Extract<StudyDashboard, { mode: 'student' }>) {
  return dashboard.profile.focus_subjects[0]
    || dashboard.profile.enrollments[0]?.subject
    || 'math';
}

export function buildLearningActions(
  dashboard: Extract<StudyDashboard, { mode: 'student' }>,
): LearningAction[] {
  const fallback = preferredSubject(dashboard);
  const dueSubject = dashboard.due_reviews[0]?.subject || fallback;
  const weakest = [...dashboard.masteries].sort((a, b) => a.score - b.score)[0];
  const quizSubject = dashboard.profile.focus_subjects.find((subject) => (
    dashboard.stats_by_subject.some((item) => item.subject === subject && item.mistake_count > 0)
  )) || dueSubject;
  const dueCount = dashboard.due_reviews.filter((item) => item.subject === dueSubject).length;

  return [
    {
      id: 'quiz',
      mode: 'quiz',
      subject: quizSubject,
      title: '3 分钟小测',
      description: dashboard.mistake_count
        ? `从近期错题中抽题，点选结果即可完成`
        : `快速检查${subjectLabels[quizSubject]}学习状态`,
      badge: '随时开始',
    },
    {
      id: 'cards',
      mode: 'cards',
      subject: dueSubject,
      title: dueCount ? `${dueCount} 张卡片待巩固` : '翻一组记忆卡片',
      description: dueCount ? '翻面回忆，再点会、模糊或不会' : '从错题和知识总结中自动生成',
      badge: dueCount ? '今日到期' : '轻量复习',
    },
    {
      id: 'map',
      mode: 'map',
      subject: weakest?.subject || fallback,
      title: '查看知识点地图',
      description: weakest
        ? `${subjectLabels[weakest.subject]} · ${weakest.knowledge_point_name}需要优先巩固`
        : '查看当前章节、薄弱点与掌握进度',
      badge: weakest ? `${weakest.score}% 掌握` : '学习路径',
    },
  ];
}

export function buildFlashcards(
  subject: StudySubject,
  mistakes: StudyMistake[],
  reviews: StudyReview[],
): StudyFlashcard[] {
  const reviewByMistake = new Map(reviews.map((review) => [review.mistake.id, review.id]));
  return mistakes
    .filter((mistake) => mistake.subject === subject)
    .sort((a, b) => a.mastery - b.mastery)
    .map((mistake) => {
      const problemText = mistake.problem.confirmed_text || mistake.problem.original_text;
      const knowledgeLabel = mistake.problem.knowledge_point_name
        || mistake.knowledge_summary
        || mistake.cause_label;
      const answer = mistake.correct_answer
        || mistake.knowledge_summary
        || `重点检查“${mistake.cause_label}”。先说出正确方法，再对照原题复盘。`;
      return {
        id: mistake.id,
        subject: mistake.subject,
        question: problemText || `看题图，回忆这道${subjectLabels[subject]}题的关键步骤`,
        answer,
        imageUrl: mistake.problem.source_image_url,
        knowledgeLabel,
        mastery: mistake.mastery,
        reviewId: reviewByMistake.get(mistake.id),
      };
    });
}

function masteryStatus(score: number): KnowledgeNodeStatus {
  if (score >= 80) return 'mastered';
  if (score >= 50) return 'learning';
  return 'needs-work';
}

export function formatKnowledgeCondition(value: string) {
  const condition = value.trim();
  if (!condition || condition.includes('$') || condition.includes('\\(') || condition.includes('\\[')) {
    return condition;
  }
  const containsLatexCommand = /\\[a-zA-Z]+/.test(condition);
  const containsComparison = /[=<>≤≥≠]/.test(condition);
  const containsChinese = /[\u3400-\u9fff]/.test(condition);
  return containsLatexCommand || (containsComparison && !containsChinese)
    ? `$${condition}$`
    : condition;
}

export function buildKnowledgeMapNodes(
  enrollment: SubjectEnrollment | undefined,
  subject: StudySubject,
  masteries: StudyMastery[],
  curriculum?: CurriculumTree | null,
): KnowledgeMapNode[] {
  const subjectMasteries = masteries.filter((mastery) => mastery.subject === subject);
  const masteryDetail = (mastery: StudyMastery) => (
    `${mastery.attempts_count} 次练习 · ${mastery.correct_count} 次正确 · ${
      mastery.confidence < 50 ? '数据较少' : `可信度 ${mastery.confidence}%`
    }`
  );
  if (curriculum) {
    const masteryByCode = new Map(subjectMasteries.map((mastery) => [mastery.knowledge_point_code, mastery]));
    const masteryByName = new Map(subjectMasteries.map((mastery) => [mastery.knowledge_point_name.trim(), mastery]));
    const weakTopics = new Set((enrollment?.weak_topics || []).map((topic) => topic.trim()));
    const currentChapter = enrollment?.current_chapter.trim();
    const nodes: KnowledgeMapNode[] = [];

    curriculum.volumes.forEach((volume) => {
      volume.chapters.forEach((chapter) => {
        chapter.sections.forEach((section) => {
          section.knowledge_points.forEach((point) => {
            const mastery = masteryByCode.get(point.id) || masteryByName.get(point.name.trim());
            let status: KnowledgeNodeStatus = 'unstarted';
            if (mastery) status = masteryStatus(mastery.score);
            else if (weakTopics.has(point.name.trim())) status = 'needs-work';
            else if (currentChapter && (
              currentChapter === chapter.name || currentChapter === section.name || currentChapter === point.name
            )) status = 'current';
            nodes.push({
              id: point.id,
              label: point.name,
              score: mastery?.score ?? null,
              status,
              detail: mastery
                ? masteryDetail(mastery)
                : `${volume.name} · ${chapter.name} · ${section.name}`,
              group: `${volume.name} · ${chapter.name}`,
              summary: point.summary,
              objectives: point.objectives,
              prerequisites: point.prerequisites,
              commonMistakes: point.common_mistakes,
              keywords: point.keywords,
              competencyTags: point.competency_tags,
              knowledgeItems: point.knowledge_items,
            });
          });
        });
      });
    });
    return nodes;
  }

  const seen = new Set<string>();
  const nodes: KnowledgeMapNode[] = [];
  if (enrollment?.current_chapter) {
    seen.add(enrollment.current_chapter);
    nodes.push({
      id: `chapter-${enrollment.current_chapter}`,
      label: enrollment.current_chapter,
      score: null,
      status: 'current',
      detail: '当前学习章节',
    });
  }
  subjectMasteries
    .sort((a, b) => a.score - b.score)
    .forEach((mastery) => {
      const normalized = mastery.knowledge_point_name.trim();
      if (!normalized || seen.has(normalized)) return;
      seen.add(normalized);
      nodes.push({
        id: mastery.id,
        label: normalized,
        score: mastery.score,
        status: masteryStatus(mastery.score),
        detail: masteryDetail(mastery),
      });
    });
  (enrollment?.weak_topics || []).forEach((topic) => {
    const normalized = topic.trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    nodes.push({
      id: `weak-${normalized}`,
      label: normalized,
      score: null,
      status: 'needs-work',
      detail: '你标记的薄弱点',
    });
  });
  return nodes;
}
