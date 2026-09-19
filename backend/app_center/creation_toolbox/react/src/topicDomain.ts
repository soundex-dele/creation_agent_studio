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
  | { type: 'reset' };

export const defaultTopicFilters: TopicFilterState = {
  search: '', status: '', tag: '', layout: 'list',
};

export function topicFilterReducer(state: TopicFilterState, action: TopicFilterAction): TopicFilterState {
  if (action.type === 'reset') return defaultTopicFilters;
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
  tags: string[];
  status: Exclude<TopicFilterStatus, ''>;
}

export function topicMatchesFilters(topic: SearchableTopic, filters: TopicFilterState): boolean {
  const query = filters.search.trim().toLocaleLowerCase();
  const matchesQuery = !query || [topic.title, topic.notes, topic.source_name, ...topic.tags]
    .some((value) => value.toLocaleLowerCase().includes(query));
  return matchesQuery
    && (!filters.status || topic.status === filters.status)
    && (!filters.tag || topic.tags.includes(filters.tag));
}
