import { useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Box, Check, CircleHelp, Grid2X2, RotateCcw, TriangleAlert, Undo2 } from 'lucide-react';
import { WarehouseBoard } from './Board';
import GameDialog from './Dialog';
import { isSolved, type Direction, type Level } from './engine';
import { boards, levels } from './levels';
import { encodeProgress, loadProgress, reduceProgress, sessionFor } from './storage';

const directionKeys: Record<string, Direction> = { ArrowUp: 'U', ArrowDown: 'D', ArrowLeft: 'L', ArrowRight: 'R', w: 'U', s: 'D', a: 'L', d: 'R' };
const controls = [
  { direction: 'U', label: '向上移动', Icon: ArrowUp },
  { direction: 'L', label: '向左移动', Icon: ArrowLeft },
  { direction: 'D', label: '向下移动', Icon: ArrowDown },
  { direction: 'R', label: '向右移动', Icon: ArrowRight },
] as const;
const instructions = [
  ['怎样通关', '把所有木箱推到菱形目标点。一次只能推一只箱子，不能拉回。'],
  ['怎样操作', '点击方向按钮，或聚焦棋盘后用方向键 / WASD 移动。Z 撤销；推入墙角时可撤销或重开。'],
  ['关于存档', '棋局和最佳成绩保存在当前浏览器，不跨设备同步。清除浏览器数据会移除存档。'],
];

export default function SokobanWorkspace({ saveKey, showBack }: { saveKey: string; showBack: boolean }) {
  const [loaded] = useState(() => loadProgress(saveKey));
  const [progress, dispatch] = useReducer(reduceProgress, loaded.progress);
  const [saveWarning, setSaveWarning] = useState('');
  const [panel, setPanel] = useState<'levels' | 'help' | 'warning' | null>(null);
  const [difficulty, setDifficulty] = useState<Level['difficulty']>('入门');
  const [levelPage, setLevelPage] = useState(0);
  const [helpPage, setHelpPage] = useState(0);
  const backgroundRef = useRef<HTMLDivElement>(null);
  const boardRef = useRef<HTMLElement>(null);
  const resumeAfterSelection = useRef(false);
  const levelIndex = levels.findIndex(level => level.id === progress.currentLevelId);
  const level = levels[levelIndex];
  const board = boards[level.id];
  const session = sessionFor(progress);
  const { state } = session;
  const solved = isSolved(board, state);
  const completed = levels.filter(item => progress.sessions[item.id]?.bestMoves !== undefined).length;
  const placed = state.boxes.filter(cell => board.goals.has(cell)).length;
  const warning = saveWarning || loaded.warning;
  const group = levels.filter(item => item.difficulty === difficulty);
  const pageCount = Math.ceil(group.length / 5);

  useEffect(() => {
    try { window.localStorage.setItem(saveKey, encodeProgress(progress)); setSaveWarning(''); }
    catch { setSaveWarning('进度无法保存到此浏览器。你仍然可以游玩，请暂时不要关闭页面。'); }
  }, [progress, saveKey]);

  useEffect(() => {
    if (!panel && resumeAfterSelection.current) {
      resumeAfterSelection.current = false;
      boardRef.current?.focus({ preventScroll: true });
    }
  }, [panel]);

  const focusBoard = () => boardRef.current?.focus({ preventScroll: true });
  const selectLevel = (id: string) => {
    dispatch({ type: 'select', id });
    if (panel) { resumeAfterSelection.current = true; setPanel(null); }
    else focusBoard();
  };
  const openLevels = () => {
    setDifficulty(level.difficulty);
    setLevelPage(Math.floor(levels.filter(item => item.difficulty === level.difficulty).findIndex(item => item.id === level.id) / 5));
    setPanel('levels');
  };
  const handleKey = (event: KeyboardEvent<HTMLElement>) => {
    if (panel || event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing || event.defaultPrevented) return;
    if ((event.target as HTMLElement).closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) return;
    const direction = directionKeys[event.key] ?? directionKeys[event.key.toLowerCase()];
    if (direction) { event.preventDefault(); dispatch({ type: 'move', direction }); }
    else if (event.key.toLowerCase() === 'z') { event.preventDefault(); dispatch({ type: 'undo' }); }
  };
  const nextLevel = levelIndex < levels.length - 1 ? levels[levelIndex + 1].id
    : levels.find(item => progress.sessions[item.id]?.bestMoves === undefined)?.id ?? levels[0].id;
  const nextLabel = levelIndex < levels.length - 1 ? '下一关' : completed === levels.length ? '从第一关再挑战' : '挑战未完成关卡';

  return <div className="sokoban-page">
    <div className="sokoban-content" ref={backgroundRef}>
      <header className="sokoban-header">
        {showBack && <Link className="sokoban-icon-button" aria-label="返回应用" title="返回应用" to="/apps"><ArrowLeft size={20} aria-hidden="true" /></Link>}
        <h1><Box size={22} aria-hidden="true" />推箱子</h1>
        <span className="sokoban-total">{completed} / 20 通关</span>
        <div className="sokoban-menu">
          {warning && <><span role="alert" className="sokoban-sr-only">{warning}</span><button className="sokoban-warning-button" aria-label="查看存档提示" title={warning} onClick={() => setPanel('warning')}><TriangleAlert size={19} aria-hidden="true" /></button></>}
          <button aria-label="选择关卡" onClick={openLevels}><Grid2X2 size={18} aria-hidden="true" /><span>选关</span></button>
          <button aria-label="玩法说明" title="玩法说明" onClick={() => { setHelpPage(0); setPanel('help'); }}><CircleHelp size={20} aria-hidden="true" /></button>
        </div>
      </header>

      <section className="sokoban-game" aria-label="推箱子游戏操作区" tabIndex={0} ref={boardRef} onKeyDown={handleKey}>
        <div className="sokoban-stage-info">
          <div className="sokoban-stage-heading"><h2 aria-current="step"><span>{String(levelIndex + 1).padStart(2, '0')}</span>{level.name}</h2><span className="sokoban-badge">{level.difficulty}</span></div>
          <div className="sokoban-stats" aria-label="当前成绩">
            <div><span>步数</span><strong data-testid="moves">{state.moves}</strong></div>
            <div><span>推动</span><strong data-testid="pushes">{state.pushes}</strong></div>
            <div><span>归位</span><strong>{placed}<small>/{state.boxes.length}</small></strong></div>
            <div><span>最佳</span><strong>{session.bestMoves ?? '—'}</strong></div>
          </div>
        </div>
        <div className="sokoban-board-frame" onPointerDown={focusBoard}>
          <WarehouseBoard board={board} state={state} />
          <div className="sokoban-result" role="status" aria-live="polite" aria-atomic="true">
            {solved && <div className="sokoban-win"><strong>{completed === levels.length ? '全部通关，仓库整理完毕！' : levelIndex === levels.length - 1 ? '最后一关完成！' : '所有木箱已归位！'}</strong><p>{state.moves} 步 · 推动 {state.pushes} 次</p><button className="sokoban-next" onClick={() => selectLevel(nextLevel)}>{nextLabel}<ArrowRight size={18} aria-hidden="true" /></button></div>}
          </div>
        </div>
        <div className="sokoban-controls">
          <button className="sokoban-undo sokoban-action" aria-label="撤销一步" title="撤销一步（Z）" disabled={!state.history.length} onClick={() => { dispatch({ type: 'undo' }); focusBoard(); }}><Undo2 size={22} aria-hidden="true" /><span>撤销</span></button>
          <div className="sokoban-dpad" aria-label="方向控制">{controls.map(({ direction, label, Icon }) => <button key={direction} className={`sokoban-direction-${direction}`} aria-label={label} disabled={solved} onClick={() => { dispatch({ type: 'move', direction }); focusBoard(); }}><Icon size={24} aria-hidden="true" /></button>)}</div>
          <button className="sokoban-restart sokoban-action" aria-label="重新开始" title="重新开始" onClick={() => { dispatch({ type: 'restart' }); focusBoard(); }}><RotateCcw size={22} aria-hidden="true" /><span>重开</span></button>
        </div>
      </section>
    </div>

    {panel && <GameDialog title={panel === 'levels' ? '选择关卡' : panel === 'help' ? instructions[helpPage][0] : '存档提示'} background={backgroundRef} onClose={() => setPanel(null)}
      extra={panel === 'levels' && <select aria-label="关卡难度" value={difficulty} onChange={event => { setDifficulty(event.target.value as Level['difficulty']); setLevelPage(0); }}>{(['入门', '进阶', '挑战'] as const).map(value => <option key={value}>{value}</option>)}</select>}>
      {panel === 'levels' ? <>
        <div className="sokoban-level-grid">{group.slice(levelPage * 5, levelPage * 5 + 5).map(item => {
          const index = levels.indexOf(item); const best = progress.sessions[item.id]?.bestMoves;
          return <button key={item.id} className={`sokoban-level ${best !== undefined ? 'is-complete' : ''}`}
            aria-label={`第 ${index + 1} 关 ${item.name}${best !== undefined ? '，已通关' : ''}`} aria-current={item.id === level.id ? 'step' : undefined}
            title={`${item.name}${best !== undefined ? ` · 最佳 ${best} 步` : ''}`} onClick={() => selectLevel(item.id)}>{String(index + 1).padStart(2, '0')}{best !== undefined && <Check size={12} aria-hidden="true" />}</button>;
        })}</div>
        <nav className="sokoban-dialog-pagination" aria-label="关卡分页"><button aria-label="上一页关卡" disabled={levelPage === 0} onClick={() => setLevelPage(value => value - 1)}><ArrowLeft size={18} aria-hidden="true" /></button><span>{completed}/20 通关 · {levelPage + 1}/{pageCount} 页</span><button aria-label="下一页关卡" disabled={levelPage + 1 >= pageCount} onClick={() => setLevelPage(value => value + 1)}><ArrowRight size={18} aria-hidden="true" /></button></nav>
      </> : panel === 'help' ? <>
        <p className="sokoban-dialog-copy">{instructions[helpPage][1]}</p>
        <nav className="sokoban-dialog-pagination" aria-label="说明分页"><button aria-label="上一页说明" disabled={helpPage === 0} onClick={() => setHelpPage(value => value - 1)}><ArrowLeft size={18} aria-hidden="true" /></button><span>{helpPage + 1} / {instructions.length}</span><button aria-label="下一页说明" disabled={helpPage === instructions.length - 1} onClick={() => setHelpPage(value => value + 1)}><ArrowRight size={18} aria-hidden="true" /></button></nav>
      </> : <p className="sokoban-dialog-copy">{warning}</p>}
    </GameDialog>}
  </div>;
}
