from rest_framework import serializers as s
from .catalog import SCENES


class SessionInput(s.Serializer):
    title = s.CharField(max_length=200, required=False)
    mode = s.ChoiceField(choices=["generate", "optimize"], default="generate")
    topic = s.CharField(max_length=20000, allow_blank=True, default="")
    original = s.CharField(max_length=30000, allow_blank=True, default="")
    objective = s.CharField(max_length=5000, allow_blank=True, default="")
    scene = s.ChoiceField(choices=["auto", *SCENES], default="auto")
    language = s.ChoiceField(choices=["zh", "en"], default="zh")
    favorite = s.BooleanField(required=False)
    revision = s.IntegerField(min_value=0, required=False)
    answers = s.DictField(required=False)


class TaskInput(s.Serializer):
    kind = s.ChoiceField(choices=["analyze", "generate", "optimize", "check"])
    revision = s.IntegerField(min_value=0)
    request_key = s.CharField(max_length=160)
    instruction = s.CharField(max_length=5000, allow_blank=True, default="")
    version_id = s.UUIDField(required=False)


class HealthItem(s.Serializer):
    problem = s.CharField(max_length=2000)
    suggestion = s.CharField(max_length=3000)


class Option(s.Serializer):
    value = s.CharField(max_length=80)
    label = s.CharField(max_length=300)


class Question(s.Serializer):
    id = s.RegexField(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    label = s.CharField(max_length=1000)
    help = s.CharField(max_length=1000, allow_blank=True, default="")
    type = s.ChoiceField(choices=["text", "single_choice", "multi_choice"])
    options = Option(many=True, default=list)
    recommended = s.CharField(max_length=2000)

    def validate(self, data):
        options = data["options"]
        if len(options) > 8 or len({o["value"] for o in options}) != len(options):
            raise s.ValidationError("问题选项重复或过多。")
        if data["type"] != "text" and len(options) < 2:
            raise s.ValidationError("选择题至少需要两个选项。")
        return data


class AnalysisOutput(s.Serializer):
    scene = s.ChoiceField(choices=list(SCENES))
    summary = s.CharField(max_length=4000)
    questions = Question(many=True)
    issues = HealthItem(many=True, default=list)


class Constraint(s.Serializer):
    text = s.CharField(max_length=2000)
    standard_excerpt = s.CharField(max_length=3000)
    concise_excerpt = s.CharField(max_length=3000)


class ResultOutput(s.Serializer):
    standard = s.CharField(max_length=40000)
    concise = s.CharField(max_length=20000)
    assumptions = s.ListField(child=s.CharField(max_length=2000), max_length=30)
    health = HealthItem(many=True)
    changes = s.ListField(child=s.CharField(max_length=2000), max_length=30)
    constraints = Constraint(many=True)

    def validate(self, data):
        if len(data["health"]) > 30 or len(data["constraints"]) > 40:
            raise s.ValidationError("体检或约束条目过多。")
        for item in data["constraints"]:
            if item["standard_excerpt"] not in data["standard"] or item["concise_excerpt"] not in data["concise"]:
                raise s.ValidationError("关键约束未同时保留在两个版本中。")
        return data


class CheckOutput(s.Serializer):
    health = HealthItem(many=True)

    def validate_health(self, value):
        if len(value) > 30:
            raise s.ValidationError("体检条目过多。")
        return value


class VersionInput(s.Serializer):
    revision = s.IntegerField(min_value=0)
    version_id = s.UUIDField()
    standard = s.CharField(max_length=40000)
    concise = s.CharField(max_length=20000)


def validate_answers(questions, answers):
    allowed = {q["id"]: q for q in questions}
    if set(answers) - allowed.keys():
        raise s.ValidationError("回答包含已失效的问题，请刷新后重试。")
    for value in answers.values():
        if value is None:
            continue
        if isinstance(value, str) and len(value) <= 5000:
            continue
        if isinstance(value, list) and len(value) <= 10 and all(isinstance(v, str) and len(v) <= 1000 for v in value):
            continue
        raise s.ValidationError("回答格式无效或内容过长。")
    return answers


def validate_output(task, value):
    validator_type = {"analyze": AnalysisOutput, "check": CheckOutput}.get(task.kind, ResultOutput)
    validator = validator_type(data=value)
    if not validator.is_valid():
        raise ValueError("模型返回的结构或内容无效，请重试。")
    data = dict(validator.validated_data)
    if task.kind == "analyze":
        questions = data["questions"]
        rounds = task.snapshot["rounds"]
        if rounds >= 2 or len(questions) > (5 if rounds == 0 else 3):
            raise ValueError("模型返回的问题超过本轮上限。")
        if rounds == 0 and 0 < len(questions) < 3:
            raise ValueError("首轮应返回 3～5 个问题，信息充分时无需提问。")
        if len(data["issues"]) > 30 or len({q["id"] for q in questions}) != len(questions):
            raise ValueError("分析条目过多或问题标识重复。")
        old = {q["id"] for q in task.snapshot["questions"]}
        if old.intersection(q["id"] for q in questions):
            raise ValueError("补问不能重复已有问题。")
    return data
