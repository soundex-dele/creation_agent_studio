// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import { createCoworkApi, createUnifiedChatApi } from '../cowork';
import { createConversationStore, useConversationStore } from '@/stores/useConversationStore';

afterEach(() => vi.restoreAllMocks());

it('unifies all conversation actions while retaining folder project scope and the run transport', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue([]);
  const post = vi.spyOn(api, 'post').mockResolvedValue({});
  const del = vi.spyOn(api, 'delete').mockResolvedValue({});
  const client = createUnifiedChatApi();
  await client.get('/conversations/', { page: 2, project_id: 4 });
  expect(get).toHaveBeenLastCalledWith('/conversations/?scope=unified', { page: 2, project_id: 4 }, undefined);
  for (const action of ['', 'workspace-files/']) {
    await client.get(`/conversations/old/${action}`);
    expect(get).toHaveBeenLastCalledWith(`/conversations/old/${action}?scope=unified`, undefined, undefined);
  }
  for (const action of ['send_message/', 'workspace/', 'open-workspace/']) {
    await client.post(`/conversations/old/${action}`, {});
    expect(post).toHaveBeenLastCalledWith(`/conversations/old/${action}?scope=unified`, {}, undefined);
  }
  for (const action of ['clear/', 'delete_conversation/']) {
    await client.delete(`/conversations/old/${action}`);
    expect(del).toHaveBeenLastCalledWith(`/conversations/old/${action}?scope=unified`, undefined);
  }
  await client.post('/conversations/', { title: 'New' });
  expect(post).toHaveBeenLastCalledWith('/conversations/?scope=unified', { title: 'New', scope: 'cowork' }, undefined);
  await client.get('/projects/');
  expect(get).toHaveBeenLastCalledWith('/projects/?scope=cowork', undefined, undefined);
  await client.post('/organizations/org/runs/run/commands', { type: 'cancel' });
  expect(post).toHaveBeenLastCalledWith('/organizations/org/runs/run/commands', { type: 'cancel' }, undefined);
});

it('scopes resource lists, creation and deletion but preserves the run transport', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue([]);
  const post = vi.spyOn(api, 'post').mockResolvedValue({});
  const del = vi.spyOn(api, 'delete').mockResolvedValue({});
  const client = createCoworkApi();
  await client.get('/conversations/', { page: 2 });
  expect(get).toHaveBeenCalledWith('/conversations/?scope=cowork', { page: 2 }, undefined);
  await client.post('/conversations/', { title: 'New', scope: 'default' });
  expect(post).toHaveBeenCalledWith('/conversations/?scope=cowork', { title: 'New', scope: 'cowork' }, undefined);
  await client.delete('/projects/2/');
  expect(del).toHaveBeenCalledWith('/projects/2/?scope=cowork', undefined);
  await client.post('/organizations/org/runs/run/commands', { type: 'cancel' });
  expect(post).toHaveBeenCalledWith('/organizations/org/runs/run/commands', { type: 'cancel' }, undefined);
});

it('keeps CoWork conversation state independent of ordinary and other tenant sessions', () => {
  const existing = useConversationStore.getState().currentConversation;
  const first = createConversationStore(undefined, createCoworkApi(), 'cowork-one');
  const second = createConversationStore(undefined, createCoworkApi(), 'cowork-two');
  first.getState().setCurrentConversation({ id: 'cowork-1', title: 'Task', messages: [], created_at: '', updated_at: '' });
  expect(second.getState().currentConversation).toBeNull();
  expect(useConversationStore.getState().currentConversation).toBe(existing);
  expect(first.persist.getOptions().name).toBe('cowork-one');
  first.getState().reset(); second.getState().reset();
});
