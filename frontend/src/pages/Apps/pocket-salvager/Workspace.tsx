import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { Link } from 'react-router-dom';
import { Anchor, ArrowLeft, ArrowUp, Box, CircleHelp, Heart, Pause, Play, Ship, Volume2, VolumeX, Waves, Wrench, Zap } from 'lucide-react';
import { capacity, createState, atDock, DOCK, GOAL, purchase, speed, upgradeCost, type GameState, type Upgrade } from './engine';
import type { Bridge } from './renderer';
import { GameAudio } from './audio';
import { readPreferences, savePreferences } from './storage';
import Dialog from './Dialog';

const upgrades: { kind: Upgrade; name: string; description: string }[] = [
  { kind: 'hold', name: '扩展船舱', description: '增加 2 格容量，能装下更多遗物。' },
  { kind: 'engine', name: '强化引擎', description: '提升基础航速，让满载返航更轻松。' },
  { kind: 'tool', name: '快速绞盘', description: '每次打捞缩短 0.25 秒，少等一会儿。' },
];
const score = (s: GameState) => Math.max(0, s.delivered * 100 + (s.phase === 'won' ? Math.floor(s.time) * 10 : 0) - s.wrecks * 50);
const formatTime = (time: number) => `${Math.floor(Math.ceil(time) / 60)}:${String(Math.ceil(time) % 60).padStart(2, '0')}`;

export default function Workspace({ saveKey, showBack }: { saveKey: string; showBack: boolean }) {
  const [bridge] = useState<Bridge>(() => ({ state: createState(), input: { x: 0, y: 0, boost: false }, publish: () => {} }));
  const [state, setState] = useState<GameState>(() => ({ ...bridge.state }));
  const [prefs, setPrefs] = useState(() => readPreferences(saveKey));
  const prefsRef = useRef(prefs);
  const [storageWarning, setStorageWarning] = useState(false);
  const [ready, setReady] = useState(false); const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [panel, setPanel] = useState<'pause' | 'help' | 'upgrade'>('pause');
  const [stick, setStick] = useState({ x: 0, y: 0 });
  const rootRef = useRef<HTMLDivElement>(null); const stageRef = useRef<HTMLDivElement>(null);
  const keys = useRef(new Set<string>()); const stickRef = useRef({ x: 0, y: 0 });
  const pointer = useRef<number | null>(null); const audio = useRef<GameAudio | null>(null);
  const lastEvent = useRef(0); const settled = useRef(false);

  useEffect(() => {
    audio.current = new GameAudio();
    bridge.publish = () => {
      const s = bridge.state;
      setState({ ...s, player: { ...s.player }, upgrades: { ...s.upgrades } });
      if (s.event !== lastEvent.current) {
        lastEvent.current = s.event;
        if (prefsRef.current.sound) audio.current?.play(s.sound);
      }
      if ((s.phase === 'won' || s.phase === 'lost') && !settled.current) {
        settled.current = true;
        const next = { ...prefsRef.current, best: Math.max(prefsRef.current.best, score(s)) };
        prefsRef.current = next; setPrefs(next); setStorageWarning(!savePreferences(saveKey, next));
      }
    };
    return () => { bridge.publish = () => {}; audio.current?.dispose(); };
  }, [bridge, saveKey]);

  useEffect(() => {
    let disposed = false; let destroy: (() => void) | undefined;
    setReady(false); setError('');
    void import('./renderer').then(({ mountGame }) => {
      if (disposed || !stageRef.current) return;
      destroy = mountGame(stageRef.current, bridge, () => { if (!disposed) setReady(true); });
    }).catch(() => { if (!disposed) setError('海面加载失败，请重试，或使用支持 Canvas / WebGL 的浏览器。'); });
    return () => { disposed = true; destroy?.(); };
  }, [bridge, attempt]);

  function updateInput() {
    const k = keys.current;
    bridge.input.x = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0) + stickRef.current.x;
    bridge.input.y = (k.has('s') || k.has('arrowdown') ? 1 : 0) - (k.has('w') || k.has('arrowup') ? 1 : 0) + stickRef.current.y;
  }
  function clearInput() {
    keys.current.clear(); stickRef.current = { x: 0, y: 0 }; pointer.current = null;
    bridge.input = { x: 0, y: 0, boost: false }; setStick({ x: 0, y: 0 });
  }
  function pause(next: typeof panel = 'pause') {
    if (bridge.state.phase !== 'playing') return;
    bridge.state.phase = 'paused'; clearInput(); setPanel(next); bridge.publish();
  }
  function resume() { bridge.state.phase = 'playing'; clearInput(); bridge.publish(); requestAnimationFrame(() => rootRef.current?.focus()); }
  function start() {
    if (!ready) return;
    bridge.state = createState(Date.now()); bridge.state.phase = 'playing';
    settled.current = false; lastEvent.current = 0; clearInput(); bridge.publish();
    if (prefsRef.current.sound) audio.current?.unlock();
    requestAnimationFrame(() => rootRef.current?.focus());
  }
  useEffect(() => {
    const stop = () => {
      keys.current.clear(); stickRef.current = { x: 0, y: 0 }; pointer.current = null;
      bridge.input = { x: 0, y: 0, boost: false }; setStick({ x: 0, y: 0 });
      if (bridge.state.phase === 'playing') { bridge.state.phase = 'paused'; setPanel('pause'); bridge.publish(); }
    };
    const hidden = () => { if (document.hidden) stop(); };
    const release = (e: KeyboardEvent) => {
      keys.current.delete(e.key.toLowerCase());
      const k = keys.current;
      bridge.input.x = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0) + stickRef.current.x;
      bridge.input.y = (k.has('s') || k.has('arrowdown') ? 1 : 0) - (k.has('w') || k.has('arrowup') ? 1 : 0) + stickRef.current.y;
    };
    window.addEventListener('blur', stop); window.addEventListener('keyup', release);
    document.addEventListener('visibilitychange', hidden);
    return () => { window.removeEventListener('blur', stop); window.removeEventListener('keyup', release); document.removeEventListener('visibilitychange', hidden); };
  }, [bridge]);

  function moveStick(e: PointerEvent<HTMLDivElement>) {
    if (pointer.current !== e.pointerId) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) / 35;
    const y = (e.clientY - rect.top - rect.height / 2) / 35;
    const length = Math.max(1, Math.hypot(x, y));
    stickRef.current = { x: x / length, y: y / length }; setStick(stickRef.current); updateInput();
  }
  function releaseStick(e: PointerEvent<HTMLDivElement>) {
    if (pointer.current !== e.pointerId) return;
    pointer.current = null; stickRef.current = { x: 0, y: 0 }; setStick({ x: 0, y: 0 }); updateInput();
  }
  function toggleSound() {
    const next = { ...prefsRef.current, sound: !prefsRef.current.sound };
    prefsRef.current = next; setPrefs(next); setStorageWarning(!savePreferences(saveKey, next));
    if (next.sound) audio.current?.unlock();
  }
  const playing = state.phase === 'playing';
  const dockAngle = Math.atan2(DOCK.y - state.player.y, DOCK.x - state.player.x) * 180 / Math.PI + 90;
  return <div className="salvager-page">
    <div className="salvager-workspace" ref={rootRef} tabIndex={0} aria-label="口袋打捞队游戏操作区"
      onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) { clearInput(); } }}
      onKeyDown={e => {
        if (e.key === 'Escape') { e.preventDefault(); pause(); return; }
        if (!playing || (e.target as HTMLElement).closest('button, a')) return;
        const key = e.key.toLowerCase();
        if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', ' '].includes(key)) {
          e.preventDefault();
          if (key === ' ') { if (!e.repeat) bridge.input.boost = true; }
          else { keys.current.add(key); updateInput(); }
        }
      }}>
      <div className="salvager-canvas" ref={stageRef} role="img" aria-label="俯视海域：西侧为港口，木箱是废料，金色菱形是遗物，漂浮木会损伤小船。" onPointerDown={() => rootRef.current?.focus()} />
      <div className={`salvager-storm ${state.time <= 30 ? 'is-near' : ''}`} aria-hidden="true" />
      <header className="salvager-header">
        <div className="salvager-brand">{showBack && <Link to="/apps" aria-label="返回应用"><ArrowLeft size={19} /></Link>}<Ship size={24} aria-hidden="true" /><div><h1>口袋打捞队</h1><span>POCKET SALVAGER</span></div></div>
        <div className="salvager-actions">
          <button aria-label={prefs.sound ? '关闭音效' : '开启音效'} aria-pressed={prefs.sound} onClick={toggleSound}>{prefs.sound ? <Volume2 size={19} /> : <VolumeX size={19} />}</button>
          <button aria-label="玩法说明" disabled={!playing} onClick={() => pause('help')}><CircleHelp size={19} /></button>
          <button aria-label="暂停游戏" disabled={!playing} onClick={() => pause()}><Pause size={19} /></button>
        </div>
      </header>
      <div className="salvager-hud">
        <div className="salvager-objective"><span><Anchor size={16} aria-hidden="true" />点亮归航灯塔</span><strong>{state.delivered}<small> / {GOAL}</small></strong><progress aria-label="灯塔修复进度" value={Math.min(GOAL, state.delivered)} max={GOAL} /></div>
        <div className={`salvager-clock ${state.time <= 30 ? 'is-urgent' : ''}`}><span><Waves size={16} aria-hidden="true" />{state.time <= 30 ? '暴风雨即将抵达' : '暴风雨倒计时'}</span><strong>{formatTime(state.time)}</strong></div>
      </div>
      <div className="salvager-notice" role="status" aria-live="polite">{playing && (state.respawn > 0 ? `救援船抵达还需 ${Math.ceil(state.respawn)} 秒` : state.noticeTime > 0 ? state.notice : state.cargo === capacity(state) ? '船舱已满，请返港卸货' : '')}</div>
      <div className="salvager-minimap" aria-label="海域地图和港口方向">
        <svg viewBox="0 0 160 110" role="img" aria-label="海图：圆点为船只，方块为西侧港口">
          <rect width="160" height="110" rx="8" fill="#154c58" />
          <path d="M0 30 Q32 55 0 86Z" fill="#aebc89" />
          {state.loot.filter(item => !item.collected).map(item => <circle key={item.id} cx={item.x / 10} cy={item.y / 10} r={item.relic ? 1.9 : 1} fill={item.relic ? '#f0c779' : '#8cb6ad'} />)}
          <rect x="19" y="51" width="8" height="8" rx="1" fill="#f6e6b9" />
          <circle cx={state.player.x / 10} cy={state.player.y / 10} r="3.5" fill="#fff" stroke="#154c58" />
        </svg>
        <span><ArrowUp size={16} style={{ transform: `rotate(${dockAngle}deg)` }} aria-hidden="true" />{atDock(state) ? '已在港口' : `港口 ${Math.round(Math.hypot(state.player.x - DOCK.x, state.player.y - DOCK.y))} 米`}</span>
      </div>
      <div className="salvager-bottom">
        <div className="salvager-status"><span aria-label={`船体耐久 ${state.hull} / 3`}>{[1, 2, 3].map(n => <Heart key={n} size={17} fill={n <= state.hull ? 'currentColor' : 'none'} opacity={n <= state.hull ? 1 : 0.35} aria-hidden="true" />)}</span><span><Box size={16} aria-hidden="true" />{state.cargo}/{capacity(state)} 格 · {state.cargoValue} 物资</span><span className="salvager-speed">航速 {Math.round(speed(state))} · 负重越多越慢</span></div>
        <button className="salvager-dock-button" disabled={!playing || !atDock(state) || state.respawn > 0} onClick={() => pause('upgrade')}><Wrench size={17} aria-hidden="true" />船坞<span>{state.credits} 物资</span></button>
      </div>
      <div className="salvager-touch-controls">
        <div className="salvager-stick" role="group" aria-label="拖动摇杆驾驶，也可使用键盘方向键" onPointerDown={e => {
          if (!playing || pointer.current !== null) return;
          rootRef.current?.focus(); pointer.current = e.pointerId; e.currentTarget.setPointerCapture(e.pointerId); moveStick(e);
        }} onPointerMove={moveStick} onPointerUp={releaseStick} onPointerCancel={releaseStick} onLostPointerCapture={releaseStick}>
          <span style={{ transform: `translate(${stick.x * 30}px, ${stick.y * 30}px)` }}><Ship size={22} aria-hidden="true" /></span>
        </div>
        <p className="salvager-key-hint"><kbd>W A S D</kbd> / 方向键驾驶<br /><kbd>空格</kbd> 加速 · 停船自动打捞</p>
        <button className="salvager-boost" aria-label="加速" disabled={!playing || state.cooldown > 0 || state.respawn > 0} onClick={() => { bridge.input.boost = true; rootRef.current?.focus(); }}><Zap size={23} aria-hidden="true" /><span>{state.cooldown > 0 ? `${Math.ceil(state.cooldown)} 秒` : '加速'}</span></button>
      </div>
    </div>
    {state.phase !== 'playing' && <Dialog background={rootRef} title={state.phase === 'ready' ? '风暴之前，再出一趟海。' : state.phase === 'won' ? '灯塔亮了，欢迎归航。' : state.phase === 'lost' ? '风暴来了，下次再出发。' : panel === 'upgrade' ? '归航船坞' : panel === 'help' ? '船长的航行手册' : '在这里，歇一会儿。'} onEscape={state.phase === 'paused' ? resume : undefined}>
      {state.phase === 'ready' ? <>
        <div className="salvager-intro-mark" aria-hidden="true"><Ship size={42} /><Waves size={70} /></div>
        <p className="salvager-lead">驾驶小船穿过青绿海域，把散落的物资带回家。<br />三分钟，三十点物资，一座等待亮起的灯塔。</p>
        <div className="salvager-rule-strip"><span><b>01</b> 停船打捞</span><span><b>02</b> 满载减速</span><span><b>03</b> 返港入库</span></div>
        <p className="salvager-copy">木箱占 1 格，价值 1 点；金色遗物占 2 格，价值 5 点。躲开漂浮木，受损后可返港免费修复。</p>
        <p className="salvager-copy">电脑使用 WASD / 方向键和空格；手机使用摇杆和加速按钮。离开窗口会自动暂停。</p>
        {error ? <p role="alert" className="salvager-error">{error}<button onClick={() => setAttempt(n => n + 1)}>重新加载海面</button></p> : <button className="salvager-primary" disabled={!ready} onClick={start}><Play size={18} aria-hidden="true" />{ready ? '准备好了，出港' : '正在铺开海图…'}</button>}
        <p className="salvager-footnote">本机最高分 {prefs.best.toLocaleString()} · 无需下载额外素材</p>
        {showBack && <Link className="salvager-return" to="/apps">返回应用</Link>}
      </> : state.phase === 'won' || state.phase === 'lost' ? <>
        <p className="salvager-lead">{state.phase === 'won' ? '你送回的每一块碎片，都成了照亮海面的光。' : '保住的物资都是收获。试试少装一点，早点返航。'}</p>
        <div className="salvager-results"><div><strong>{score(state)}</strong><span>本局得分</span></div><div><strong>{state.delivered}</strong><span>送回物资</span></div><div><strong>{state.trips}</strong><span>成功返航</span></div></div>
        <p className="salvager-copy">损毁 {state.wrecks} 次 · 剩余 {formatTime(state.time)} · 本机最高分 {prefs.best.toLocaleString()}</p>
        <p className="salvager-footnote">每点送达物资 100 分，成功后每剩余秒加 10 分，每次损毁扣 50 分。</p>
        <button className="salvager-primary" onClick={start}><Ship size={19} aria-hidden="true" />再出一趟海</button>
        {showBack && <Link className="salvager-return" to="/apps">返回应用</Link>}
      </> : panel === 'upgrade' ? <>
        <p className="salvager-copy">可用物资 <b>{state.credits}</b> · 每项最多升级两次。消费不会减少灯塔修复进度，改装期间计时暂停。</p>
        <div className="salvager-upgrades">{upgrades.map(u => <button key={u.kind} disabled={state.upgrades[u.kind] >= 2 || state.credits < upgradeCost(state, u.kind)} onClick={() => { purchase(bridge.state, u.kind); bridge.publish(); }}><span><b>{u.name} · {state.upgrades[u.kind]}/2</b><small>{u.description}</small></span><strong>{state.upgrades[u.kind] >= 2 ? '已满级' : `${upgradeCost(state, u.kind)} 物资`}</strong></button>)}</div>
        <button className="salvager-primary" onClick={resume}>完成改装，继续航行</button>
      </> : <>
        <p className="salvager-lead">{panel === 'pause' ? '航行和倒计时已暂停，海上的物资等你回来。' : '记住：船上的收获，送回港口才算数。'}</p>
        <ul className="salvager-instructions"><li>WASD / 方向键或摇杆驾驶；空格或加速按钮冲刺，冷却 5 秒。</li><li>靠近木箱或金色遗物后松开方向，等待圆环完成打捞。</li><li>向西侧港口返航，自动卸货并修复船体；小海图标出你的位置。</li><li>三次撞击会损毁小船，丢失随船货物，5 秒后获救。已入库物资和升级保留。</li><li>在 3 分钟内累计送回 30 点物资即可获胜。船坞可以购买升级。</li></ul>
        <button className="salvager-primary" onClick={resume}><Play size={18} aria-hidden="true" />继续航行</button>
        <button className="salvager-secondary" onClick={start}>放弃本局，重新出港</button>
      </>}
      {storageWarning && <p className="salvager-error" role="status">浏览器未允许保存记录，本次仍可正常游玩。</p>}
    </Dialog>}
  </div>;
}
