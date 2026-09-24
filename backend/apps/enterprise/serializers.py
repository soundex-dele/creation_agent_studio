from django.db.models import Sum
from rest_framework import serializers

from .models import (
    AuditLog, AutomationTrigger, Connector, EvaluationCase, EvaluationRun,
    EvaluationSuite,
    GovernancePolicy, IdentityProvider, Membership, Organization, ProviderConfig, QuotaPolicy, RunTrace,
    SecretReference, TraceSpan, UsageRecord,
)
from .services import monthly_usage_records


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'owner', 'is_active', 'settings', 'role',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'owner', 'role', 'created_at', 'updated_at']

    def get_role(self, obj):
        request = self.context.get('request')
        platform_role = getattr(getattr(request, 'user', None), 'role', None)
        if platform_role == 'admin':
            return Membership.Role.OWNER
        if platform_role == 'auditor':
            return Membership.Role.AUDITOR
        membership = obj.memberships.filter(user=request.user, is_active=True).first() \
            if request and request.user.is_authenticated else None
        if membership:
            return membership.role
        return None


class MembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    monthly_token_limit = serializers.IntegerField(
        min_value=0, max_value=9007199254740991, allow_null=True, required=False,
        help_text='Monthly token limit; null disables the member limit, zero blocks new runs.')
    monthly_tokens_used = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ['id', 'user_id', 'username', 'email', 'role', 'is_active',
                  'monthly_token_limit', 'monthly_tokens_used', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_role(self, value):
        if value == Membership.Role.OWNER:
            raise serializers.ValidationError('Ownership must be transferred explicitly.')
        return value

    def validate_user_id(self, value):
        if self.instance and value != self.instance.user_id:
            raise serializers.ValidationError('A membership cannot be reassigned.')
        return value

    def get_monthly_tokens_used(self, obj):
        totals = self.context.get('monthly_member_usage')
        if totals is not None:
            return totals.get(obj.user_id, 0)
        return monthly_usage_records(obj.organization).filter(user_id=obj.user_id).aggregate(
            tokens=Sum('total_tokens'))['tokens'] or 0


class AuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source='actor.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'
        read_only_fields = [field.name for field in AuditLog._meta.fields]


class QuotaPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotaPolicy
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at']


class UsageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageRecord
        fields = '__all__'
        read_only_fields = [field.name for field in UsageRecord._meta.fields]


class ProviderConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderConfig
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at']


class SecretReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecretReference
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at', 'rotated_at']

    def validate_reference(self, value):
        if value.lower().startswith(('http://', 'https://')):
            raise serializers.ValidationError('Use a Vault/KMS path, not a URL containing credentials.')
        return value


class IdentityProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = IdentityProvider
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GovernancePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = GovernancePolicy
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at']


class TraceSpanSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraceSpan
        fields = '__all__'


class RunTraceSerializer(serializers.ModelSerializer):
    spans = TraceSpanSerializer(many=True, read_only=True)

    class Meta:
        model = RunTrace
        exclude = ['organization']
        read_only_fields = ['id', 'user', 'request_id', 'created_at', 'spans']


class EvaluationCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationCase
        exclude = ['suite']
        read_only_fields = ['id', 'created_at', 'updated_at']


class EvaluationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationRun
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at', 'finished_at',
                            'execution_run', 'score', 'passed', 'results', 'error']


class EvaluationSuiteSerializer(serializers.ModelSerializer):
    case_count = serializers.IntegerField(source='cases.count', read_only=True)

    class Meta:
        model = EvaluationSuite
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at', 'case_count']


class ConnectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connector
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_endpoint(self, value):
        if value and not value.lower().startswith(('https://', 'http://')):
            raise serializers.ValidationError('Connector endpoint must be an HTTP(S) URL.')
        return value


class AutomationTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationTrigger
        exclude = ['organization']
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_triggered_at']

    def validate(self, attrs):
        trigger_type = attrs.get('trigger_type', getattr(self.instance, 'trigger_type', 'webhook'))
        schedule = attrs.get('schedule', getattr(self.instance, 'schedule', ''))
        if trigger_type == 'schedule':
            from .services import cron_matches
            from django.utils import timezone
            if not schedule or len(schedule.split()) != 5 or not any(
                    cron_matches(schedule, timezone.now().replace(minute=value))
                    for value in range(60)):
                raise serializers.ValidationError(
                    {'schedule': 'Use a valid five-field cron expression.'})
        target_type = attrs.get(
            'target_type', getattr(self.instance, 'target_type', '')
        )
        if target_type not in {'agent', 'application', 'workflow'}:
            raise serializers.ValidationError({
                'target_type': 'Use agent, application, or workflow.'
            })
        return attrs
