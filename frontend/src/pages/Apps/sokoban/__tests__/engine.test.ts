import { describe, expect, it } from 'vitest';
import { initialState, isSolved, move, parseLevel, replay, undo, type Level } from '../engine';
import { boards, levels } from '../levels';
import solutions from './solutions.json';

const boardFor = (map: string[]) => parseLevel({ id: 'test', name: 'Test', difficulty: '入门', map });

describe('Sokoban rules', () => {
  it('walks without pulling, counts only legal moves, and cannot cross walls', () => {
    const board = boardFor(['#######', '#@ $ .#', '#######']);
    const start = initialState(board);
    expect(move(board, start, 'L')).toBe(start);
    expect(move(board, start, 'U')).toBe(start);
    const walked = move(board, start, 'R');
    expect(walked.moves).toBe(1);
    expect(walked.pushes).toBe(0);
    const pushed = move(board, walked, 'R');
    expect(pushed.boxes).toEqual([11]);
    expect(pushed.pushes).toBe(1);
    expect(move(board, pushed, 'L').boxes).toEqual(pushed.boxes);
  });
  it('cannot push two boxes or a box into a wall', () => {
    for (const map of [['########', '#@$$ ..#', '########'], ['######', '# @$##', '# .  #', '######']]) {
      const board = boardFor(map);
      const state = initialState(board);
      expect(move(board, state, 'R')).toBe(state);
    }
  });
  it('allows a box to leave a goal while the other boxes are unfinished', () => {
    const board = boardFor(['########', '#@*  $.#', '#      #', '########']);
    const next = move(board, initialState(board), 'R');
    expect(next.boxes).not.toContain(10);
    expect(board.goals.has(10)).toBe(true);
    expect(isSolved(board, next)).toBe(false);
  });
  it('wins, freezes movement, and can undo a winning push', () => {
    const board = boards[levels[0].id];
    const one = move(board, initialState(board), 'R');
    const won = move(board, one, 'R');
    expect(isSolved(board, won)).toBe(true);
    expect(move(board, won, 'L')).toBe(won);
    expect(undo(won)).toEqual(one);
    expect(undo(undo(won))).toEqual(initialState(board));
    const empty = initialState(board);
    expect(undo(empty)).toBe(empty);
  });
  it('does not wrap across row edges or enter void tiles', () => {
    const board = boardFor(['  @', '$ .']);
    const state = initialState(board);
    expect(move(board, state, 'R')).toBe(state);
    const voidBoard = boardFor(['@-$.' ]);
    const voidState = initialState(voidBoard);
    expect(move(voidBoard, voidState, 'R')).toBe(voidState);
  });
  it('rejects malformed maps and impossible replay paths', () => {
    for (const map of [[], ['###', '##'], ['@$$.'], ['@@$.'], ['@$.?']]) expect(() => boardFor(map)).toThrow();
    const board = boards[levels[0].id];
    for (const path of ['X', 'UU', 'RRR']) expect(() => replay(board, path)).toThrow();
  });
});

describe('20 original warehouse levels', () => {
  it('has stable unique IDs, unique maps, and three difficulty groups', () => {
    expect(levels).toHaveLength(20);
    expect(new Set(levels.map(level => level.id)).size).toBe(20);
    expect(new Set(levels.map(level => level.map.join('\n'))).size).toBe(20);
    expect(new Set(levels.map(level => level.difficulty))).toEqual(new Set(['入门', '进阶', '挑战']));
    expect(Object.keys(solutions).sort()).toEqual(levels.map(level => level.id).sort());
  });
  it.each(levels)('$id $name has a legal, winning solution and reversible history', (level: Level) => {
    const board = boards[level.id];
    expect(isSolved(board, initialState(board))).toBe(false);
    const path = solutions[level.id as keyof typeof solutions];
    let state = replay(board, path);
    expect(isSolved(board, state)).toBe(true);
    expect(state.moves).toBe(path.length);
    expect(state.pushes).toBeGreaterThan(0);
    while (state.history.length) state = undo(state);
    expect(state).toEqual(initialState(board));
  });
});
