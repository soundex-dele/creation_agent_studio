export type ApplicationKind = 'chat' | 'task' | 'custom';

export interface SkillBinding {
  skill_id: string;
  skill_name: string;
  skill_slug: string;
  mode: 'required' | 'default' | 'optional';
}

export interface AgentBinding {
  agent_id: number;
  agent_name: string;
  agent_slug: string;
  agent_icon?: string;
  label?: string;
  is_default: boolean;
}

export interface GuidedOption {
  id: string;
  value: string;
  label: string;
  description?: string;
  icon?: string;
  order?: number;
}

export interface GuidedQuestion {
  id: string;
  key: string;
  label: string;
  help_text?: string;
  type: 'text' | 'single_choice' | 'multi_choice' | 'number' | 'file';
  placeholder?: string;
  required: boolean;
  default_value?: unknown;
  order?: number;
  options: GuidedOption[];
}

export interface GuidedPrompt {
  id?: string;
  key: string;
  title: string;
  description?: string;
  icon?: string;
  prompt_template: string;
  action: 'fill' | 'preview' | 'send';
  is_featured: boolean;
  order?: number;
  questions: GuidedQuestion[];
}

export interface ChatApplicationProfile {
  welcome_message?: string;
  input_placeholder?: string;
  empty_state_title?: string;
  allow_agent_selection: boolean;
  allow_skill_selection: boolean;
  allow_extra_skills: boolean;
  conversation_policy?: 'new_each_open' | 'resume_last' | 'choose_history';
  starter_layout: 'cards' | 'list' | 'compact';
}

export interface BaseApplicationRuntime {
  id: number;
  application_id: number;
  organization_id?: string;
  environment?: 'development' | 'staging' | 'production';
  application_slug: string;
  application_name: string;
  application_description: string;
  application_icon: string;
  application_color?: string;
  renderer_key: string;
  executor_key?: string;
  default_config: Record<string, unknown>;
}

export interface ChatApplicationRuntime extends BaseApplicationRuntime {
  kind: 'chat';
  renderer_key: 'chat';
  chat_profile: ChatApplicationProfile;
  agent_bindings: AgentBinding[];
  skill_bindings: SkillBinding[];
  guided_prompts: GuidedPrompt[];
}

export interface StandardApplicationRuntime extends BaseApplicationRuntime {
  kind: 'task' | 'custom';
}

export type ApplicationRuntime = ChatApplicationRuntime | StandardApplicationRuntime;

export interface BaseApplicationDefinition {
  executor_kind: 'agent' | 'media' | 'workflow' | 'evaluation';
  executor_key: string;
  executor_protocol_version?: number;
  renderer_key?: string | null;
  renderer_schema_version?: number;
  retry_policy?: { max_attempts: number; retry_safe: boolean };
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  default_config?: Record<string, unknown>;
}

export interface ChatApplicationDefinition extends BaseApplicationDefinition {
  kind: 'chat';
  executor_kind: 'agent';
  renderer_key: 'chat';
  chat_profile: ChatApplicationProfile;
  agent_bindings: AgentBinding[];
  skill_bindings: SkillBinding[];
  guided_prompts: GuidedPrompt[];
}

export interface StandardApplicationDefinition extends BaseApplicationDefinition {
  kind: 'task' | 'custom';
}

export type ApplicationDefinition =
  | ChatApplicationDefinition
  | StandardApplicationDefinition;

export interface WorkflowStep {
  id: string;
  key: string;
  name?: string;
  order: number;
  config: Record<string, unknown>;
  depends_on: string[];
  condition: Record<string, unknown>;
  max_attempts: number;
  application_id?: number;
  application: ApplicationRuntime;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  execution_mode: 'manual' | 'automatic';
  is_public: boolean;
  step_count?: number;
  steps?: WorkflowStep[];
  created_at?: string;
  updated_at?: string;
}
