export type Direction = 'U' | 'D' | 'L' | 'R';
export interface Level {
  id: string;
  name: string;
  difficulty: '入门' | '进阶' | '挑战';
  map: string[];
}
export interface Board {
  width: number;
  height: number;
  floors: Set<number>;
  goals: Set<number>;
  walls: Set<number>;
  player: number;
  boxes: number[];
}
export interface Snapshot { player: number; boxes: number[]; moves: number; pushes: number }
export interface GameState extends Snapshot { history: Snapshot[]; path: string }

export function parseLevel(level: Level): Board {
  const width = level.map[0]?.length ?? 0;
  const board: Board = { width, height: level.map.length, floors: new Set(), goals: new Set(), walls: new Set(), player: -1, boxes: [] };
  let players = 0;
  if (!width || level.map.some(row => row.length !== width)) throw new Error('关卡地图尺寸无效');
  level.map.forEach((row, y) => [...row].forEach((tile, x) => {
    const cell = y * width + x;
    if (!'# .$@*+-'.includes(tile)) throw new Error('未知地图元素');
    if (tile === '-') return; // Void outside the warehouse.
    if (tile === '#') { board.walls.add(cell); return; }
    board.floors.add(cell);
    if ('.*+'.includes(tile)) board.goals.add(cell);
    if ('$*'.includes(tile)) board.boxes.push(cell);
    if ('@+'.includes(tile)) { board.player = cell; players += 1; }
  }));
  if (players !== 1 || !board.boxes.length || board.boxes.length !== board.goals.size) throw new Error('角色、箱子或目标数量无效');
  return board;
}

export function initialState(board: Board): GameState {
  return { player: board.player, boxes: [...board.boxes], moves: 0, pushes: 0, history: [], path: '' };
}
export const isSolved = (board: Board, state: Snapshot) => state.boxes.every(cell => board.goals.has(cell));

function neighbor(board: Board, cell: number, direction: Direction) {
  const x = cell % board.width;
  if ((direction === 'L' && x === 0) || (direction === 'R' && x === board.width - 1)) return -1;
  return cell + ({ U: -board.width, D: board.width, L: -1, R: 1 })[direction];
}

export function move(board: Board, state: GameState, direction: Direction): GameState {
  if (isSolved(board, state)) return state;
  const next = neighbor(board, state.player, direction);
  if (!board.floors.has(next)) return state;
  const boxIndex = state.boxes.indexOf(next);
  const boxes = [...state.boxes];
  if (boxIndex !== -1) {
    const beyond = neighbor(board, next, direction);
    if (!board.floors.has(beyond) || boxes.includes(beyond)) return state;
    boxes[boxIndex] = beyond;
  }
  const snapshot: Snapshot = { player: state.player, boxes: state.boxes, moves: state.moves, pushes: state.pushes };
  return { player: next, boxes, moves: state.moves + 1, pushes: state.pushes + Number(boxIndex !== -1), history: [...state.history, snapshot], path: state.path + direction };
}

export function undo(state: GameState): GameState {
  const previous = state.history[state.history.length - 1];
  return previous ? { ...previous, history: state.history.slice(0, -1), path: state.path.slice(0, -1) } : state;
}

// Replay validates persisted positions and counters rather than trusting a saved board.
export function replay(board: Board, path: string): GameState {
  let state = initialState(board);
  const history: Snapshot[] = [];
  for (const direction of path) {
    if (!'UDLR'.includes(direction)) throw new Error('存档方向无效');
    const next = move(board, state, direction as Direction);
    if (next === state) throw new Error('存档包含无效移动');
    history.push({ player: state.player, boxes: state.boxes, moves: state.moves, pushes: state.pushes });
    // Reconstruct long saves in linear time without copying all prior history.
    state = { ...next, history: [], path: '' };
  }
  return { ...state, history, path };
}
