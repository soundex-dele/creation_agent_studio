from rest_framework import serializers
from .models import ResearchProject


class ProjectSerializer(serializers.ModelSerializer):
    objective = serializers.CharField(max_length=8000, allow_blank=True, required=False)

    class Meta:
        ref_name = "ResearchProject"
        model = ResearchProject
        fields = ["id", "title", "objective", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SourceInput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchSourceInput"

    title = serializers.CharField(max_length=200, required=False)
    file = serializers.FileField(required=False)
    text = serializers.CharField(required=False)
    origin_type = serializers.ChoiceField(choices=["drive", "document"], required=False)
    origin_id = serializers.UUIDField(required=False)
    application_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, data):
        if sum(key in data for key in ["file", "text", "origin_type"]) != 1:
            raise serializers.ValidationError("请选择文件、文章或已有资料中的一种。")
        if data.get("origin_type") and not all(data.get(key) for key in ["origin_id", "application_id"]):
            raise serializers.ValidationError("请选择来源应用和资料。")
        return data


class GenerateInput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchGenerateInput"

    source_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    kind = serializers.ChoiceField(choices=["report", "comparison", "writing_pack"])
    instruction = serializers.CharField(max_length=8000, allow_blank=True, required=False, default="")


class ExportInput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchExportInput"

    target = serializers.ChoiceField(choices=["document", "drive"])
    application_id = serializers.IntegerField(min_value=1)
    parent = serializers.UUIDField(required=False, allow_null=True, default=None)


class SourceOutput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchSource"
    id = serializers.UUIDField()
    title = serializers.CharField()
    filename = serializers.CharField()
    byte_size = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["pending", "indexing", "ready", "failed"])
    error = serializers.CharField(allow_blank=True)
    error_code = serializers.CharField(allow_blank=True)
    indexing_run_id = serializers.CharField()
    origin = serializers.JSONField()
    metadata = serializers.JSONField()
    removed = serializers.BooleanField()
    reused = serializers.BooleanField(required=False)


class ResultOutput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchResult"
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["report", "comparison", "writing_pack"])
    instruction = serializers.CharField()
    objective = serializers.CharField()
    source_ids = serializers.ListField(child=serializers.UUIDField())
    created_at = serializers.DateTimeField()
    run_id = serializers.UUIDField(allow_null=True)
    status = serializers.CharField()
    error = serializers.CharField()
    progress = serializers.JSONField(allow_null=True)
    output = serializers.JSONField(allow_null=True, required=False,
        help_text="schema_version=1; title, sections[{heading, items[{type,text,evidence_ids,source_id?,source_title?}]}], citations and coverage")


class CitationOutput(serializers.Serializer):
    class Meta:
        ref_name = "ResearchCitation"
    id = serializers.CharField()
    number = serializers.IntegerField()
    source_id = serializers.UUIDField()
    document_id = serializers.IntegerField()
    revision = serializers.IntegerField()
    chunk_id = serializers.IntegerField()
    title = serializers.CharField()
    quote = serializers.CharField()
    note = serializers.CharField()
    page_number = serializers.IntegerField(allow_null=True)
    paragraph_number = serializers.IntegerField(allow_null=True)
    position = serializers.IntegerField()
    section_path = serializers.ListField(child=serializers.CharField())
    context = serializers.CharField()
    origin = serializers.JSONField()
    filename = serializers.CharField()


class ProjectPage(serializers.Serializer):
    class Meta:
        ref_name = "ResearchProjectPage"
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ProjectSerializer(many=True)


class ResultPage(serializers.Serializer):
    class Meta:
        ref_name = "ResearchResultPage"
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ResultOutput(many=True)
