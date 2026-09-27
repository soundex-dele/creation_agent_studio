import json
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from .models import KitchenState, KitchenRecord, KitchenOperation
from .serializers import State, StateUpdate, StatePatch, RecordEdit


def initial_state():
    recipes = json.loads((Path(__file__).parent.parent / "assets" / "recipes.json").read_text(encoding="utf-8"))
    return dict(schemaVersion=2, preferences=default_preferences(), shoppingScopes={}, recipes=recipes, inventory=[], records=[], selectedRecipeIds=[],
                checkedShoppingItems=[], servings=2, cooking=None, weeklyMenu=[])


def default_preferences():
    return dict(servings=2, avoid=[], dislike=[], spicy=1,
                equipment=["炒锅", "汤锅", "蒸锅", "电饭煲", "平底锅"], maxMinutes=60)


def normalize(data):
    data = {"preferences": {**default_preferences(), "servings": data.get("servings", 2)},
            "shoppingScopes": {}, **data, "schemaVersion": 2, "records": []}
    menu = data.get("weeklyMenu", [])
    if menu and isinstance(menu[0], list):
        today = timezone.localdate()
        data["weeklyMenu"] = [dict(date=(today + timedelta(days=i)).isoformat(), lunch=[], dinner=day)
                              for i, day in enumerate(menu)]
    data["weeklyMenu"] = [{"breakfast": [], "settings": {
        meal: dict(servings=data.get("servings", 2), locked=False, skipped=False, count=1 if meal == "breakfast" else 2)
        for meal in ("breakfast", "lunch", "dinner")}, **day} for day in data.get("weeklyMenu", [])]
    if data.get("cooking"):
        data["cooking"] = {"pausedTimers": {}, "timerMeta": {}, "prepared": [],
            "servings": data.get("servings", 2), "recipeSnapshots": [r for r in data["recipes"] if r["id"] in data["cooking"]["recipeIds"]], **data["cooking"]}
    return data


class KitchenAccess(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def state(self):
        application = get_object_or_404(accessible_resources(
            Application.objects.for_organization(self.kwargs["organization_id"]).filter(
                is_active=True, slug="kitchen-assistant", kind=Application.Kind.CUSTOM,
            ), self.request.user, operation="run",
        ), pk=self.kwargs["application_id"])
        state, _ = KitchenState.objects.for_organization(self.kwargs["organization_id"]).get_or_create(
            organization_id=self.kwargs["organization_id"], application=application,
            owner=self.request.user, defaults={"data": initial_state()},
        )
        return state

    def records(self, state):
        return KitchenRecord.objects.for_organization(state.organization_id).filter(state=state).order_by("-finished_at", "-id")

    def snapshot(self, state):
        records = self.records(state)
        return {"revision": state.revision, "recordCount": records.count(),
                "data": {**normalize(state.data), "records": [{**r.data, "revision": r.revision} for r in records[:20]]}}

    def conflict(self):
        return Response({"detail": "数据已在其他页面更新。请加载最新数据后重新应用本次操作。"}, status=409)


class KitchenStateView(KitchenAccess):
    def get(self, request, **kwargs):
        return Response(self.snapshot(self.state()))

    def patch(self, request, **kwargs):
        serializer = StatePatch(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.data
        return self.write(request, payload)

    def put(self, request, **kwargs):
        # Compatibility for existing clients. Historical rows are never deleted
        # merely because a legacy client sent its bounded recent-record window.
        serializer = StateUpdate(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.data
        data = dict(payload["data"])
        records = data.pop("records")
        return self.write(request, dict(schemaVersion=request.data.get("data", {}).get("schemaVersion"), revision=payload["revision"], changes=data, appendRecords=records))

    def write(self, request, payload):
        state = self.state()
        with transaction.atomic():
            state = KitchenState.objects.for_organization(state.organization_id).select_for_update().get(pk=state.pk)
            operation_id = payload.get("operationId")
            operations = KitchenOperation.objects.for_organization(state.organization_id).filter(state=state)
            if operation_id and operations.filter(operation_id=operation_id).exists():
                return Response(self.snapshot(state))
            if payload.get("schemaVersion") != 2 and set(payload["changes"]) & {"recipes", "inventory", "weeklyMenu", "cooking", "preferences", "shoppingScopes"}:
                return Response({"detail": "厨房数据已升级，请刷新页面后重试。", "code": "schema_upgrade_required"}, status=409)
            if state.revision != payload["revision"]:
                return self.conflict()
            if payload.get("aiTaskId"):
                from .ai import validate_output
                from types import SimpleNamespace
                from copy import deepcopy
                task = get_object_or_404(state.ai_tasks, pk=payload["aiTaskId"], kind="menu", status="succeeded")
                if set(payload["changes"]) - {"weeklyMenu", "shoppingScopes"} or payload.get("appendRecords"):
                    raise serializers.ValidationError("应用 AI 菜单不可同时更改其他厨房数据。")
                current = normalize(state.data)
                current_days = {d["date"]: d for d in current["weeklyMenu"]}
                baseline = [current_days.get(d["date"], d) for d in task.snapshot["weeklyMenu"]]
                try:
                    verified = validate_output(SimpleNamespace(kind="menu", snapshot={**current, "weeklyMenu": baseline}), deepcopy(task.result))
                except ValueError as exc:
                    raise serializers.ValidationError(f"厨房条件已变化，请重新生成菜单：{exc}") from None
                payload["changes"] = {"weeklyMenu": verified["menu"], "shoppingScopes": {key: {**value, "checked": []} if key.startswith("range:") else value for key, value in current["shoppingScopes"].items()}}
            data = {**normalize(state.data), **payload["changes"], "records": []}
            validator = State(data=data)
            validator.is_valid(raise_exception=True)
            updated = KitchenState.objects.for_organization(state.organization_id).filter(pk=state.pk, revision=state.revision).update(
                data={**normalize(state.data), **{key: validator.data[key] for key in payload["changes"]}},
                revision=state.revision + 1, updated_at=timezone.now(),
            )
            if not updated:
                return self.conflict()
            for record in payload.get("appendRecords", []):
                KitchenRecord.objects.for_organization(state.organization_id).get_or_create(
                    state=state, record_id=record["id"],
                    defaults={"organization_id": state.organization_id, "data": record, "finished_at": record["finishedAt"], "recipe_names": "\n".join(record["recipeNames"])},
                )
            if operation_id:
                operations.create(organization_id=state.organization_id, state=state, operation_id=operation_id)
            state.refresh_from_db()
            return Response(self.snapshot(state))


class HistoryPagination(PageNumberPagination):
    page_size = 20


class KitchenHistoryView(KitchenAccess):
    def get(self, request, **kwargs):
        state = self.state()
        paginator = HistoryPagination()
        records = self.records(state)
        search = request.query_params.get("search", "").strip()[:200]
        if search:
            records = records.filter(recipe_names__icontains=search)
        for param, lookup in (("start", "finished_at__date__gte"), ("end", "finished_at__date__lte")):
            if request.query_params.get(param):
                date = serializers.DateField().run_validation(request.query_params[param])
                records = records.filter(**{lookup: date})
        page = paginator.paginate_queryset(records, request, view=self)
        return paginator.get_paginated_response([{**row.data, "revision": row.revision} for row in page])


class KitchenRecordView(KitchenAccess):
    def patch(self, request, **kwargs):
        state = self.state()
        values = RecordEdit(data=request.data)
        values.is_valid(raise_exception=True)
        row = get_object_or_404(self.records(state), record_id=kwargs["record_id"])
        data = {**row.data, **{key: value for key, value in values.validated_data.items() if key != "revision"}}
        updated = self.records(state).filter(pk=row.pk, revision=values.validated_data["revision"]).update(data=data, revision=row.revision + 1)
        if not updated:
            return self.conflict()
        return Response({**data, "revision": row.revision + 1})

    def delete(self, request, **kwargs):
        state = self.state()
        values = serializers.IntegerField(min_value=0)
        revision = values.run_validation(request.query_params.get("revision"))
        row = get_object_or_404(self.records(state), record_id=kwargs["record_id"])
        deleted, _ = self.records(state).filter(pk=row.pk, revision=revision).delete()
        if not deleted:
            return self.conflict()
        return Response(status=204)


class KitchenCatalogView(KitchenAccess):
    def get(self, request, **kwargs):
        self.state()
        return Response(json.loads((Path(__file__).parent.parent / "assets" / "catalog.json").read_text(encoding="utf-8")))
