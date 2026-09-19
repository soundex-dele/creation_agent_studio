import { describe, expect, it } from 'vitest';

import {
  defaultTopicFilters,
  restoreTopicFilters,
  topicFilterReducer,
  topicMatchesFilters,
} from '@creation-toolbox/topicDomain';

const topic = {
  title: '普通人如何建立知识库',
  notes: '从真实使用场景切入',
  source_name: '用户访谈',
  tags: ['知识管理', '效率'],
  status: 'ready' as const,
};

describe('creation toolbox topic domain', () => {
  it('filters topics by normalized query, status and tag', () => {
    expect(topicMatchesFilters(topic, { ...defaultTopicFilters, search: '知识库' })).toBe(true);
    expect(topicMatchesFilters(topic, { ...defaultTopicFilters, search: '访谈', status: 'ready' })).toBe(true);
    expect(topicMatchesFilters(topic, { ...defaultTopicFilters, tag: '效率', status: 'pending' })).toBe(false);
  });

  it('restores safe persisted filters and reducer updates one domain field', () => {
    expect(restoreTopicFilters('{"search":"知识","layout":"cards","status":"ready"}')).toEqual({
      search: '知识', layout: 'cards', status: 'ready', tag: '',
    });
    expect(restoreTopicFilters('broken')).toBe(defaultTopicFilters);
    expect(topicFilterReducer(defaultTopicFilters, { type: 'tag', value: '效率' }).tag).toBe('效率');
  });
});
