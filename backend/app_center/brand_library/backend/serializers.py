from rest_framework import serializers
from .models import BrandProfile, BrandProduct, BrandExample


SECTION_FIELDS = {
    "positioning": {"platform": "平台", "introduction": "账号介绍", "audience": "目标受众", "topics": "内容领域", "value": "价值主张", "goals": "创作目标"},
    "voice": {"keywords": "风格关键词", "principles": "表达原则", "preferred": "推荐用语", "forbidden": "禁用表达", "positive": "正例", "negative": "反例"},
    "visual": {"primary_color": "主色及用途", "secondary_color": "辅色及用途", "heading_font": "标题字体", "body_font": "正文字体", "style": "画面风格", "layout": "排版要求", "logo": "Logo 使用说明"},
}
MODULE_LABELS = {"positioning": "账号定位", "products": "产品事实", "voice": "品牌语气", "examples": "优秀范文", "visual": "视觉规范"}


class SectionField(serializers.DictField):
    def __init__(self, section, **kwargs):
        self.allowed = SECTION_FIELDS[section]
        super().__init__(child=serializers.CharField(max_length=4000, allow_blank=True), **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if set(value) - set(self.allowed):
            raise serializers.ValidationError("包含未知资料字段。")
        return value


class ProfileSerializer(serializers.ModelSerializer):
    positioning = SectionField("positioning", required=False)
    voice = SectionField("voice", required=False)
    visual = SectionField("visual", required=False)

    class Meta:
        model = BrandProfile
        fields = ["id", "application_id", "name", "positioning", "voice", "visual", "created_at", "updated_at"]
        read_only_fields = ["id", "application_id", "created_at", "updated_at"]


class ProductSerializer(serializers.ModelSerializer):
    facts = serializers.ListField(child=serializers.CharField(max_length=2000), max_length=100, required=False)

    class Meta:
        model = BrandProduct
        fields = ["id", "name", "description", "facts", "source", "restrictions", "prohibited_claims", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {key: {"max_length": 4000} for key in ("description", "source", "restrictions", "prohibited_claims")}


class ExampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandExample
        fields = ["id", "name", "platform", "body", "source_url", "highlights", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"body": {"max_length": 30000}, "highlights": {"max_length": 4000}}


class BrandReferenceSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    modules = serializers.ListField(child=serializers.ChoiceField(choices=list(MODULE_LABELS)), allow_empty=False, max_length=5)
    product_ids = serializers.ListField(child=serializers.UUIDField(), default=list, max_length=100)
    example_ids = serializers.ListField(child=serializers.UUIDField(), default=list, max_length=100)

    def validate(self, attrs):
        for module, key in (("products", "product_ids"), ("examples", "example_ids")):
            if attrs[key] and module not in attrs["modules"]:
                raise serializers.ValidationError(f"选择条目时必须启用{MODULE_LABELS[module]}模块。")
        return attrs
