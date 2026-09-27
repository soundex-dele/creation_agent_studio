import math
from rest_framework import serializers as s


class Amount(s.FloatField):
    def __init__(self, **kwargs):
        super().__init__(min_value=0, max_value=1000000, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            self.fail("invalid")
        return value


def text(max_length=200, **kwargs):
    return s.CharField(max_length=max_length, **kwargs)


def ids(**kwargs):
    return s.ListField(child=text(), max_length=500, **kwargs)


class Ingredient(s.Serializer):
    id = text()
    name = text()
    amount = Amount()
    unit = text(30)
    type = s.ChoiceField(choices=["main", "side", "seasoning"])


class Step(s.Serializer):
    id = text()
    title = text()
    description = text(10000)
    phase = s.ChoiceField(choices=["prep", "cook", "finish"])
    durationMinutes = s.IntegerField(min_value=0, max_value=1440)
    heatLevel = text(100)
    ingredientIds = ids()
    mediaUrls = s.ListField(child=s.URLField(), max_length=20, default=list)


class Recipe(s.Serializer):
    id = text()
    name = text()
    category = text(50)
    intro = text(10000, allow_blank=True)
    difficulty = text(50)
    servings = s.IntegerField(min_value=1, max_value=8)
    durationMinutes = s.IntegerField(min_value=1, max_value=1440)
    mealTimes = s.ListField(child=text(30), max_length=10)
    source = text(500, allow_blank=True)
    createdAt = s.DateTimeField()
    updatedAt = s.DateTimeField()
    favorite = s.BooleanField(default=False)
    tags = s.ListField(child=text(50), max_length=30, default=list)
    equipment = s.ListField(child=text(50), max_length=20, default=list)
    spicy = s.IntegerField(min_value=0, max_value=3, default=0)
    catalogId = text(required=False)
    ingredients = Ingredient(many=True, allow_empty=False)
    steps = Step(many=True, allow_empty=False)
    tips = s.ListField(child=text(2000), max_length=50)

    def validate(self, data):
        for field in ("ingredients", "steps"):
            values = data[field]
            if len(values) > 100 or len({v["id"] for v in values}) != len(values):
                raise s.ValidationError({field: "最多 100 项，且 ID 不可重复。"})
        known = {v["id"] for v in data["ingredients"]}
        if any(set(step["ingredientIds"]) - known for step in data["steps"]):
            raise s.ValidationError("步骤引用了不存在的食材。")
        return data


class Inventory(s.Serializer):
    id = text()
    name = text()
    amount = Amount()
    unit = text(30)
    category = text(50)
    expireDate = s.DateField(allow_null=True)
    location = s.ChoiceField(choices=["冷藏", "冷冻", "常温"], default="常温")


class Record(s.Serializer):
    id = text()
    recipeNames = ids(allow_empty=False)
    startedAt = s.DateTimeField()
    finishedAt = s.DateTimeField()
    servings = s.IntegerField(min_value=1, max_value=8)
    rating = s.IntegerField(min_value=0, max_value=5)
    tasteNotes = text(10000, allow_blank=True)
    healthSummary = text(10000, allow_blank=True)
    recipeSnapshots = Recipe(many=True, required=False)

    def validate(self, data):
        snapshots = data.get("recipeSnapshots")
        if snapshots is not None and (len(snapshots) > 500 or len({r["id"] for r in snapshots}) != len(snapshots)
                                      or [r["name"] for r in snapshots] != data["recipeNames"]):
            raise s.ValidationError("历史快照必须与菜名一致且 ID 不可重复。")
        if data["finishedAt"] < data["startedAt"]:
            raise s.ValidationError("结束时间不可早于开始时间。")
        return data


class TimerMeta(s.Serializer):
    recipeId = text()
    stepId = text()


class Cooking(s.Serializer):
    startedAt = s.DateTimeField()
    recipeIds = ids(allow_empty=False)
    currentId = text()
    steps = s.DictField(child=s.IntegerField(min_value=0, max_value=99))
    completedIds = ids()
    timers = s.DictField(child=s.IntegerField(min_value=0, max_value=8640000000000000))
    recipeSnapshots = Recipe(many=True, required=False)
    servings = s.IntegerField(min_value=1, max_value=8, required=False)
    prepared = ids(default=list)
    timerMeta = s.DictField(child=TimerMeta(), default=dict)
    pausedTimers = s.DictField(child=s.IntegerField(min_value=0, max_value=86400), default=dict)


class MealSettings(s.Serializer):
    servings = s.IntegerField(min_value=1, max_value=8)
    locked = s.BooleanField(default=False)
    skipped = s.BooleanField(default=False)
    count = s.IntegerField(min_value=1, max_value=8)


class Preferences(s.Serializer):
    servings = s.IntegerField(min_value=1, max_value=8, default=2)
    avoid = s.ListField(child=text(100), max_length=100, default=list)
    dislike = s.ListField(child=text(100), max_length=100, default=list)
    spicy = s.IntegerField(min_value=0, max_value=3, default=1)
    equipment = s.ListField(child=text(50), max_length=20, default=lambda: ["炒锅", "汤锅", "蒸锅", "电饭煲", "平底锅"])
    maxMinutes = s.IntegerField(min_value=1, max_value=1440, default=60)


class ManualPurchase(s.Serializer):
    id = text()
    name = text()
    amount = Amount()
    unit = text(30)
    type = s.ChoiceField(choices=["main", "side", "seasoning"])


class ShoppingScope(s.Serializer):
    checked = s.ListField(child=text(500), max_length=5000)
    manual = ManualPurchase(many=True)

    def validate_manual(self, value):
        if len(value) > 500 or len({x["id"] for x in value}) != len(value):
            raise s.ValidationError("手动采购项最多 500 个，ID 不可重复。")
        return value


class MenuDay(s.Serializer):
    date = s.DateField()
    lunch = ids()
    dinner = ids()
    breakfast = ids(default=list)
    settings = s.DictField(child=MealSettings(), default=dict)

    def validate(self, data):
        if set(data["settings"]) - {"breakfast", "lunch", "dinner"}:
            raise s.ValidationError("无效餐次。")
        for meal in ("breakfast", "lunch", "dinner"):
            if len(data[meal]) != len(set(data[meal])):
                raise s.ValidationError("同一餐的菜谱不可重复。")
        return data


class State(s.Serializer):
    schemaVersion = s.IntegerField(min_value=2, max_value=2, default=2)
    preferences = Preferences(required=False)
    shoppingScopes = s.DictField(child=ShoppingScope(), default=dict)
    recipes = Recipe(many=True)
    inventory = Inventory(many=True)
    records = Record(many=True)
    selectedRecipeIds = ids()
    checkedShoppingItems = s.ListField(child=text(500), max_length=5000)
    servings = s.IntegerField(min_value=1, max_value=8)
    cooking = Cooking(allow_null=True)
    weeklyMenu = MenuDay(many=True)

    def validate(self, data):
        for field in ("recipes", "inventory"):
            values = data[field]
            if len(values) > 500 or len({v["id"] for v in values}) != len(values):
                raise s.ValidationError({field: "最多 500 项，且 ID 不可重复。"})
        if len(data["shoppingScopes"]) > 100:
            raise s.ValidationError("采购范围最多保留 100 个，请清理旧清单。")
        recipes = {r["id"]: r for r in data["recipes"]}
        selected = data["selectedRecipeIds"]
        if len(set(selected)) != len(selected) or set(selected) - recipes.keys():
            raise s.ValidationError("待制作清单中的菜谱无效。")
        if len(data["weeklyMenu"]) > 7 or len({day["date"] for day in data["weeklyMenu"]}) != len(data["weeklyMenu"]):
            raise s.ValidationError("周菜单最多 7 天，日期不可重复。")
        if any(set(day["breakfast"] + day["lunch"] + day["dinner"]) - recipes.keys() for day in data["weeklyMenu"]):
            raise s.ValidationError("周菜单中的菜谱无效。")
        cooking = data["cooking"]
        if cooking:
            active = set(cooking["recipeIds"])
            if active != set(selected) or len(active) != len(cooking["recipeIds"]):
                raise s.ValidationError("制作中的菜谱必须与清单一致。")
            if cooking["currentId"] not in active or set(cooking["completedIds"]) - active:
                raise s.ValidationError("制作进度无效。")
            snapshots = {r["id"]: r for r in cooking.get("recipeSnapshots", [])} or recipes
            if cooking.get("recipeSnapshots") and (set(snapshots) != active or len(cooking["recipeSnapshots"]) != len(active)):
                raise s.ValidationError("制作快照必须覆盖全部菜品。")
            prep_keys = {f"{rid}:{step['id']}" for rid in active for step in snapshots[rid]["steps"] if step["phase"] == "prep"}
            if set(cooking["prepared"]) - prep_keys:
                raise s.ValidationError("备菜勾选项无效。")
            timer_ids = set(cooking["pausedTimers"]) | set(cooking["timers"])
            if len(timer_ids) > 500 or set(cooking["timerMeta"]) - timer_ids:
                raise s.ValidationError("计时器数量或元数据无效。")
            for key in timer_ids:
                meta = cooking["timerMeta"].get(key)
                if meta:
                    if meta["recipeId"] not in active or meta["stepId"] not in {v["id"] for v in snapshots[meta["recipeId"]]["steps"]}:
                        raise s.ValidationError("计时器必须引用本餐菜谱步骤。")
                elif key not in active:
                    raise s.ValidationError("计时器缺少步骤信息。")
            if set(cooking["pausedTimers"]) & set(cooking["timers"]):
                raise s.ValidationError("暂停中的计时器无效。")
            if set(cooking["steps"]) != active:
                raise s.ValidationError("制作步骤或计时器无效。")
            if any(index >= len(snapshots[key]["steps"]) for key, index in cooking["steps"].items()):
                raise s.ValidationError("制作步骤超出范围。")
        return data


class StateUpdate(s.Serializer):
    revision = s.IntegerField(min_value=0)
    data = State()


class StatePatch(s.Serializer):
    aiTaskId = s.UUIDField(required=False)
    schemaVersion = s.IntegerField(min_value=2, max_value=2, required=False)
    revision = s.IntegerField(min_value=0)
    operationId = s.UUIDField()
    changes = s.DictField()
    appendRecords = Record(many=True, default=list)

    def validate_changes(self, value):
        allowed = set(State().fields) - {"records"}
        if set(value) - allowed:
            raise s.ValidationError("包含不支持的状态字段。")
        return value

    def validate_appendRecords(self, value):
        if len(value) > 1:
            raise s.ValidationError("一次只能完成一顿饭。")
        return value


class RecordEdit(s.Serializer):
    revision = s.IntegerField(min_value=0)
    rating = s.IntegerField(min_value=0, max_value=5, required=False)
    tasteNotes = text(10000, allow_blank=True, required=False)
