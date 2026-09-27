import type { RunEventEnvelope } from './types';

export interface AgentItem {
  id: string;
  type: string;
  text?: string;
  phase?: string;
  summary?: string[];
  review?: string;
  completed?: boolean;
  status?: string;
  agentNickname?: string;
  agentRole?: string;
  kind?: string;
  agentPath?: string;
}

export interface AgentActivityState {
  items?: Record<string, AgentItem>;
  tools?: Record<string, Record<string, unknown> & { output?: string }>;
  plan?: { explanation?: string; plan?: { step: string; status: string }[] };
  diff?: { diff?: string };
  warnings?: Record<string, unknown>[];
  usage?: Record<string, unknown>;
  session?: { can_steer?: boolean; thread_id?: string; turn_id?: string };
}

export function reduceAgentActivity(state: AgentActivityState = {}, event: RunEventEnvelope): AgentActivityState {
  const payload = event.payload;
  const id = String(payload.id || 'unknown');
  if (event.type === 'agent.item') {
    const previous = state.items?.[id];
    const item = { ...previous, ...payload } as unknown as AgentItem;
    if (typeof payload.delta === 'string') item.text = (previous?.text ?? '') + payload.delta;
    if (typeof payload.summary_delta === 'string') {
      item.summary = [...(previous?.summary ?? [])];
      const index = Math.min(100, Math.max(0, Number(payload.summary_index) || 0));
      while (item.summary.length <= index) item.summary.push('');
      item.summary[index] = (item.summary[index] + payload.summary_delta).slice(-100000);
    }
    for (const key of ['delta', 'summary_delta', 'summary_index']) delete (item as unknown as Record<string, unknown>)[key];
    return { ...state, items: { ...state.items, [id]: item } };
  }
  if (event.type === 'agent.tool') {
    const previous = state.tools?.[id];
    return { ...state, tools: { ...state.tools, [id]: { ...previous, ...payload,
      ...(typeof payload.delta === 'string' ? { output: ((previous?.output ?? '') + payload.delta).slice(-100000) } : {}),
    } } };
  }
  if (event.type === 'agent.warning') return { ...state, warnings: [...(state.warnings ?? []), payload].slice(-30) };
  if (['agent.plan', 'agent.diff', 'agent.usage', 'agent.session'].includes(event.type)) {
    return { ...state, [event.type.split('.')[1]]: payload };
  }
  return state;
}
