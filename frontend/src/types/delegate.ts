export interface DelegateLimits {
  max_tasks: number;
  max_replans: number;
  max_parallelism: number;
  timeout_seconds: number;
}

export interface Delegate {
  id: number;
  name: string;
  slug: string;
  description: string;
  icon: string;
  visibility: 'private' | 'organization';
  role_prompt: string;
  principles: string[];
  output_preferences: string;
  agent_ids: number[];
  application_ids: number[];
  model_config: Record<string, unknown>;
  limits: DelegateLimits;
  draft_version: number;
  active_revision_id: string | null;
  is_active: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_toggle: boolean;
  can_run: boolean;
  created_by_id: number;
  created_at: string;
  updated_at: string;
}

export interface SupervisorTaskPlan {
  key: string;
  title: string;
  target_type: 'agent' | 'application';
  target_id: number;
  instructions: string;
  depends_on: string[];
  expected_output: string;
  input: Record<string, unknown>;
}

export interface SupervisorPlan {
  plan_version: number;
  objective: string;
  assumptions: string[];
  tasks: SupervisorTaskPlan[];
  delivery_criteria: string[];
  budget: Record<string, number>;
}

export interface DelegateInstance {
  id: number;
  title: string;
  agent: { id: number; name: string; icon: string; description: string } | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message: {
    id: number;
    role: string;
    content: string;
    created_at: string;
  } | null;
}
