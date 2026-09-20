export type TopicFilterStatus = 'pending' | 'ready' | 'adopted' | 'postponed' | 'archived' | '';

export interface TopicFilterState {
  search: string;
  status: TopicFilterStatus;
  tag: string;
  layout: 'list' | 'cards';
}

export type TopicFilterAction =
  | { type: 'search'; value: string }
  | { type: 'status'; value: TopicFilterStatus }
  | { type: 'tag'; value: string }
  | { type: 'layout'; value: 'list' | 'cards' }
  | { type: 'reveal-created' }
  | { type: 'reset' };

export const defaultTopicFilters: TopicFilterState = {
  search: '', status: '', tag: '', layout: 'list',
};

export function topicFilterReducer(state: TopicFilterState, action: TopicFilterAction): TopicFilterState {
  if (action.type === 'reset') return defaultTopicFilters;
  if (action.type === 'reveal-created') return { ...state, search: '', status: '', tag: '' };
  return { ...state, [action.type]: action.value };
}

export function restoreTopicFilters(raw: string | null): TopicFilterState {
  if (!raw) return defaultTopicFilters;
  try {
    const value = JSON.parse(raw) as Partial<TopicFilterState>;
    return {
      search: typeof value.search === 'string' ? value.search : '',
      status: ['pending', 'ready', 'adopted', 'postponed', 'archived'].includes(value.status || '')
        ? value.status as TopicFilterStatus : '',
      tag: typeof value.tag === 'string' ? value.tag : '',
      layout: value.layout === 'cards' ? 'cards' : 'list',
    };
  } catch {
    return defaultTopicFilters;
  }
}

export interface SearchableTopic {
  title: string;
  notes: string;
  source_name: string;
  parent_title?: string;
  tags: string[];
  status: Exclude<TopicFilterStatus, ''>;
}

export function topicMatchesFilters(topic: SearchableTopic, filters: TopicFilterState): boolean {
  const query = filters.search.trim().toLocaleLowerCase();
  const matchesQuery = !query || [topic.title, topic.notes, topic.source_name, topic.parent_title || '', ...topic.tags]
    .some((value) => value.toLocaleLowerCase().includes(query));
  return matchesQuery
    && (!filters.status || topic.status === filters.status)
    && (!filters.tag || topic.tags.includes(filters.tag));
}

export function prependCreatedTopic<T extends { id: string }>(topics: T[], created: T): T[] {
  return [created, ...topics.filter((topic) => topic.id !== created.id)];
}

export function toggleTopicSelection(selected: string[], topicId: string, checked: boolean): string[] {
  if (checked) return selected.includes(topicId) ? selected : [...selected, topicId];
  return selected.filter((id) => id !== topicId);
}

export function retainVisibleTopicSelection(selected: string[], visibleIds: string[]): string[] {
  const visible = new Set(visibleIds);
  const next = selected.filter((id) => visible.has(id));
  return next.length === selected.length ? selected : next;
}

export function topicRowStateClassName(topicId: string, currentId: string, selected: string[]): string {
  return [topicId === currentId ? 'active' : '', selected.includes(topicId) ? 'selected' : '']
    .filter(Boolean)
    .join(' ');
}
