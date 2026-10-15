import { api } from './api';

export type EntryKind = 'ideas' | 'todos' | 'memos';
export type TodoStatus = 'pending' | 'all' | 'completed' | 'today' | 'overdue';
export type Priority = 1 | 2 | 3;

interface PersonalEntry {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface Idea extends PersonalEntry {
  body: string;
  tags: string[];
  is_pinned: boolean;
}
export interface Todo extends PersonalEntry {
  description: string;
  priority: Priority;
  due_date: string | null;
  is_completed: boolean;
  completed_at: string | null;
}
export interface Memo extends PersonalEntry {
  body: string;
  is_pinned: boolean;
}
export type Entry = Idea | Todo | Memo;
export interface EntryPage<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
export type IdeaInput = Pick<Idea, 'title' | 'body' | 'tags' | 'is_pinned'>;
export type TodoInput = Pick<Todo, 'title' | 'description' | 'priority' | 'due_date'>;
export type MemoInput = Pick<Memo, 'title' | 'body' | 'is_pinned'>;

export { localDate } from '@platform/utils';

export { entryError } from '@platform/utils';

export function ideasTodosApi(base: string) {
  return {
    list: (kind: EntryKind, params: Record<string, unknown>, signal: AbortSignal) =>
      api.get<EntryPage<Entry>>(`${base}/${kind}`, params, { signal }),
    createMemo: (data: MemoInput) => api.post<Memo>(`${base}/memos`, data),
    updateMemo: (id: string, data: Partial<MemoInput>) => api.patch<Memo>(`${base}/memos/${id}`, data),
    createIdea: (data: IdeaInput) => api.post<Idea>(`${base}/ideas`, data),
    createTodo: (data: TodoInput) => api.post<Todo>(`${base}/todos`, data),
    updateIdea: (id: string, data: Partial<IdeaInput>) => api.patch<Idea>(`${base}/ideas/${id}`, data),
    updateTodo: (id: string, data: Partial<TodoInput> & { is_completed?: boolean }) => api.patch<Todo>(`${base}/todos/${id}`, data),
    remove: (kind: EntryKind, id: string) => api.delete(`${base}/${kind}/${id}`),
  };
}
