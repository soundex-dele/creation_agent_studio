import { describe, expect, it } from 'vitest';
import { decodeProgress, emptyProgress, encodeProgress, reduceProgress, sessionFor, storageKey } from '../storage';
import { levels } from '../levels';

describe('local Sokoban progress', () => {
  it('round-trips all levels, selection, undo history and best scores', () => {
    let progress = emptyProgress();
    progress = reduceProgress(progress, { type: 'move', direction: 'R' });
    progress = reduceProgress(progress, { type: 'move', direction: 'R' });
    expect(sessionFor(progress).bestMoves).toBe(2);
    progress = reduceProgress(progress, { type: 'select', id: levels[1].id });
    progress = reduceProgress(progress, { type: 'move', direction: 'R' });
    expect(decodeProgress(encodeProgress(progress))).toEqual(progress);
    progress = reduceProgress(progress, { type: 'select', id: levels[0].id });
    progress = reduceProgress(progress, { type: 'undo' });
    expect(sessionFor(progress).state.moves).toBe(1);
    expect(sessionFor(progress).bestMoves).toBe(2);
    progress = reduceProgress(progress, { type: 'restart' });
    expect(sessionFor(progress).state.moves).toBe(0);
    expect(sessionFor(progress).state.history).toEqual([]);
    expect(sessionFor(progress).bestMoves).toBe(2);
    expect(progress.sessions[levels[1].id].state.moves).toBe(1);
  });
  it('keeps the better score after a longer replay', () => {
    let progress = emptyProgress();
    for (const direction of ['R', 'R'] as const) progress = reduceProgress(progress, { type: 'move', direction });
    progress = reduceProgress(progress, { type: 'restart' });
    for (const direction of ['U', 'D', 'R', 'R'] as const) progress = reduceProgress(progress, { type: 'move', direction });
    expect(sessionFor(progress).state.moves).toBe(4);
    expect(sessionFor(progress).bestMoves).toBe(2);
  });
  it('handles absent storage and rejects corrupt, incompatible or illegal records', () => {
    expect(decodeProgress(null)).toEqual(emptyProgress());
    const valid = { version: 1, currentLevelId: levels[0].id, sessions: {} };
    for (const raw of ['broken', 'null', '{}', JSON.stringify({ ...valid, version: 2 }),
      JSON.stringify({ ...valid, currentLevelId: '__proto__' }),
      JSON.stringify({ ...valid, sessions: { [levels[0].id]: { path: 'RRR' } } }),
      JSON.stringify({ ...valid, sessions: { [levels[0].id]: { path: '', bestMoves: -2 } } })]) expect(() => decodeProgress(raw)).toThrow();
    const progress = emptyProgress();
    expect(reduceProgress(progress, { type: 'select', id: 'constructor' })).toBe(progress);
  });
  it('isolates users, organizations and applications with unambiguous keys', () => {
    const keys = [storageKey('org', 'a', '1'), storageKey('org', 'b', '1'), storageKey('other', 'a', '1'), storageKey('org', 'a', '2'), storageKey('a:b', 'c', '1'), storageKey('a', 'b:c', '1')];
    expect(new Set(keys).size).toBe(keys.length);
  });
});
