import type { RunResource } from '@/services/applicationRuntime';
import type { WorkflowStep } from '@/types';


export function workflowApplicationPath(
  step: WorkflowStep,
  embedded = true,
  workflowId?: string,
  manualRun?: RunResource | null,
) {
  const application = step.application;
  const applicationId = step.application_id
    ?? application.application_id
    ?? application.id;
  const embeddedQuery = embedded ? 'embedded=1' : '';

  if (application.kind === 'chat') {
    const conversationMap = manualRun?.output_summary?.conversations as
      | Record<string, string>
      | undefined;
    const query = new URLSearchParams({
      slug: application.application_slug,
      ...(embedded ? { embedded: '1' } : {}),
      ...(workflowId ? { workflowId } : {}),
      ...(manualRun ? { manualRunId: manualRun.id, workflowStepKey: step.key } : {}),
      ...(conversationMap?.[step.key]
        ? { conversation: conversationMap[step.key] }
        : {}),
    });
    return `/applications/${applicationId}/chat?${query.toString()}`;
  }
  if (application.renderer_key === 'contacts') {
    return `/applications/${applicationId}/contacts${embeddedQuery ? `?${embeddedQuery}` : ''}`;
  }
  if (application.renderer_key === 'creation-master') {
    return `/applications/${applicationId}/creation-master${
      embeddedQuery ? `?${embeddedQuery}` : ''
    }`;
  }
  return `/applications/${applicationId}/run${embeddedQuery ? `?${embeddedQuery}` : ''}`;
}
