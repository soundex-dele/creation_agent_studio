from django.db import migrations, models


SUBJECTS = [
    ("chinese", "语文"), ("math", "数学"), ("english", "英语"),
    ("physics", "物理"), ("chemistry", "化学"), ("biology", "生物"),
    ("politics", "思想政治"), ("history", "历史"), ("geography", "地理"),
]
GRADES = [("high_1", "高一"), ("high_2", "高二"), ("high_3", "高三")]
CAUSES = [
    ("concept", "概念不清"), ("formula", "公式遗忘"), ("memory", "记忆不牢"),
    ("reading", "审题错误"), ("calculation", "计算错误"), ("method", "方法选择"),
    ("expression", "表达不规范"), ("experiment", "实验分析"), ("careless", "粗心"),
]


def migrate_profile_data(apps, schema_editor):
    Profile = apps.get_model("study_with_method", "StudyProfile")
    Enrollment = apps.get_model("study_with_method", "SubjectEnrollment")
    for profile in Profile.objects.all().iterator():
        subject = profile.primary_subject or "math"
        profile.focus_subjects = [subject]
        profile.last_tutor_subject = subject
        profile.save(update_fields=("focus_subjects", "last_tutor_subject"))
        enrollment = Enrollment.objects.filter(
            profile_id=profile.pk,
            subject=subject,
            grade_stage=profile.grade_stage,
        ).first()
        if enrollment:
            enrollment.latest_score = profile.latest_score
            enrollment.target_score = profile.target_score
            enrollment.save(update_fields=("latest_score", "target_score"))


class Migration(migrations.Migration):
    dependencies = [("study_with_method", "0007_problem_conversation")]

    operations = [
        migrations.AddField(
            model_name="studyprofile", name="focus_subjects",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="studyprofile", name="last_tutor_subject",
            field=models.CharField(blank=True, choices=SUBJECTS, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="subjectenrollment", name="latest_score",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="subjectenrollment", name="target_score",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        migrations.AlterField(
            model_name="subjectenrollment", name="curriculum_version",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AlterField(
            model_name="subjectenrollment", name="current_chapter",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.RunPython(migrate_profile_data, migrations.RunPython.noop),
        migrations.AlterField(model_name="studyprofile", name="primary_subject", field=models.CharField(choices=SUBJECTS, db_index=True, default="math", max_length=32)),
        migrations.AlterField(model_name="studyprofile", name="grade_stage", field=models.CharField(choices=GRADES, db_index=True, default="high_2", max_length=32)),
        migrations.AlterField(model_name="subjectenrollment", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="subjectenrollment", name="grade_stage", field=models.CharField(choices=GRADES, db_index=True, max_length=32)),
        migrations.AlterField(model_name="curriculumnode", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="curriculumnode", name="grade_stage", field=models.CharField(choices=GRADES, db_index=True, max_length=32)),
        migrations.AlterField(model_name="curriculumnode", name="code", field=models.CharField(max_length=180)),
        migrations.AddConstraint(
            model_name="curriculumnode",
            constraint=models.UniqueConstraint(fields=("subject", "grade_stage", "curriculum_version", "code"), name="unique_study_curriculum_node"),
        ),
        migrations.AlterField(model_name="studytask", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="studytask", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="problem", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="problem", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="attempt", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="attempt", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="mistakerecord", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="mistakerecord", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="mistakerecord", name="cause", field=models.CharField(choices=CAUSES, default="concept", max_length=32)),
        migrations.AlterField(model_name="reviewschedule", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="reviewschedule", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="knowledgemastery", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="knowledgemastery", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="weeklyreport", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="weeklyreport", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
        migrations.AlterField(model_name="weeklyquiz", name="subject", field=models.CharField(choices=SUBJECTS, db_index=True, max_length=32)),
        migrations.AlterField(model_name="weeklyquiz", name="grade_stage", field=models.CharField(choices=GRADES, max_length=32)),
    ]
