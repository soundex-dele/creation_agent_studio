import { initialState, isSolved, move, replay, undo, type Direction, type GameState } from './engine';
import { boards, levels } from './levels';

export interface Session { state: GameState; bestMoves?: number }
export interface Progress { currentLevelId: string; sessions: Record<string, Session> }
export type Action = { type: 'move'; direction: Direction } | { type: 'undo' | 'restart' } | { type: 'select'; id: string };
export const storageKey = (organization: string, user: string, application: string) =>
  `sokoban:v1:${encodeURIComponent(organization)}:${encodeURIComponent(user)}:${encodeURIComponent(application)}`;
export const emptyProgress = (): Progress => ({ currentLevelId: levels[0].id, sessions: {} });
export const sessionFor = (progress: Progress, id = progress.currentLevelId): Session =>
  progress.sessions[id] ?? { state: initialState(boards[id]) };

export function reduceProgress(progress: Progress, action: Action): Progress {
  if (action.type === 'select') return levels.some(level => level.id === action.id) ? { ...progress, currentLevelId: action.id } : progress;
  const id = progress.currentLevelId;
  const board = boards[id];
  const session = sessionFor(progress);
  const state = action.type === 'move' ? move(board, session.state, action.direction)
    : action.type === 'undo' ? undo(session.state) : initialState(board);
  if (state === session.state) return progress;
  const bestMoves = isSolved(board, state) ? Math.min(session.bestMoves ?? Infinity, state.moves) : session.bestMoves;
  return { ...progress, sessions: { ...progress.sessions, [id]: { state, bestMoves } } };
}

export function encodeProgress(progress: Progress): string {
  return JSON.stringify({ version: 1, currentLevelId: progress.currentLevelId,
    sessions: Object.fromEntries(Object.entries(progress.sessions).map(([id, session]) =>
      [id, { path: session.state.path, bestMoves: session.bestMoves }])) });
}

export function decodeProgress(raw: string | null): Progress {
  if (!raw) return emptyProgress();
  const saved = JSON.parse(raw);
  if (saved?.version !== 1 || !levels.some(level => level.id === saved.currentLevelId)
    || !saved.sessions || typeof saved.sessions !== 'object' || Array.isArray(saved.sessions)) throw new Error('存档格式无效');
  const progress: Progress = { currentLevelId: saved.currentLevelId, sessions: {} };
  for (const [id, value] of Object.entries(saved.sessions)) {
    if (!levels.some(level => level.id === id)) continue;
    const session = value as { path?: unknown; bestMoves?: unknown } | null;
    if (!session || typeof session.path !== 'string') throw new Error('存档记录无效');
    if (session.bestMoves !== undefined && (!Number.isSafeInteger(session.bestMoves) || (session.bestMoves as number) < 1)) throw new Error('成绩无效');
    const state = replay(boards[id], session.path);
    const best = session.bestMoves as number | undefined;
    progress.sessions[id] = { state, bestMoves: isSolved(boards[id], state) ? Math.min(best ?? Infinity, state.moves) : best };
  }
  return progress;
}

export function loadProgress(key: string): { progress: Progress; warning: string } {
  let raw: string | null;
  try { raw = window.localStorage.getItem(key); }
  catch { return { progress: emptyProgress(), warning: '浏览器存储不可用，进度暂时无法保存。你仍然可以游玩。' }; }
  try { return { progress: decodeProgress(raw), warning: '' }; }
  catch { return { progress: emptyProgress(), warning: '本机存档已损坏或不兼容，已恢复初始状态。' }; }
}
