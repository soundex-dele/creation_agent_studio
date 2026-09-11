/** Fetch-based SSE client for Codex-shaped agent turns. */
import type { AgentProtocolEvent } from './agentProtocol';
import { API_BASE_URL } from './apiBaseUrl';

export interface SSEDoneEvent {
  type: 'done';
  conversation_id: string;
  message_id: string;
  tokens_used: number;
}

export interface SSEEventHandler {
  onEvent: (event: AgentProtocolEvent) => void;
  onDone?: (event: SSEDoneEvent) => void;
  onError?: (error: Error) => void;
}

export interface ChatRunOptions {
  permissionMode?: 'default' | 'allow_all';
  skills?: string[];
  agentId?: number | null;
}

export function streamChat(
  conversationId: string,
  message: string,
  handlers: SSEEventHandler,
  options: ChatRunOptions = {},
): AbortController {
  const controller = new AbortController();
  const authToken = localStorage.getItem('token') || getStoredToken();
  const url = `${API_BASE_URL}/conversations/${conversationId}/stream/`;

  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: JSON.stringify({
      message,
      permission_mode: options.permissionMode || 'default',
      skills: options.skills || [],
      agent_id: options.agentId,
      protocol_version: 2,
    }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let complete = false;
      while (!complete) {
        const { done, value } = await reader.read();
        complete = done;
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        frames.forEach((frame) => dispatchFrame(frame, handlers));

        if (complete) {
          if (buffer.trim()) dispatchFrame(buffer, handlers);
        }
      }
    })
    .catch((error: Error & { name?: string }) => {
      if (error.name !== 'AbortError') handlers.onError?.(error);
    });

  return controller;
}

function dispatchFrame(frame: string, handlers: SSEEventHandler): void {
  if (!frame.trim() || frame.trimStart().startsWith(':')) return;
  let eventName = 'message';
  const dataLines: string[] = [];
  frame.split(/\r?\n/).forEach((line) => {
    if (line.startsWith('event:')) eventName = line.slice(6).trim();
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  });
  if (!dataLines.length) return;
  try {
    const payload = JSON.parse(dataLines.join('\n'));
    if (eventName === 'done' || payload.type === 'done') {
      handlers.onDone?.(payload as SSEDoneEvent);
    } else {
      handlers.onEvent(payload as AgentProtocolEvent);
    }
  } catch {
    // Ignore malformed/incomplete server frames; the next valid event continues.
  }
}

export async function resumeAgent(
  conversationId: string,
  answer: { text?: string; selections?: string[] },
): Promise<void> {
  await postAgentAction(conversationId, 'resume', answer);
}

export async function cancelAgentTurn(conversationId: string): Promise<void> {
  await postAgentAction(conversationId, 'cancel-turn', {});
}

async function postAgentAction(
  conversationId: string,
  action: string,
  body: Record<string, unknown>,
): Promise<void> {
  const authToken = localStorage.getItem('token') || getStoredToken();
  const response = await fetch(
    `${API_BASE_URL}/conversations/${conversationId}/${action}/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
}

function getStoredToken(): string | null {
  try {
    const authStorage = localStorage.getItem('auth-storage');
    if (authStorage) return JSON.parse(authStorage)?.state?.token || null;
  } catch {
    // Ignore malformed persisted auth state.
  }
  return null;
}
