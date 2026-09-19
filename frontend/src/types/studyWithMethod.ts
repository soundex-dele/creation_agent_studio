export type StudySubject =
  | 'chinese' | 'math' | 'english' | 'physics' | 'chemistry'
  | 'biology' | 'politics' | 'history' | 'geography';
export type GradeStage = 'high_1' | 'high_2' | 'high_3';

export interface SubjectEnrollment {
  id: string;
  subject: StudySubject;
  subject_label: string;
  grade_stage: GradeStage;
  grade_stage_label: string;
  curriculum_version: string;
  current_chapter: string;
  weak_topics: string[];
  latest_score: string | null;
  target_score: string | null;
  setup_completed: boolean;
  is_active: boolean;
}

export interface StudyProfile {
  id: string;
  student_name: string;
  display_name: string;
  region: string;
  primary_subject: StudySubject;
  grade_stage: GradeStage;
  daily_minutes: number;
  latest_score: string | null;
  target_score: string | null;
  onboarding_completed: boolean;
  focus_subjects: StudySubject[];
  last_tutor_subject: StudySubject | '';
  enrollment: SubjectEnrollment;
  enrollments: SubjectEnrollment[];
  created_at: string;
  updated_at: string;
}

export interface StudyTask {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  task_type: 'school_sync' | 'weak_point' | 'review' | 'weekly_quiz';
  task_type_label: string;
  title: string;
  scheduled_for: string;
  duration_minutes: number;
  status: 'pending' | 'completed' | 'skipped';
  completed_at: string | null;
  knowledge_point_name: string | null;
  metadata: Record<string, unknown>;
}

export interface StudyAttempt {
  id: string;
  response: string;
  student_thought: string;
  is_correct: boolean | null;
  hint_level_used: number;
  duration_seconds: number;
  created_at: string;
}

export interface StudyProblem {
  id: string;
  conversation_id: number | null;
  source_attachment_id: string | null;
  subject: StudySubject;
  grade_stage: GradeStage;
  source_image_url: string;
  original_text: string;
  confirmed_text: string;
  source: string;
  status: 'needs_confirmation' | 'ready' | 'completed';
  max_hint_level: number;
  analysis: Record<string, unknown>;
  knowledge_point_code: string | null;
  knowledge_point_name: string | null;
  latest_run_id: string | null;
  attempts: StudyAttempt[];
  created_at: string;
  updated_at: string;
}

export interface StudyMistake {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  problem: StudyProblem;
  cause: string;
  cause_label: string;
  knowledge_summary: string;
  notes: string;
  correct_answer: string;
  similar_problem_types: string[];
  mastery: number;
  next_review_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StudyMistakeCheckIn {
  id: string;
  subject: StudySubject;
  checked_on: string;
  created_at: string;
}

export interface StudyMistakeCheckInSummary {
  subject: StudySubject;
  checked_in_today: boolean;
  streak: number;
  check_ins: StudyMistakeCheckIn[];
}

export interface ManualStudyMistakeInput {
  problemText: string;
  image?: Blob;
  knowledgeSummary: string;
  cause: string;
  notes: string;
  correctAnswer: string;
  similarProblemTypes: string[];
}

export interface StudyReview {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  mistake: StudyMistake;
  interval_step: number;
  next_review_at: string;
  last_result: string;
  completed_reviews: number;
  updated_at: string;
}

export interface StudyMastery {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  knowledge_point_code: string;
  knowledge_point_name: string;
  score: number;
  attempts_count: number;
  correct_count: number;
  updated_at: string;
}

export interface WeeklyReport {
  id: string;
  student_name: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  week_start: string;
  metrics: {
    task_total?: number;
    task_completed?: number;
    completion_rate?: number;
    planned_minutes?: number;
    attempt_total?: number;
    correct_rate?: number;
    mistake_count?: number;
    due_review_count?: number;
  };
  summary: string;
  next_week_advice: string;
}

export interface GuardianLink {
  id: string;
  guardian_name: string;
  guardian_email: string;
  is_active: boolean;
  created_at: string;
}

export interface WeeklyQuizQuestion {
  id: string;
  prompt: string;
  knowledge_point: string;
  source_problem_id: string;
  validation_status: string;
}

export interface WeeklyQuiz {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  week_start: string;
  questions: WeeklyQuizQuestion[];
  question_count: number;
  results: Record<string, unknown>;
  status: 'ready' | 'completed';
  score: number | null;
  completed_at: string | null;
}

export type StudyDashboard =
  | { mode: 'onboarding'; enabled_subjects: StudySubject[] }
  | { mode: 'guardian'; reports: WeeklyReport[] }
  | {
      mode: 'student';
      profile: StudyProfile;
      enrollments: SubjectEnrollment[];
      today: string;
      tasks: StudyTask[];
      due_reviews: StudyReview[];
      due_review_count: number;
      mistake_count: number;
      masteries: StudyMastery[];
      latest_report: WeeklyReport | null;
      stats_by_subject: Array<{
        subject: StudySubject;
        subject_label: string;
        task_count: number;
        completed_count: number;
        mistake_count: number;
      }>;
    };

export interface StudyProfileInput {
  display_name?: string;
  region?: string;
  daily_minutes: number;
  subjects: StudySubject[];
  focus_subjects: StudySubject[];
  grade_stage: GradeStage;
  curriculum_version?: string;
  current_chapter?: string;
  weak_topics?: string[];
}

export interface StudyCatalogSubject {
  value: StudySubject;
  label: string;
  icon: string;
  color: string;
  chapters: string[];
  curriculum_versions: string[];
  curriculum_version_options: Array<{ id: string; label: string }>;
}

export interface CurriculumKnowledgeItem {
  id: string;
  type: 'concept' | 'definition' | 'formula' | 'theorem' | 'property' | 'method' | 'model' | 'event' | 'process' | 'impact' | 'comparison' | 'institution' | 'person' | 'cause' | 'evidence';
  name: string;
  content: string;
  formulas?: string[];
  conditions?: string[];
  conclusion?: string;
  common_mistakes?: string[];
  review_status: 'candidate' | 'self_checked' | 'teacher_reviewed';
}

export interface CurriculumKnowledgePoint {
  id: string;
  name: string;
  summary: string;
  objectives: string[];
  prerequisites: string[];
  common_mistakes: string[];
  keywords: string[];
  competency_tags: string[];
  knowledge_items: CurriculumKnowledgeItem[];
}

export interface CurriculumSection {
  id: string;
  name: string;
  knowledge_points: CurriculumKnowledgePoint[];
}

export interface CurriculumChapter {
  id: string;
  name: string;
  sections: CurriculumSection[];
}

export interface CurriculumVolume {
  id: string;
  name: string;
  chapters: CurriculumChapter[];
}

export interface CurriculumTree {
  id: string;
  subject: StudySubject;
  label: string;
  publisher: string;
  volumes: CurriculumVolume[];
}

export interface AnswerCardQuestion {
  id: string;
  stem: string;
  options: Array<{ id: 'A' | 'B' | 'C' | 'D'; text: string }>;
  difficulty: 'basic' | 'medium' | 'advanced';
  tags: string[];
}

export interface AnswerCardResult {
  question_id: string;
  selected_option_id: string;
  correct_option_id: string;
  is_correct: boolean;
  explanation: string;
  mistake_id?: string;
}

export interface AnswerCard {
  id: string;
  subject: StudySubject;
  grade_stage: GradeStage;
  curriculum_version: string;
  knowledge_point_code: string;
  knowledge_point_name: string;
  questions: AnswerCardQuestion[];
  results: { answers?: AnswerCardResult[]; correct?: number; total?: number };
  status: 'ready' | 'completed';
  score: number | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StudyCatalog {
  grades: Array<{ value: GradeStage; label: string }>;
  subjects: StudyCatalogSubject[];
}

export interface StudyTutor {
  id: number;
  name: string;
  description: string;
  subject: StudySubject;
  subject_label: string;
}

export interface StudyTutorSession {
  id: string;
  title: string;
  subject: StudySubject;
  updated_at: string;
  agent?: { id: number; name: string; description: string };
}

export interface StudyTutorSessionCreateResult {
  conversation: StudyTutorSession | null;
  subject: StudySubject;
  problem?: StudyProblem | null;
  run_id?: string | null;
}

export interface StudyReportSummary {
  overall_metrics: WeeklyReport['metrics'];
  subjects: WeeklyReport[];
}

export interface TutorHint {
  subject: StudySubject;
  strategy_version: number;
  knowledge_point: string;
  hint_level: number;
  hint: string;
  solution_revealed: boolean;
  tutor_run_id: string | null;
  run_error?: string;
}

export interface TutorRun {
  id: string;
  status: string;
  output_summary: { result?: string };
  error_message?: string;
}
