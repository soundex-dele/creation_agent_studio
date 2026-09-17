from django.contrib import admin

from .models import (
    CurriculumNode,
    GuardianLink,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyTask,
    SubjectEnrollment,
    WeeklyReport,
    WeeklyQuiz,
)


admin.site.register(
    (StudyProfile, SubjectEnrollment, CurriculumNode, StudyTask, Problem,
     MistakeRecord, ReviewSchedule, GuardianLink, WeeklyReport, WeeklyQuiz)
)
