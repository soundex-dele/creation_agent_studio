from django.db import transaction
from rest_framework import serializers

from apps.applications.models import Application
from apps.applications.serializers import ApplicationRuntimeSerializer
from .models import Workflow, WorkflowStep


class WorkflowStepSerializer(serializers.ModelSerializer):
    application = ApplicationRuntimeSerializer(read_only=True)
    application_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = WorkflowStep
        fields = ['id', 'name', 'order', 'config', 'application_id',
                  'application']


class WorkflowListSerializer(serializers.ModelSerializer):
    step_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'is_public', 'step_count',
                  'created_at', 'updated_at']


class WorkflowDetailSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, read_only=True)

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'is_public', 'steps',
                  'created_at', 'updated_at']


class WorkflowWriteSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, required=False)

    class Meta:
        model = Workflow
        fields = ['id', 'name', 'description', 'icon', 'is_public', 'steps']
        read_only_fields = ['id']

    def validate_steps(self, value):
        orders = [item['order'] for item in value]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError('步骤顺序不能重复。')
        request = self.context['request']
        organization = getattr(request, 'organization', None)
        requested = {item['application_id'] for item in value}
        from django.db.models import Q
        allowed = set(Application.objects.filter(id__in=requested).filter(
            Q(is_public=True) | Q(organization=organization) |
            Q(created_by=request.user),
        ).values_list('id', flat=True))
        if requested != allowed:
            raise serializers.ValidationError('包含不可用或未发布的应用版本。')
        return value

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
                name=item.get('name', ''),
                config=item.get('config', {}),
                order=item['order'],
            )
            for item in steps
        ])
