/** Pure, fixed-step simulation. Phaser is a disposable view of this state. */
export const WORLD = { width: 1600, height: 1100 };
export const DOCK = { x: 230, y: 550, radius: 78 };
export const GOAL = 30;
export const DURATION = 180;
export type Phase = 'ready' | 'playing' | 'paused' | 'won' | 'lost';
export type Upgrade = 'hold' | 'engine' | 'tool';
export type Point = { x: number; y: number };
export interface Loot extends Point { id: number; relic: boolean; collected: boolean }
export interface Input { x: number; y: number; boost: boolean }
export interface GameState {
  phase: Phase; time: number; player: Point; angle: number; hull: number;
  cargo: number; cargoValue: number; delivered: number; credits: number;
  upgrades: Record<Upgrade, number>; cooldown: number; boostTime: number;
  invincible: number; respawn: number; wrecks: number; trips: number;
  loot: Loot[]; salvageId: number | null; salvageProgress: number;
  notice: string; noticeTime: number; event: number; sound: 'pickup' | 'bank' | 'hit' | 'win';
}
export const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
export const capacity = (s: GameState) => 6 + s.upgrades.hold * 2;
export const speed = (s: GameState) => (210 + s.upgrades.engine * 28) * (1 - Math.min(0.48, s.cargo * 0.055));
export const atDock = (s: GameState) => distance(s.player, DOCK) < DOCK.radius;
export const upgradeCost = (s: GameState, kind: Upgrade) => 4 + s.upgrades[kind] * 3;

export function createState(seed = 42): GameState {
  let n = seed >>> 0;
  const random = () => { n = (Math.imul(n, 1664525) + 1013904223) >>> 0; return n / 4294967296; };
  const loot: Loot[] = Array.from({ length: 42 }, (_, id) => ({
    id, x: 390 + (id % 7) * 175 + random() * 55,
    y: 100 + Math.floor(id / 7) * 170 + random() * 40,
    relic: id % 7 >= 3, collected: false,
  }));
  // A first pickup in sight of the harbor teaches the return loop immediately.
  loot[0] = { id: 0, x: 395, y: 550, relic: false, collected: false };
  return {
    phase: 'ready', time: DURATION, player: { x: DOCK.x, y: DOCK.y }, angle: 0,
    hull: 3, cargo: 0, cargoValue: 0, delivered: 0, credits: 0,
    upgrades: { hold: 0, engine: 0, tool: 0 }, cooldown: 0, boostTime: 0,
    invincible: 0, respawn: 0, wrecks: 0, trips: 0, loot,
    salvageId: null, salvageProgress: 0, notice: '向东出港，靠近木箱并停船打捞', noticeTime: 6,
    event: 0, sound: 'pickup',
  };
}

export function hazards(s: GameState): Point[] {
  const t = DURATION - s.time;
  return Array.from({ length: 7 }, (_, i) => ({
    x: 590 + (i % 3) * 335 + Math.sin(t * 0.32 + i * 2) * 110,
    y: 180 + (i % 4) * 225 + Math.cos(t * 0.24 + i) * 95,
  }));
}

function announce(s: GameState, notice: string, sound?: GameState['sound']) {
  s.notice = notice; s.noticeTime = 3.5;
  if (sound) { s.event++; s.sound = sound; }
}

export function purchase(s: GameState, kind: Upgrade): boolean {
  const cost = upgradeCost(s, kind);
  if (!['playing', 'paused'].includes(s.phase) || !atDock(s) || s.respawn > 0 || s.upgrades[kind] >= 2 || s.credits < cost) return false;
  s.credits -= cost; s.upgrades[kind]++;
  announce(s, '改装完成，下一趟走得更远！', 'bank');
  return true;
}

export function damage(s: GameState) {
  if (s.phase !== 'playing' || s.invincible > 0 || s.respawn > 0 || atDock(s)) return;
  s.hull--; s.invincible = 2;
  announce(s, '撞上漂浮木！暂时获得 2 秒保护', 'hit');
  if (s.hull === 0) {
    s.cargo = 0; s.cargoValue = 0; s.respawn = 5; s.wrecks++;
    s.boostTime = 0; s.salvageId = null; s.salvageProgress = 0;
    announce(s, '小船损毁，救援中… 已存物资和升级保留', 'hit');
  }
}

/** Call with 1/60 second steps; deadlines settle before any action at time zero. */
export function step(s: GameState, input: Input, dt: number) {
  if (s.phase !== 'playing' || dt <= 0) return;
  s.time = Math.max(0, s.time - dt);
  if (s.time <= 0) {
    s.phase = 'lost'; s.cargo = 0; s.cargoValue = 0;
    announce(s, '暴风雨抵达，未送回的物资已经丢失'); return;
  }
  s.noticeTime = Math.max(0, s.noticeTime - dt);
  s.cooldown = Math.max(0, s.cooldown - dt);
  s.boostTime = Math.max(0, s.boostTime - dt);
  s.invincible = Math.max(0, s.invincible - dt);
  if (s.respawn > 0) {
    s.respawn = Math.max(0, s.respawn - dt);
    if (!s.respawn) {
      s.player = { x: DOCK.x, y: DOCK.y }; s.hull = 3; s.invincible = 3;
      announce(s, '救援完成，再次出港吧');
    }
    return;
  }
  const length = Math.hypot(input.x, input.y);
  if (input.boost && s.cooldown === 0 && length > 0) { s.boostTime = 0.7; s.cooldown = 5; }
  if (length > 0.05) {
    const velocity = speed(s) * (s.boostTime > 0 ? 2.4 : 1);
    const norm = Math.max(1, length);
    s.player.x = Math.max(195, Math.min(WORLD.width - 35, s.player.x + input.x / norm * velocity * dt));
    s.player.y = Math.max(40, Math.min(WORLD.height - 40, s.player.y + input.y / norm * velocity * dt));
    s.angle = Math.atan2(input.y, input.x);
  }
  if (atDock(s)) {
    s.hull = 3;
    if (s.cargo) {
      const amount = s.cargoValue;
      s.delivered += amount; s.credits += amount; s.cargo = 0; s.cargoValue = 0; s.trips++;
      announce(s, `成功入港 +${amount} 物资 · 可打开船坞改装`, 'bank');
      if (s.delivered >= GOAL) { s.phase = 'won'; announce(s, '灯塔重新亮起，谢谢你，船长！', 'win'); return; }
    }
  }
  const target = s.loot.find(item => !item.collected && distance(item, s.player) < 52 && s.cargo + (item.relic ? 2 : 1) <= capacity(s));
  if (target && length < 0.12) {
    if (s.salvageId !== target.id) { s.salvageId = target.id; s.salvageProgress = 0; }
    s.salvageProgress += dt / (1.05 - s.upgrades.tool * 0.25);
    if (s.salvageProgress >= 1) {
      target.collected = true; s.cargo += target.relic ? 2 : 1; s.cargoValue += target.relic ? 5 : 1;
      s.salvageId = null; s.salvageProgress = 0;
      announce(s, s.cargo === capacity(s) ? '船舱已满，跟随港口指引返航' : target.relic ? '发现旧世遗物！价值 5 点物资' : '废料已装船 · 返回港口才能计入修复', 'pickup');
    }
  } else { s.salvageId = null; s.salvageProgress = 0; }
  if (hazards(s).some(hazard => distance(hazard, s.player) < 37)) damage(s);
}
