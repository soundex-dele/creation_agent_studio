export type AutomationStatus = 'draft' | 'active' | 'paused' | 'blocked' | 'archived';
export type AutomationTriggerType = 'schedule' | 'webhook';
export type AutomationTargetType = 'application' | 'workflow';
export type AutomationScheduleKind = 'once' | 'cron';

export interface AutomationInvocation {
  id: string;
  source: 'schedule' | 'webhook' | 'manual';
  scheduled_for?: string | null;
  outcome: string;
  status: string;
  run_id?: string | null;
  error?: string;
  created_at: string;
}

export interface Automation {
  id: number;
  name: string;
  description: string;
  status: AutomationStatus;
  trigger_type: AutomationTriggerType;
  target_type: AutomationTargetType;
  target_id: string;
  target_name: string;
  default_input: Record<string, unknown>;
  schedule_kind: AutomationScheduleKind | '';
  timezone: string;
  run_at?: string | null;
  schedule: string;
  next_run_at?: string | null;
  last_scheduled_at?: string | null;
  last_triggered_at?: string | null;
  public_id: string;
  webhook_url: string;
  secret_prefix: string;
  secret_rotated_at?: string | null;
  blocked_reason: string;
  created_by: number;
  created_by_username: string;
  created_at: string;
  updated_at: string;
  last_invocation?: AutomationInvocation | null;
  webhook_secret?: string;
}

export interface AutomationTarget {
  type: AutomationTargetType;
  id: string;
  name: string;
  description: string;
}
