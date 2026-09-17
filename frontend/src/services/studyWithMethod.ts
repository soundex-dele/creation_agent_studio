import { api } from './api';
import { tenantApiRoot } from './tenantContext';
import type {
  GuardianLink,
  ManualStudyMistakeInput,
  StudyDashboard,
  StudyMistake,
  StudyProblem,
  StudyProfile,
  StudyProfileInput,
  StudyReview,
  StudyTask,
  TutorHint,
  TutorRun,
  WeeklyReport,
  WeeklyQuiz,
} from '@/types/studyWithMethod';


function studyRoot(organizationId: string, applicationId: string) {
  return `${tenantApiRoot(organizationId)}/applications/${applicationId}/study`;
}

export const loadStudyDashboard = (organizationId: string, applicationId: string) =>
  api.get<StudyDashboard>(`${studyRoot(organizationId, applicationId)}/dashboard`);

export const saveStudyProfile = (
  organizationId: string,
  applicationId: string,
  input: StudyProfileInput,
) => api.put<StudyProfile>(`${studyRoot(organizationId, applicationId)}/profile`, input);

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
) => {
  const data = new FormData();
  data.set('subject', 'math');
  data.set('grade_stage', 'high_2');
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

export const listStudyMistakes = (organizationId: string, applicationId: string) =>
  api.get<StudyMistake[]>(`${studyRoot(organizationId, applicationId)}/mistakes`);

export const importStudyMistake = (
  organizationId: string,
  applicationId: string,
  input: ManualStudyMistakeInput,
) => {
  const data = new FormData();
  data.set('subject', 'math');
  data.set('grade_stage', 'high_2');
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
  },
) => api.patch<StudyMistake>(
  `${studyRoot(organizationId, applicationId)}/mistakes/${mistakeId}`,
  input,
);

export const listStudyReviews = (organizationId: string, applicationId: string) =>
  api.get<StudyReview[]>(`${studyRoot(organizationId, applicationId)}/reviews`);

export const completeStudyReview = (
  organizationId: string,
  applicationId: string,
  reviewId: string,
  isCorrect: boolean,
) => api.post<StudyReview>(
  `${studyRoot(organizationId, applicationId)}/reviews/${reviewId}/complete`,
  { is_correct: isCorrect },
);

export const listWeeklyReports = (organizationId: string, applicationId: string) =>
  api.get<WeeklyReport[]>(`${studyRoot(organizationId, applicationId)}/reports`);

export const generateWeeklyReport = (organizationId: string, applicationId: string) =>
  api.post<WeeklyReport>(`${studyRoot(organizationId, applicationId)}/reports`, { subject: 'math' });

export const listWeeklyQuizzes = (organizationId: string, applicationId: string) =>
  api.get<WeeklyQuiz[]>(`${studyRoot(organizationId, applicationId)}/quizzes`);

export const generateWeeklyQuiz = (organizationId: string, applicationId: string) =>
  api.post<WeeklyQuiz>(`${studyRoot(organizationId, applicationId)}/quizzes`, { subject: 'math' });

export const submitWeeklyQuiz = (
  organizationId: string,
  applicationId: string,
  quizId: string,
  answers: Array<{ question_id: string; is_correct: boolean }>,
) => api.post<WeeklyQuiz>(
  `${studyRoot(organizationId, applicationId)}/quizzes/${quizId}/submit`,
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
