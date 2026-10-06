import { describe, expect, it } from 'vitest';
import { CONVERSATION_APP_ID as chat, mergeConversationHomePreferences } from '../conversationApplication';

describe('merged conversation preferences', () => {
  it('preserves the existing conversation position and visibility', () => {
    expect(mergeConversationHomePreferences({
      order: ['cowork', 'writer', chat, chat], hidden: ['cowork'],
    })).toEqual({ order: ['writer', chat], hidden: [] });
  });
  it('inherits cowork preferences when no conversation preference exists', () => {
    expect(mergeConversationHomePreferences({
      order: ['writer', 'cowork', 'cowork'], hidden: ['cowork'],
    })).toEqual({ order: ['writer', chat], hidden: [chat] });
  });
  it('preserves an explicitly hidden conversation and unrelated preferences', () => {
    const preferences = { order: ['writer', chat, 'cowork'], hidden: [chat, 'writer'] };
    const merged = mergeConversationHomePreferences(preferences);
    expect(merged).toEqual({ order: ['writer', chat], hidden: [chat, 'writer'] });
    expect(mergeConversationHomePreferences(merged)).toEqual(merged);
    expect(preferences.order).toContain('cowork');
  });
});
