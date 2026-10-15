from django.contrib import admin

from .models import (
    AnswerCard,
    CurriculumNode,
    DiagnosticAssessment,
    DiagnosticResult,
    GuardianLink,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyGoal,
    StudyTask,
    SubjectEnrollment,
    WeeklyReport,
    WeeklyQuiz,
)


admin.site.register(
    (StudyProfile, SubjectEnrollment, CurriculumNode, StudyTask, Problem,
     MistakeRecord, ReviewSchedule, GuardianLink, WeeklyReport, WeeklyQuiz,
     AnswerCard, StudyGoal, DiagnosticAssessment, DiagnosticResult)
)
