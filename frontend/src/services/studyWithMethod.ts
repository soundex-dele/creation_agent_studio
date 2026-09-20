import { api } from './api';
import { tenantApiRoot } from './tenantContext';
import type {
  GuardianLink,
  ManualStudyMistakeInput,
  StudyDashboard,
  StudyCatalog,
  StudyMistake,
  StudyMistakeCheckInSummary,
  StudyProblem,
  StudyProfile,
  StudyProfileInput,
  StudyReview,
  StudyTask,
  StudySubject,
  GradeStage,
  SubjectEnrollment,
  StudyTutor,
  StudyTutorSession,
  StudyTutorSessionCreateResult,
  StudyReportSummary,
  TutorHint,
  TutorRun,
  WeeklyReport,
  WeeklyQuiz,
  AnswerCard,
  CurriculumTree,
  DiagnosticAssessment,
  ReviewRating,
  StudyGoal,
} from '@/types/studyWithMethod';


function studyRoot(organizationId: string, applicationId: string) {
  return `${tenantApiRoot(organizationId)}/applications/${applicationId}/study`;
}

export const loadStudyDashboard = (organizationId: string, applicationId: string) =>
  api.get<StudyDashboard>(`${studyRoot(organizationId, applicationId)}/dashboard`);

export const loadStudyCatalog = (organizationId: string, applicationId: string) =>
  api.get<StudyCatalog>(`${studyRoot(organizationId, applicationId)}/catalog`);

export const saveStudyProfile = (
  organizationId: string,
  applicationId: string,
  input: StudyProfileInput,
) => api.put<StudyProfile>(`${studyRoot(organizationId, applicationId)}/profile`, input);

export const updateStudyEnrollment = (
  organizationId: string,
  applicationId: string,
  subject: StudySubject,
  input: Partial<Pick<SubjectEnrollment,
    'curriculum_version' | 'current_chapter' | 'weak_topics' | 'latest_score' | 'target_score'>>,
) => api.patch<SubjectEnrollment>(
  `${studyRoot(organizationId, applicationId)}/enrollments/${subject}`,
  input,
);

export const listStudyTutors = (organizationId: string, applicationId: string) =>
  api.get<StudyTutor[]>(`${studyRoot(organizationId, applicationId)}/tutors`);

export const listTutorSessions = (organizationId: string, applicationId: string) =>
  api.get<StudyTutorSession[]>(`${studyRoot(organizationId, applicationId)}/tutor-sessions`);

export const createTutorSession = (
  organizationId: string,
  applicationId: string,
  input: { mode: 'photo' | 'chat'; subject: StudySubject; agentId: number; image?: Blob; problemText?: string },
) => {
  const data = new FormData();
  data.set('mode', input.mode);
  data.set('subject', input.subject);
  data.set('agent_id', String(input.agentId));
  if (input.image) data.set('source_image', input.image, 'study-question.jpg');
  if (input.problemText?.trim()) data.set('problem_text', input.problemText.trim());
  return api.post<StudyTutorSessionCreateResult>(
    `${studyRoot(organizationId, applicationId)}/tutor-sessions`,
    data,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
};

export const updateStudyTask = (
  organizationId: string,
  applicationId: string,
  taskId: string,
  status: 'completed' | 'skipped',
) => api.patch<StudyTask>(
  `${studyRoot(organizationId, applicationId)}/tasks/${taskId}`,
  { status },
);

export const listStudyProblems = (organizationId: string, applicationId: string) =>
  api.get<StudyProblem[]>(`${studyRoot(organizationId, applicationId)}/problems`);

export const createStudyProblem = (
  organizationId: string,
  applicationId: string,
  input: { problemText: string; image?: Blob; source: 'camera' | 'upload' | 'manual' },
  subject: StudySubject = 'math',
  gradeStage: GradeStage = 'high_2',
) => {
  const data = new FormData();
  data.set('subject', subject);
  data.set('grade_stage', gradeStage);
  data.set('problem_text', input.problemText);
  data.set('source', input.source);
  if (input.image) data.set('source_image', input.image, 'math-problem.jpg');
  return api.post<StudyProblem>(
    `${studyRoot(organizationId, applicationId)}/problems`,
    data,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
};

export const confirmStudyProblem = (
  organizationId: string,
  applicationId: string,
  problemId: string,
  confirmedText: string,
) => api.patch<StudyProblem>(
  `${studyRoot(organizationId, applicationId)}/problems/${problemId}`,
  { confirmed_text: confirmedText },
);

export const requestTutorHint = (
  organizationId: string,
  applicationId: string,
  problemId: string,
  studentThought: string,
  hintLevel?: number,
) => api.post<TutorHint>(
  `${studyRoot(organizationId, applicationId)}/problems/${problemId}/hint`,
  { student_thought: studentThought, ...(hintLevel ? { hint_level: hintLevel } : {}) },
);

export const submitStudyAttempt = (
  organizationId: string,
  applicationId: string,
  problemId: string,
  input: { response: string; studentThought: string; isCorrect: boolean },
) => api.post(
  `${studyRoot(organizationId, applicationId)}/problems/${problemId}/attempts`,
  {
    response: input.response,
    student_thought: input.studentThought,
    is_correct: input.isCorrect,
    duration_seconds: 0,
  },
);

export const requestVariantProblem = (
  organizationId: string,
  applicationId: string,
  problemId: string,
) => api.post<{ tutor_run_id: string | null; validation_status: string }>(
  `${studyRoot(organizationId, applicationId)}/problems/${problemId}/variant`,
);

export const listStudyMistakes = (
  organizationId: string,
  applicationId: string,
  options?: {
    subject?: StudySubject;
    date?: string;
    month?: string;
    start_date?: string;
    end_date?: string;
    cause?: string;
    archived?: boolean;
    search?: string;
  },
) => api.get<StudyMistake[]>(
  `${studyRoot(organizationId, applicationId)}/mistakes`,
  options,
);

export const getMistakeCheckInSummary = (
  organizationId: string,
  applicationId: string,
  subject: StudySubject,
) => api.get<StudyMistakeCheckInSummary>(
  `${studyRoot(organizationId, applicationId)}/mistake-check-ins`,
  { subject },
);

export const importStudyMistake = (
  organizationId: string,
  applicationId: string,
  input: ManualStudyMistakeInput,
  subject: StudySubject = 'math',
  gradeStage: GradeStage = 'high_2',
) => {
  const data = new FormData();
  data.set('subject', subject);
  data.set('grade_stage', gradeStage);
  data.set('problem_text', input.problemText);
  data.set('knowledge_summary', input.knowledgeSummary);
  data.set('cause', input.cause);
  data.set('notes', input.notes);
  data.set('correct_answer', input.correctAnswer);
  input.similarProblemTypes.forEach((item) => data.append('similar_problem_types', item));
  if (input.image) data.set('source_image', input.image, 'mistake.jpg');
  return api.post<StudyMistake>(
    `${studyRoot(organizationId, applicationId)}/mistakes`,
    data,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
};

export const updateStudyMistake = (
  organizationId: string,
  applicationId: string,
  mistakeId: string,
  input: {
    cause?: string;
    knowledge_summary?: string;
    notes?: string;
    correct_answer?: string;
    similar_problem_types?: string[];
    is_archived?: boolean;
  },
) => api.patch<StudyMistake>(
  `${studyRoot(organizationId, applicationId)}/mistakes/${mistakeId}`,
  input,
);

export const listStudyReviews = (
  organizationId: string,
  applicationId: string,
  options?: { subject?: StudySubject; dueOnly?: boolean },
) => api.get<StudyReview[]>(
  `${studyRoot(organizationId, applicationId)}/reviews`,
  {
    ...(options?.subject ? { subject: options.subject } : {}),
    ...(options?.dueOnly === false ? { due: 0 } : {}),
  },
);

export const completeStudyReview = (
  organizationId: string,
  applicationId: string,
  reviewId: string,
  rating: ReviewRating,
) => api.post<StudyReview>(
  `${studyRoot(organizationId, applicationId)}/reviews/${reviewId}/complete`,
  { rating },
);

export const listStudyGoals = (organizationId: string, applicationId: string) =>
  api.get<StudyGoal[]>(`${studyRoot(organizationId, applicationId)}/goals`);

export const saveStudyGoal = (
  organizationId: string,
  applicationId: string,
  input: Pick<StudyGoal, 'subject' | 'exam_date' | 'weekly_minutes' | 'focus_chapters'>
    & { target_score: number | null },
) => api.put<StudyGoal>(`${studyRoot(organizationId, applicationId)}/goals`, input);

export const listDiagnostics = (organizationId: string, applicationId: string) =>
  api.get<DiagnosticAssessment[]>(`${studyRoot(organizationId, applicationId)}/diagnostics`);

export const createDiagnostic = (
  organizationId: string,
  applicationId: string,
  subjects: StudySubject[],
  skip = false,
) => api.post<DiagnosticAssessment>(
  `${studyRoot(organizationId, applicationId)}/diagnostics`,
  { subjects, skip },
);

export const submitDiagnostic = (
  organizationId: string,
  applicationId: string,
  assessmentId: string,
  answers: Array<{
    question_id: string;
    selected_option_id?: string;
    self_rating?: number;
  }>,
) => api.post<DiagnosticAssessment>(
  `${studyRoot(organizationId, applicationId)}/diagnostics/${assessmentId}/submit`,
  { answers },
);

export const listWeeklyReports = (organizationId: string, applicationId: string) =>
  api.get<WeeklyReport[]>(`${studyRoot(organizationId, applicationId)}/reports`);

export const generateWeeklyReport = (organizationId: string, applicationId: string) =>
  api.post<StudyReportSummary>(`${studyRoot(organizationId, applicationId)}/reports`, {});

export const getWeeklyReportSummary = (organizationId: string, applicationId: string) =>
  api.get<StudyReportSummary>(`${studyRoot(organizationId, applicationId)}/reports`, { aggregate: 1 });

export const listWeeklyQuizzes = (
  organizationId: string, applicationId: string, subject?: StudySubject,
) => api.get<WeeklyQuiz[]>(
  `${studyRoot(organizationId, applicationId)}/quizzes`,
  subject ? { subject } : undefined,
);

export const generateWeeklyQuiz = (
  organizationId: string, applicationId: string, subject: StudySubject = 'math',
) => api.post<WeeklyQuiz>(`${studyRoot(organizationId, applicationId)}/quizzes`, { subject });

export const submitWeeklyQuiz = (
  organizationId: string,
  applicationId: string,
  quizId: string,
  answers: Array<{
    question_id: string;
    selected_option_id?: string;
    rating?: ReviewRating;
  }>,
) => api.post<WeeklyQuiz>(
  `${studyRoot(organizationId, applicationId)}/quizzes/${quizId}/submit`,
  { answers },
);

export const loadCurriculumTree = (
  organizationId: string,
  applicationId: string,
  subject: StudySubject,
  curriculumVersion: string,
) => api.get<CurriculumTree>(
  `${studyRoot(organizationId, applicationId)}/curriculum`,
  { subject, curriculum_version: curriculumVersion },
);

export const listAnswerCards = (
  organizationId: string,
  applicationId: string,
  subject?: StudySubject,
) => api.get<AnswerCard[]>(
  `${studyRoot(organizationId, applicationId)}/answer-cards`,
  subject ? { subject } : undefined,
);

export const createAnswerCard = (
  organizationId: string,
  applicationId: string,
  input: { subject: StudySubject; curriculum_version: string; knowledge_point_code: string },
) => api.post<AnswerCard>(`${studyRoot(organizationId, applicationId)}/answer-cards`, input);

export const submitAnswerCard = (
  organizationId: string,
  applicationId: string,
  cardId: string,
  answers: Array<{ question_id: string; selected_option_id: string }>,
) => api.post<AnswerCard>(
  `${studyRoot(organizationId, applicationId)}/answer-cards/${cardId}/submit`,
  { answers },
);

export const listGuardianLinks = (organizationId: string, applicationId: string) =>
  api.get<GuardianLink[]>(`${studyRoot(organizationId, applicationId)}/guardians`);

export const addGuardianLink = (
  organizationId: string,
  applicationId: string,
  identifier: string,
) => api.post<GuardianLink>(
  `${studyRoot(organizationId, applicationId)}/guardians`,
  { identifier },
);

export const removeGuardianLink = (
  organizationId: string,
  applicationId: string,
  linkId: string,
) => api.delete<void>(`${studyRoot(organizationId, applicationId)}/guardians/${linkId}`);

export const getTutorRun = (organizationId: string, runId: string) =>
  api.get<TutorRun>(`${tenantApiRoot(organizationId)}/runs/${runId}`);

export const exportStudyData = (organizationId: string, applicationId: string) =>
  api.get<Record<string, unknown>>(`${studyRoot(organizationId, applicationId)}/export`);

export const deleteStudyData = (organizationId: string, applicationId: string) =>
  api.delete<void>(`${studyRoot(organizationId, applicationId)}/data?confirmation=${
    encodeURIComponent('删除我的学习数据')
  }`);
