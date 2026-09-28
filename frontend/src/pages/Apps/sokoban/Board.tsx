import type { Board as BoardModel, GameState } from './engine';

// Original vector tiles: no image downloads, fonts or external sprite sheets.
export function WarehouseBoard({ board, state }: { board: BoardModel; state: GameState }) {
  const boxes = new Set(state.boxes);
  const cellSize = 48;
  return <svg className="sokoban-board" preserveAspectRatio="xMidYMid meet" viewBox={`0 0 ${board.width * cellSize} ${board.height * cellSize}`}
    role="img" aria-label={`仓库棋盘，${board.width} 列 ${board.height} 行。搬运工在第 ${Math.floor(state.player / board.width) + 1} 行，第 ${state.player % board.width + 1} 列。${state.boxes.filter(cell => board.goals.has(cell)).length} 个箱子已归位，共 ${state.boxes.length} 个。`}>
    {Array.from({ length: board.width * board.height }, (_, cell) => {
      const wall = board.walls.has(cell);
      const goal = board.goals.has(cell);
      const box = boxes.has(cell);
      if (!wall && !board.floors.has(cell)) return null;
      return <g key={cell} transform={`translate(${cell % board.width * cellSize},${Math.floor(cell / board.width) * cellSize})`}>
        {wall ? <g className="sokoban-tile-wall">
          <rect width="48" height="48" fill="#414a49" />
          <path d="M1 2h46v19H1zM1 25h21v20H1zM26 25h21v20H26z" fill="#66736c" />
          <path d="M2 3h44M2 26h19m6 0h19" stroke="#879187" strokeWidth="2" />
          <path d="M1 22h46M1 46h46" stroke="#343e3b" strokeWidth="2" />
        </g> : <g>
          <rect width="48" height="48" fill={cell % 2 ? '#e4dac5' : '#e9dfcc'} />
          <path d="M0 47h48M47 0v48" stroke="#d0c4ae" />
          <path d="M7 9h5m24 29h5" stroke="#d6c9b2" strokeWidth="2" />
        </g>}
        {goal && !box && <g><circle cx="24" cy="24" r="13" fill="#be773c" opacity=".16" />
          <path d="M24 14l10 10-10 10-10-10z" fill="none" stroke="#955021" strokeWidth="2.5" />
          <circle cx="24" cy="24" r="3" fill="#955021" /></g>}
        {box && <g>
          <rect x="5" y="7" width="39" height="39" rx="3" fill="#433722" opacity=".25" />
          <rect x="4" y="3" width="39" height="39" rx="3" fill={goal ? '#477c59' : '#b9783f'} stroke={goal ? '#2e583c' : '#79491f'} strokeWidth="2" />
          <rect x="9" y="8" width="29" height="29" rx="1" fill={goal ? '#60966a' : '#dba060'} stroke={goal ? '#365f41' : '#9d602e'} strokeWidth="2" />
          <path d="M10 10l26 25M36 10L11 35" stroke={goal ? '#9ebf8c' : '#f3c185'} strokeWidth="5" />
          <path d="M10 11l25 25M36 12L12 35" stroke={goal ? '#355e40' : '#965b28'} strokeWidth="1" />
          {[10, 37].flatMap(x => [9, 36].map(y => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.5" fill="#493c29" />))}
          {goal && <g><circle cx="24" cy="23" r="10" fill="#264f35" /><path d="M18 23l4 4 8-9" fill="none" stroke="#f3f6dc" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></g>}
        </g>}
        {state.player === cell && <g>
          <ellipse cx="25" cy="41" rx="15" ry="4" fill="#463e32" opacity=".25" />
          <path d="M17 33v8m14-8v8" stroke="#263f49" strokeWidth="7" strokeLinecap="round" />
          <rect x="12" y="21" width="24" height="15" rx="7" fill="#387b8e" stroke="#225363" strokeWidth="2" />
          <path d="M16 23v9h16v-9" fill="#66a3ab" />
          <circle cx="24" cy="16" r="10" fill="#edbd85" stroke="#aa784b" strokeWidth="1.5" />
          <path d="M13 14c0-15 22-15 22 0z" fill="#e4a33d" stroke="#986626" strokeWidth="1.5" />
          <path d="M11 14h26" stroke="#f4c666" strokeWidth="4" strokeLinecap="round" />
          <path d="M23 4v7" stroke="#ffe0a0" strokeWidth="3" />
          <circle cx="20" cy="18" r="1.2" fill="#4d372a" /><circle cx="28" cy="18" r="1.2" fill="#4d372a" />
        </g>}
      </g>;
    })}
  </svg>;
}
