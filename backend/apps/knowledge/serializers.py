from rest_framework import serializers
from modules.execution.api.serializers import RunSerializer

from .models import KnowledgeBase, KnowledgeDocument


class KnowledgeBaseSummarySerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = KnowledgeBase
        fields = [
            "id", "name", "description", "is_active", "document_count",
            "created_at", "updated_at",
        ]


class KnowledgeBaseDetailSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = KnowledgeBase
        fields = [
            "id", "name", "description", "embedding_provider", "embedding_model",
            "answer_provider", "answer_model", "chunk_size", "chunk_overlap",
            "is_active", "document_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "document_count", "created_at", "updated_at"]

    def validate(self, attrs):
        size = attrs.get("chunk_size", getattr(self.instance, "chunk_size", 600))
        overlap = attrs.get("chunk_overlap", getattr(self.instance, "chunk_overlap", 80))
        if not 100 <= size <= 1500:
            raise serializers.ValidationError({"chunk_size": "Use a value between 100 and 1500."})
        if overlap < 0 or overlap >= size / 2:
            raise serializers.ValidationError({"chunk_overlap": "Overlap must be less than half the chunk size."})
        return attrs


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    indexing_run_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = KnowledgeDocument
        fields = [
            "id", "knowledge_base_id", "title", "source_type", "original_filename",
            "mime_type", "byte_size", "checksum", "status", "active_revision",
            "indexing_run_id", "metadata", "error_code", "error", "indexed_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class KnowledgeSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=4000)
    knowledge_base_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list,
        max_length=50,
    )
    limit = serializers.IntegerField(min_value=1, max_value=50, default=10)


class KnowledgeAnswerRunInputSerializer(KnowledgeSearchRequestSerializer):
    pass


class KnowledgeDocumentCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300, required=False)
    file = serializers.FileField(required=False)
    text = serializers.CharField(required=False)


class KnowledgeIndexAcceptedSerializer(serializers.Serializer):
    document = KnowledgeDocumentSerializer()
    run = RunSerializer()
    run_url = serializers.CharField()
    stream_url = serializers.CharField()


class KnowledgeSearchResultSerializer(serializers.Serializer):
    chunk_id = serializers.IntegerField()
    document_id = serializers.IntegerField()
    knowledge_base_id = serializers.IntegerField()
    knowledge_base_name = serializers.CharField()
    title = serializers.CharField()
    snippet = serializers.CharField()
    score = serializers.FloatField()
    page_number = serializers.IntegerField(allow_null=True)
    section_path = serializers.ListField(child=serializers.CharField())
    citation = serializers.CharField()


class KnowledgeSearchResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    retrieval_mode = serializers.ChoiceField(choices=["hybrid", "vector", "lexical"])
    results = KnowledgeSearchResultSerializer(many=True)


class KnowledgeCitationSerializer(KnowledgeSearchResultSerializer):
    label = serializers.CharField()


class KnowledgeAnswerOutputSerializer(serializers.Serializer):
    answer = serializers.CharField()
    citations = KnowledgeCitationSerializer(many=True)
    retrieval_mode = serializers.ChoiceField(choices=["hybrid", "vector", "lexical"])
    model = serializers.CharField(allow_blank=True)
    usage = serializers.JSONField()


class KnowledgeAnswerAcceptedSerializer(serializers.Serializer):
    run = RunSerializer()
    run_url = serializers.CharField()
    stream_url = serializers.CharField()
    output = KnowledgeAnswerOutputSerializer(allow_null=True)
