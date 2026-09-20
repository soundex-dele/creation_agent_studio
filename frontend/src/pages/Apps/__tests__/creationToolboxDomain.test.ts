import { describe, expect, it } from 'vitest';

import {
  defaultTopicFilters,
  prependCreatedTopic,
  retainVisibleTopicSelection,
  restoreTopicFilters,
  toggleTopicSelection,
  topicFilterReducer,
  topicMatchesFilters,
  topicRowStateClassName,
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
    expect(topicMatchesFilters({ ...topic, title: '子方向', parent_title: '知识库系列' }, { ...defaultTopicFilters, search: '知识库系列' })).toBe(true);
  });

  it('restores safe persisted filters and reducer updates one domain field', () => {
    expect(restoreTopicFilters('{"search":"知识","layout":"cards","status":"ready"}')).toEqual({
      search: '知识', layout: 'cards', status: 'ready', tag: '',
    });
    expect(restoreTopicFilters('broken')).toBe(defaultTopicFilters);
    expect(topicFilterReducer(defaultTopicFilters, { type: 'tag', value: '效率' }).tag).toBe('效率');
  });

  it('clears visibility filters after creating a topic while preserving the layout', () => {
    expect(topicFilterReducer({
      search: '旧关键词', status: 'ready', tag: '效率', layout: 'cards',
    }, { type: 'reveal-created' })).toEqual({
      search: '', status: '', tag: '', layout: 'cards',
    });
  });

  it('prepends the created topic to local state without duplicating it', () => {
    const oldTopic = { id: 'old', title: '旧选题' };
    const created = { id: 'created', title: '刚记录的选题' };
    expect(prependCreatedTopic([oldTopic], created)).toEqual([created, oldTopic]);
    expect(prependCreatedTopic([created, oldTopic], created)).toEqual([created, oldTopic]);
  });

  it('keeps every checked topic selected and exposes selection separately from the current row', () => {
    const first = toggleTopicSelection([], 'first', true);
    const both = toggleTopicSelection(first, 'second', true);
    expect(both).toEqual(['first', 'second']);
    expect(topicRowStateClassName('first', 'first', both)).toBe('active selected');
    expect(topicRowStateClassName('second', 'first', both)).toBe('selected');
    expect(toggleTopicSelection(both, 'first', false)).toEqual(['second']);
  });

  it('drops hidden topic selections when filters change', () => {
    expect(retainVisibleTopicSelection(['visible', 'hidden'], ['visible'])).toEqual(['visible']);
  });
});
