import { describe, expect, it } from 'vitest';
import { atDock, capacity, createState, damage, DOCK, hazards, purchase, speed, step, type GameState } from '../engine';

const idle = { x: 0, y: 0, boost: false };
function game() { const s = createState(); s.phase = 'playing'; return s; }
function tick(s: GameState, seconds: number, input = idle) { for (let i = 0; i < Math.ceil(seconds * 60); i++) step(s, input, 1 / 60); }

describe('Pocket Salvager rules', () => {
  it('generates repeatable maps with sufficient cargo and a safe first pickup', () => {
    expect(createState(17).loot).toEqual(createState(17).loot);
    expect(createState(18).loot).not.toEqual(createState(17).loot);
    const s = game(); expect(atDock(s)).toBe(true);
    expect(s.loot.reduce((sum, item) => sum + (item.relic ? 5 : 1), 0)).toBeGreaterThan(60);
  });
  it('requires stopping to salvage, then banks exactly once on docking', () => {
    const s = game(); s.player = { ...s.loot[0] };
    tick(s, 0.1, { x: 0.2, y: 0, boost: false }); expect(s.cargo).toBe(0);
    tick(s, 1.2); expect(s.cargo).toBe(1); expect(s.delivered).toBe(0);
    s.player = { x: DOCK.x, y: DOCK.y }; s.hull = 1;
    tick(s, 0.1); expect(s.cargo).toBe(0); expect(s.credits).toBe(1); expect(s.delivered).toBe(1); expect(s.hull).toBe(3);
    tick(s, 1); expect(s.delivered).toBe(1); expect(s.trips).toBe(1);
  });
  it('values relics at five points but refuses cargo that will not fit', () => {
    const s = game(); const item = s.loot.find(l => l.relic)!;
    s.loot = [item]; s.player = { ...item }; s.invincible = 10; s.cargo = 5;
    tick(s, 1.2); expect(item.collected).toBe(false);
    s.cargo = 4; tick(s, 1.2); expect(item.collected).toBe(true); expect(s.cargo).toBe(6); expect(s.cargoValue).toBe(5);
  });
  it('normalizes diagonal movement, reduces laden speed and respects bounds', () => {
    const straight = game(); const diagonal = game();
    tick(straight, 0.1, { x: 1, y: 0, boost: false }); tick(diagonal, 0.1, { x: 1, y: 1, boost: false });
    expect(Math.hypot(diagonal.player.x - DOCK.x, diagonal.player.y - DOCK.y)).toBeCloseTo(straight.player.x - DOCK.x);
    diagonal.cargo = 6; expect(speed(diagonal)).toBeLessThan(speed(straight));
    straight.player = { x: 1560, y: 45 }; tick(straight, 1, { x: 1, y: -1, boost: false });
    expect(straight.player).toEqual({ x: 1565, y: 40 });
  });
  it('gates boosts on movement and cooldown', () => {
    const s = game(); step(s, { ...idle, boost: true }, 1 / 60); expect(s.cooldown).toBe(0);
    step(s, { x: 1, y: 0, boost: true }, 1 / 60); expect(s.cooldown).toBe(5);
    tick(s, 1); const before = s.cooldown;
    step(s, { x: 1, y: 0, boost: true }, 1 / 60); expect(s.boostTime).toBe(0); expect(s.cooldown).toBeLessThan(before);
  });
  it('spends credits without reducing delivered progress; limits purchases to the dock', () => {
    const s = game(); s.delivered = 20; s.credits = 20;
    expect(purchase(s, 'hold')).toBe(true); expect(capacity(s)).toBe(8); expect(s.credits).toBe(16); expect(s.delivered).toBe(20);
    expect(purchase(s, 'hold')).toBe(true); expect(capacity(s)).toBe(10); expect(purchase(s, 'hold')).toBe(false);
    s.player.x = 900; expect(purchase(s, 'engine')).toBe(false);
    s.player.x = DOCK.x; s.credits = 0; expect(purchase(s, 'tool')).toBe(false);
    s.credits = 10; s.phase = 'won'; expect(purchase(s, 'tool')).toBe(false);
  });
  it('applies collision protection and five-second rescues without losing banked progress', () => {
    const s = game(); s.player = hazards(s)[0]; s.cargo = 6; s.cargoValue = 15; s.credits = 8; s.delivered = 8; s.upgrades.engine = 1;
    tick(s, 1 / 60); expect(s.hull).toBe(2);
    damage(s); expect(s.hull).toBe(2);
    s.invincible = 0; damage(s); s.invincible = 0; damage(s);
    expect(s.respawn).toBe(5); expect(s.cargoValue).toBe(0); expect(s.wrecks).toBe(1);
    tick(s, 4.9); expect(s.respawn).toBeGreaterThan(0);
    tick(s, 0.2); expect(atDock(s)).toBe(true); expect(s.hull).toBe(3);
    expect(s.credits).toBe(8); expect(s.delivered).toBe(8); expect(s.upgrades.engine).toBe(1);
  });
  it('freezes paused state and settles time-zero before a last-second unload', () => {
    const s = game(); s.phase = 'paused'; const before = structuredClone(s);
    tick(s, 10); expect(s).toEqual(before);
    s.phase = 'playing'; s.time = 1 / 120; s.cargo = 6; s.cargoValue = 30;
    tick(s, 1 / 60); expect(s.phase).toBe('lost'); expect(s.cargoValue).toBe(0); expect(s.delivered).toBe(0);
  });
  it('wins on delivery and cannot keep scoring after the result', () => {
    const s = game(); s.delivered = 28; s.cargoValue = 5; s.cargo = 2;
    tick(s, 1 / 60); expect(s.phase).toBe('won'); expect(s.delivered).toBe(33);
    const before = structuredClone(s); tick(s, 5); expect(s).toEqual(before);
  });
  it('supports a complete winning voyage using real movement and salvage steps', () => {
    const s = game();
    for (let frame = 0; frame < 180 * 60 && s.phase === 'playing'; frame++) {
      const target = s.cargo >= 6 ? DOCK : s.loot.filter(l => l.relic && !l.collected)
        .sort((a, b) => Math.hypot(a.x - s.player.x, a.y - s.player.y) - Math.hypot(b.x - s.player.x, b.y - s.player.y))[0];
      const dx = target.x - s.player.x; const dy = target.y - s.player.y; const length = Math.hypot(dx, dy);
      const moving = length > (target === DOCK ? 25 : 30);
      step(s, { x: moving ? dx / length : 0, y: moving ? dy / length : 0, boost: false }, 1 / 60);
    }
    expect(s.phase).toBe('won'); expect(s.trips).toBeGreaterThanOrEqual(2);
    expect(s.delivered).toBeGreaterThanOrEqual(30);
  });
});
