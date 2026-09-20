from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from apps.applications.models import Application
from core.resource_access import accessible_resources
from apps.applications.serializers import ApplicationRuntimeSerializer
from apps.enterprise.models import Membership
from .input_schema import (
    validate_workflow_input_schema,
    workflow_input_properties,
)
from .models import Workflow, WorkflowStep


def _can_delete_workflow(workflow, request):
    if not request or not request.user.is_authenticated:
        return False
    membership = getattr(request, 'organization_membership', None)
    if membership is None:
        return False
    if membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN):
        return True
    return (
        membership.role == Membership.Role.DEVELOPER
        and workflow.owner_id == request.user.id
    )


class WorkflowStepSerializer(serializers.ModelSerializer):
    application = ApplicationRuntimeSerializer(read_only=True)
    application_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = WorkflowStep
        fields = [
            'id', 'key', 'name', 'order', 'config', 'input_mapping', 'depends_on',
            'condition', 'max_attempts', 'application_id', 'application',
        ]


class WorkflowListSerializer(serializers.ModelSerializer):
    step_count = serializers.IntegerField(read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'execution_mode',
                  'is_public', 'step_count', 'can_delete', 'created_at', 'updated_at']

    def get_can_delete(self, obj):
        return _can_delete_workflow(obj, self.context.get('request'))


class WorkflowDetailSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'execution_mode', 'input_schema',
                  'output_mapping', 'is_public', 'steps', 'can_delete', 'created_at',
                  'updated_at']

    def get_can_delete(self, obj):
        return _can_delete_workflow(obj, self.context.get('request'))


class WorkflowWriteSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, required=False)

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'execution_mode', 'input_schema',
                  'output_mapping', 'is_public', 'steps']
        read_only_fields = ['id']

    def validate_input_schema(self, value):
        try:
            validate_workflow_input_schema(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate_steps(self, value):
        orders = [item['order'] for item in value]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError('步骤顺序不能重复。')
        keys = [item['key'] for item in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError('步骤 key 不能重复。')
        known_keys = set(keys)
        graph = {}
        for item in value:
            if not 1 <= item.get('max_attempts', 1) <= 10:
                raise serializers.ValidationError(
                    f"步骤 {item['key']} 的 max_attempts 必须在 1 到 10 之间。"
                )
            dependencies = item.get('depends_on') or []
            if not isinstance(dependencies, list) or not all(
                isinstance(key, str) for key in dependencies
            ):
                raise serializers.ValidationError('depends_on 必须是步骤 key 数组。')
            dependency_set = set(dependencies)
            if len(dependencies) != len(dependency_set):
                raise serializers.ValidationError(f"步骤 {item['key']} 的依赖不能重复。")
            if item['key'] in dependency_set:
                raise serializers.ValidationError(f"步骤 {item['key']} 不能依赖自身。")
            missing = dependency_set - known_keys
            if missing:
                raise serializers.ValidationError(
                    f"步骤 {item['key']} 引用了不存在的依赖：{', '.join(sorted(missing))}。"
                )
            graph[item['key']] = dependency_set
            if not isinstance(item.get('input_mapping') or {}, dict):
                raise serializers.ValidationError(
                    f"步骤 {item['key']} 的 input_mapping 必须是对象。"
                )
            self._validate_condition(
                item['key'], item.get('condition') or {}, known_keys, dependency_set
            )

        remaining = {key: set(dependencies) for key, dependencies in graph.items()}
        while remaining:
            ready = {key for key, dependencies in remaining.items() if not dependencies}
            if not ready:
                raise serializers.ValidationError('工作流依赖不能形成环。')
            remaining = {
                key: dependencies - ready
                for key, dependencies in remaining.items()
                if key not in ready
            }
        request = self.context['request']
        organization = getattr(request, 'organization', None)
        requested = {item['application_id'] for item in value}
        allowed = set(accessible_resources(
            Application.objects.filter(
                Q(organization=organization) | Q(organization__isnull=True),
                id__in=requested,
                is_active=True,
            ),
            request.user,
            operation="run",
        ).values_list('id', flat=True))
        if requested != allowed:
            raise serializers.ValidationError('包含不可用或未发布的应用版本。')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        input_schema = attrs.get(
            'input_schema', getattr(self.instance, 'input_schema', {})
        ) or {}
        input_properties = workflow_input_properties(input_schema)
        mapping = attrs.get(
            'output_mapping', getattr(self.instance, 'output_mapping', {})
        ) or {}
        if not isinstance(mapping, dict):
            raise serializers.ValidationError({
                'output_mapping': 'output_mapping 必须是对象。'
            })
        steps = attrs.get('steps')
        known_keys = {
            item['key'] for item in steps
        } if steps is not None else {
            step.key for step in self.instance.steps.all()
        } if self.instance else set()
        for name, binding in mapping.items():
            if not isinstance(name, str) or not name.strip():
                raise serializers.ValidationError({
                    'output_mapping': '最终输出字段名不能为空。'
                })
            source = binding if isinstance(binding, str) else (
                binding.get('from') if isinstance(binding, dict) else None
            )
            if not isinstance(source, str) or not source.startswith('steps.'):
                raise serializers.ValidationError({
                    'output_mapping': f'{name} 必须引用步骤输出。'
                })
            step_key = source.removeprefix('steps.').partition('.output')[0]
            if '.output' not in source or step_key not in known_keys:
                raise serializers.ValidationError({
                    'output_mapping': f'{name} 引用了不存在的步骤。'
                })
        if input_properties:
            steps_to_validate = steps
            if steps_to_validate is None and self.instance:
                steps_to_validate = [
                    {
                        'key': step.key,
                        'config': step.config,
                        'input_mapping': step.input_mapping,
                        'condition': step.condition,
                    }
                    for step in self.instance.steps.all()
                ]
            for step in steps_to_validate or []:
                self._validate_input_references(step, input_properties)
        return attrs

    @staticmethod
    def _validate_input_references(step, input_properties):
        step_key = step['key']
        condition = step.get('condition') or {}
        if condition.get('source') == 'input':
            input_key = str(condition.get('path') or '').partition('.')[0]
            if input_key not in input_properties:
                raise serializers.ValidationError({
                    'input_schema': (
                        f'步骤 {step_key} 的条件引用了不存在的输入字段 {input_key}。'
                    )
                })
        automation = (step.get('config') or {}).get('automation') or {}
        answers = automation.get('answers') or {}
        if not isinstance(answers, dict):
            answers = {}
        for binding in answers.values():
            if not isinstance(binding, dict):
                continue
            source = str(binding.get('from') or '')
            if not source.startswith('workflow.input.'):
                continue
            input_key = source.removeprefix('workflow.input.').partition('.')[0]
            if input_key not in input_properties:
                raise serializers.ValidationError({
                    'input_schema': (
                        f'步骤 {step_key} 引用了不存在的输入字段 {input_key}。'
                    )
                })
        for binding in (step.get('input_mapping') or {}).values():
            if not isinstance(binding, dict):
                continue
            source = str(binding.get('from') or '')
            if not source.startswith('workflow.input.'):
                continue
            input_key = source.removeprefix('workflow.input.').partition('.')[0]
            if input_key not in input_properties:
                raise serializers.ValidationError({
                    'input_schema': (
                        f'步骤 {step_key} 引用了不存在的输入字段 {input_key}。'
                    )
                })

    @staticmethod
    def _validate_condition(step_key, condition, known_keys, dependencies):
        if not isinstance(condition, dict):
            raise serializers.ValidationError(f'步骤 {step_key} 的 condition 必须是对象。')
        if not condition:
            return
        source = condition.get('source')
        if source not in {'input', 'dependency'}:
            raise serializers.ValidationError(
                f'步骤 {step_key} 的 condition.source 必须是 input 或 dependency。'
            )
        if source == 'dependency' and condition.get('step') not in known_keys:
            raise serializers.ValidationError(
                f'步骤 {step_key} 的 condition.step 必须引用已有步骤。'
            )
        if source == 'dependency' and condition.get('step') not in dependencies:
            raise serializers.ValidationError(
                f'步骤 {step_key} 的 condition.step 必须同时列入 depends_on。'
            )
        operator = condition.get('operator', 'truthy')
        if operator not in {
            'truthy', 'equals', 'not_equals', 'exists', 'in',
        }:
            raise serializers.ValidationError(f'步骤 {step_key} 使用了不支持的条件操作符。')
        if not isinstance(condition.get('path', ''), str):
            raise serializers.ValidationError(f'步骤 {step_key} 的 condition.path 必须是字符串。')
        if operator == 'in' and not isinstance(condition.get('value'), list):
            raise serializers.ValidationError(
                f'步骤 {step_key} 使用 in 条件时 value 必须是数组。'
            )

    @transaction.atomic
    def create(self, validated_data):
        steps = validated_data.pop('steps', [])
        workflow = Workflow.objects.create(**validated_data)
        self._replace_steps(workflow, steps)
        return workflow

    @transaction.atomic
    def update(self, instance, validated_data):
        steps = validated_data.pop('steps', None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if steps is not None:
            self._replace_steps(instance, steps)
        return instance

    @staticmethod
    def _replace_steps(workflow, steps):
        workflow.steps.all().delete()
        WorkflowStep.objects.bulk_create([
            WorkflowStep(
                workflow=workflow,
                application_id=item['application_id'],
                key=item['key'],
                name=item.get('name', ''),
                config=item.get('config', {}),
                input_mapping=item.get('input_mapping', {}),
                depends_on=item.get('depends_on', []),
                condition=item.get('condition', {}),
                max_attempts=item.get('max_attempts', 1),
                order=item['order'],
            )
            for item in steps
        ])
