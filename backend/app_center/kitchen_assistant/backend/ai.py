"""Private AI drafts; generating never mutates kitchen state."""
import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers as s
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition, CommandNotAllowed
from .models import KitchenAITask, KitchenState
from .serializers import Recipe, State
from .views import KitchenAccess, normalize

ACTIVE = {"queued", "running", "waiting_input", "waiting_children", "cancelling"}
MEALS = ("breakfast", "lunch", "dinner")


class TaskInput(s.Serializer):
    kind = s.ChoiceField(choices=["recipe", "menu", "question"])
    instruction = s.CharField(max_length=20000)
    revision = s.IntegerField(min_value=0)
    requestKey = s.CharField(max_length=160)
    recipeId = s.CharField(max_length=200, required=False)
    parentId = s.UUIDField(required=False)
    startDate = s.DateField(required=False)


def task_data(task):
    status, error = task.status, task.error
    if task.run and status in ACTIVE:
        status = task.run.status
        if status == "failed":
            error = error or "任务执行失败，请检查模型配置后手动重试。"
    return dict(id=str(task.pk), kind=task.kind, instruction=task.instruction, revision=task.revision,
                status=status, error=error, result=task.result,
                recipeId=task.snapshot.get("recipeId"), parentId=task.snapshot.get("parentId"))


class AITasksView(KitchenAccess):
    def get(self, request, **kwargs):
        return Response([task_data(t) for t in self.state().ai_tasks.select_related("run")[:50]])

    @transaction.atomic
    def post(self, request, **kwargs):
        state = self.state()
        state = KitchenState.objects.for_organization(state.organization_id).select_for_update().get(pk=state.pk)
        serializer = TaskInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.data)
        key = values.pop("requestKey")
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        existing = state.ai_tasks.filter(request_key=key).select_related("run").first()
        if existing:
            if existing.request_hash != digest:
                return Response({"detail": "同一请求键不能用于不同任务。"}, status=409)
            return Response(task_data(existing))
        if state.revision != values["revision"]:
            return self.conflict()
        data = normalize(deepcopy(state.data))
        if values.get("recipeId"):
            recipes = data.get("cooking", {}).get("recipeSnapshots", []) if data.get("cooking") else []
            recipe = next((r for r in recipes + data["recipes"] if r["id"] == values["recipeId"]), None)
            if not recipe:
                raise s.ValidationError("所选菜谱不存在。")
            data["activeRecipe"] = recipe
        if values["kind"] == "menu":
            start = s.DateField().run_validation(values.get("startDate") or timezone.localdate().isoformat())
            existing_days = {d["date"]: d for d in data["weeklyMenu"]}
            data["weeklyMenu"] = [existing_days.get((start + timedelta(days=i)).isoformat()) or {
                "date": (start + timedelta(days=i)).isoformat(), "breakfast": [], "lunch": [], "dinner": [],
                "settings": {meal: dict(servings=data["preferences"]["servings"], locked=False, skipped=False, count=1 if meal == "breakfast" else 2) for meal in MEALS},
            } for i in range(7)]
        if values.get("parentId"):
            parent = get_object_or_404(state.ai_tasks, pk=values["parentId"], kind="question", status="succeeded")
            if values["kind"] != "question":
                raise s.ValidationError("仅烹饪问答支持追问。")
            if not data.get("activeRecipe") and parent.snapshot.get("recipeId"):
                data["recipeId"] = parent.snapshot["recipeId"]
                data["activeRecipe"] = next((r for r in data["recipes"] if r["id"] == data["recipeId"]), parent.snapshot.get("activeRecipe"))
            data["conversation"] = (parent.snapshot.get("conversation", []) + [dict(question=parent.instruction, answer=parent.result.get("answer", ""))])[-10:]
        data.update({k: values[k] for k in ("recipeId", "parentId") if k in values})
        task = KitchenAITask.objects.for_organization(state.organization_id).create(
            organization_id=state.organization_id, state=state, kind=values["kind"], instruction=values["instruction"],
            request_key=key, request_hash=digest, revision=state.revision, snapshot=data)
        try:
            run, _ = start_application_run(organization_id=state.organization_id, application_id=state.application_id,
                actor=request.user, input_data={"task_id": str(task.pk)}, priority=0, idempotency_key=f"kitchen:{task.pk}")
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            transaction.set_rollback(True)
            return Response({"detail": str(exc)}, status=409)
        task.run = run
        task.save(update_fields=["run"])
        return Response(task_data(task), status=202)


class AITaskView(KitchenAccess):
    def get(self, request, task_id, **kwargs):
        return Response(task_data(get_object_or_404(self.state().ai_tasks.select_related("run"), pk=task_id)))


class AITaskCancelView(KitchenAccess):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        task = get_object_or_404(self.state().ai_tasks.select_for_update().select_related("run"), pk=task_id)
        if task_data(task)["status"] in ACTIVE:
            task.cancel_requested = True
            task.status = "cancelled"
            task.save(update_fields=["cancel_requested", "status"])
            if task.run and task.run.status in ACTIVE:
                try:
                    submit_run_command(run_id=task.run_id, organization_id=task.organization_id, actor=request.user,
                        command_type="cancel", idempotency_key=f"kitchen-cancel:{task.pk}")
                except CommandNotAllowed:
                    pass  # Finishing concurrently cannot apply any kitchen mutations.
        return Response(task_data(task))


def recipe_conflicts(recipe, prefs, meal):
    marker = dict(breakfast="早", lunch="中", dinner="晚")[meal]
    return (any(term in i["name"] for term in prefs["avoid"] for i in recipe["ingredients"])
            or recipe["durationMinutes"] > prefs["maxMinutes"]
            or recipe.get("spicy", 0) > prefs["spicy"]
            or bool(set(recipe.get("equipment", [])) - set(prefs["equipment"]))
            or not any(marker in m or m == meal for m in recipe["mealTimes"]))


def validate_output(task, value):
    if not isinstance(value, dict):
        raise ValueError("模型返回格式无效。")
    if task.kind == "question":
        answer = value.get("answer")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 20000:
            raise ValueError("回答为空或过长。")
        return {"answer": answer}
    if task.kind == "menu":
        menu = value.get("menu")
        if not isinstance(menu, list) or len(menu) != 7:
            raise ValueError("菜单必须覆盖七天。")
        original = {d["date"]: d for d in task.snapshot["weeklyMenu"]}
        if {d.get("date") for d in menu if isinstance(d, dict)} != set(original):
            raise ValueError("菜单日期与请求不一致。")
        for day in menu:
            for meal in MEALS:
                old = original[day["date"]]; settings = old.get("settings", {}).get(meal, {})
                if settings.get("locked") or settings.get("skipped"):
                    day[meal] = old.get(meal, [])
                    day.setdefault("settings", {})[meal] = settings
                else:
                    proposed = day.setdefault("settings", {}).get(meal) or {}
                    day["settings"][meal] = {"servings": proposed.get("servings", settings.get("servings", task.snapshot["servings"])),
                        "count": proposed.get("count", settings.get("count", 1 if meal == "breakfast" else 2)), "locked": False, "skipped": False}
        validator = State(data={**task.snapshot, "weeklyMenu": menu})
        if not validator.is_valid():
            raise ValueError("菜单结构或菜谱引用无效。")
        recipes = {r["id"]: r for r in task.snapshot["recipes"]}
        for day in validator.data["weeklyMenu"]:
            for meal in MEALS:
                settings = original[day["date"]].get("settings", {}).get(meal, {})
                if settings.get("locked") or settings.get("skipped"):
                    continue
                if any(recipe_conflicts(recipes[r], task.snapshot["preferences"], meal) for r in day[meal]):
                    raise ValueError("生成菜单不符合饮食偏好、厨具或餐次限制。")
        return {"menu": validator.data["weeklyMenu"]}
    recipe = value.get("recipe")
    if not isinstance(recipe, dict):
        raise ValueError("缺少菜谱内容。")
    recipe = deepcopy(recipe)
    ingredients, steps = recipe.get("ingredients"), recipe.get("steps")
    if not isinstance(ingredients, list) or not ingredients or len(ingredients) > 100 or not isinstance(steps, list) or not steps or len(steps) > 100:
        raise ValueError("菜谱必须包含食材和步骤，且各不超过 100 项。")
    missing = []
    recipe.update(id=str(uuid4()), source="AI 整理文字 · 待用户核对", createdAt=timezone.now().isoformat(), updatedAt=timezone.now().isoformat())
    recipe.setdefault("name", "待命名菜谱")
    for key, default in (("category", "其他"), ("intro", ""), ("difficulty", "简单"), ("mealTimes", ["中", "晚"]), ("tips", [])):
        recipe.setdefault(key, default)
    # Null remains null in the draft; temporary values only validate the rest of the structure.
    for key in ("servings", "durationMinutes"):
        if recipe.get(key) is None:
            recipe[key] = None; missing.append(key)
    old_ids = {}
    for index, item in enumerate(ingredients):
        if not isinstance(item, dict):
            raise ValueError("食材格式无效。")
        original_id = str(item.get("id", index))
        if original_id in old_ids:
            raise ValueError("原文整理结果的食材 ID 重复。")
        new_id = str(uuid4()); old_ids[original_id] = new_id; item["id"] = new_id
        item.setdefault("type", "main")
        if item.get("amount") is None:
            item["amount"] = None; missing.append(f"ingredients.{index}.amount")
        if not item.get("unit"):
            item["unit"] = ""; missing.append(f"ingredients.{index}.unit")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("步骤格式无效。")
        step["id"] = str(uuid4())
        refs = step.get("ingredientIds", [])
        if not isinstance(refs, list) or any(str(ref) not in old_ids for ref in refs):
            raise ValueError("步骤引用了不存在的食材。")
        step["ingredientIds"] = [old_ids[str(ref)] for ref in refs]
        step["mediaUrls"] = []
        step.setdefault("phase", "cook"); step.setdefault("heatLevel", "按原文确认")
        if step.get("durationMinutes") is None:
            step["durationMinutes"] = None; missing.append(f"steps.{index}.durationMinutes")
    check = deepcopy(recipe)
    for key in ("servings", "durationMinutes"):
        if check[key] is None: check[key] = 1
    for item in check["ingredients"]:
        if item["amount"] is None: item["amount"] = 1
        if not item["unit"]: item["unit"] = "待补充"
    for step in check["steps"]:
        if step["durationMinutes"] is None: step["durationMinutes"] = 0
    validator = Recipe(data=check)
    if not validator.is_valid():
        raise ValueError("菜谱结构无效，请调整原文后重试。")
    normalized = dict(validator.data)
    for key in missing:
        parts = key.split(".")
        if len(parts) == 1:
            normalized[key] = None
        else:
            normalized[parts[0]][int(parts[1])][parts[2]] = "" if parts[2] == "unit" else None
    return {"recipe": normalized, "missing": missing}
