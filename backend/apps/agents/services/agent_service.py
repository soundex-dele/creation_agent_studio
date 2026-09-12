from typing import Dict, Any
import time

from django.utils import timezone

from core.llm.factory import build_agent_engine
from ..models import Agent, AgentExecution
from ..runtime import get_agent_definition


class AgentService:
    @staticmethod
    def execute(agent: Agent, user, input_data: Dict[str, Any]) -> AgentExecution:
        from apps.enterprise.services import apply_input_guardrails, enforce_quota, record_usage
        from apps.enterprise.models import RunTrace, TraceSpan
        enforce_quota(agent.organization)
        input_data = {
            **input_data,
            '_governed_input': apply_input_guardrails(
                agent.organization, str(input_data)),
        }
        started = time.monotonic()
        execution = AgentExecution.objects.create(
            agent=agent,
            user=user,
            input_data=input_data,
            status='running'
        )
        trace = None
        span = None
        if agent.organization:
            trace = RunTrace.objects.create(
                organization=agent.organization, user=user, kind='agent',
                resource_id=str(agent.id), status=RunTrace.Status.RUNNING,
                input=input_data, started_at=timezone.now())
            span = TraceSpan.objects.create(
                trace=trace, name='llm.completion', kind='llm', input=input_data)
        try:
            definition = get_agent_definition(agent)
            model_config = definition.get('model_config') or {}
            configured_model = model_config.get('model', '')
            engine = build_agent_engine(
                agent.organization,
                configured_model,
                adapter_name=model_config.get('adapter', ''),
            )
            messages = [
                {"role": "system", "content": definition.get('system_prompt', '')},
                {"role": "user", "content": str(input_data)},
            ]
            response = engine.complete(messages)
            if not response.success:
                execution.status = 'failed'
                execution.error_message = response.error or 'LLM 请求失败'
            else:
                execution.output_data = {
                    'result': response.content,
                    'model': response.model,
                    'usage': response.usage.model_dump(),
                }
                execution.status = 'completed'
        except Exception as e:
            execution.status = 'failed'
            execution.error_message = str(e)
        finally:
            execution.updated_at = timezone.now()
            execution.save()
            if trace:
                trace.status = (RunTrace.Status.SUCCEEDED if execution.status == 'completed'
                                else RunTrace.Status.FAILED)
                trace.output = execution.output_data or {}
                trace.error = execution.error_message
                trace.finished_at = timezone.now()
                trace.save(update_fields=['status', 'output', 'error', 'finished_at'])
            if span:
                span.status = 'ok' if execution.status == 'completed' else 'error'
                span.output = execution.output_data or {}
                span.error = execution.error_message
                span.finished_at = timezone.now()
                span.save(update_fields=['status', 'output', 'error', 'finished_at'])
            usage = (execution.output_data or {}).get('usage', {})
            record_usage(
                organization=agent.organization, user=user,
                resource_type='agent_execution', resource_id=execution.id,
                usage=usage,
                model=(execution.output_data or {}).get('model', ''),
                latency_ms=(time.monotonic() - started) * 1000,
                status='success' if execution.status == 'completed' else 'failed',
            )
        return execution
