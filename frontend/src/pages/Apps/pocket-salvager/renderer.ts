import Phaser from 'phaser';
import { DOCK, WORLD, hazards, step, type GameState, type Input } from './engine';

export interface Bridge { state: GameState; input: Input; publish: () => void }

export function mountGame(parent: HTMLElement, bridge: Bridge, ready: () => void) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  class SeaScene extends Phaser.Scene {
    private ink!: Phaser.GameObjects.Graphics;
    private boat!: Phaser.GameObjects.Container;
    private accumulator = 0;
    private hudElapsed = 0;
    private event = -1;
    create() {
      const sea = this.add.graphics();
      sea.fillStyle(0x246f78).fillRect(0, 0, WORLD.width, WORLD.height);
      // Shallow reefs, chart lines and wave marks are original procedural art.
      for (let i = 0; i < 28; i++) {
        sea.fillStyle(i % 2 ? 0x338c8c : 0x398f91, 0.22);
        sea.fillEllipse((i * 373) % WORLD.width, (i * 197) % WORLD.height, 170 + i % 4 * 50, 100);
      }
      sea.lineStyle(1, 0xbce9da, 0.07);
      for (let x = 0; x < WORLD.width; x += 100) sea.lineBetween(x, 0, x, WORLD.height);
      for (let y = 0; y < WORLD.height; y += 100) sea.lineBetween(0, y, WORLD.width, y);
      sea.lineStyle(2, 0xbce9da, 0.17);
      for (let i = 0; i < 260; i++) {
        const x = (i * 149) % WORLD.width; const y = (i * 283) % WORLD.height;
        sea.beginPath().moveTo(x, y).lineTo(x + 8, y + 3).lineTo(x + 17, y).strokePath();
      }
      sea.fillStyle(0x75b7a1, 0.25).fillEllipse(62, 550, 365, 430);
      sea.fillStyle(0xb4d0a0).fillEllipse(50, 550, 280, 330);
      sea.fillStyle(0xe1d1a0).fillEllipse(45, 540, 240, 290);
      sea.fillStyle(0x6f9270).fillEllipse(10, 565, 200, 225);
      sea.fillStyle(0x174a4b, 0.3).fillRoundedRect(110, 538, 142, 50, 6);
      sea.fillStyle(0xb78b60).fillRoundedRect(108, 522, 145, 45, 5);
      sea.lineStyle(2, 0x705c46);
      for (let x = 115; x < 250; x += 17) sea.lineBetween(x, 525, x, 565);
      for (const y of [520, 570]) for (const x of [115, 240]) sea.fillStyle(0xefd5a1).fillCircle(x, y, 6);
      // Lighthouse and conifers above the west harbor.
      sea.fillStyle(0x244e4c, 0.35).fillEllipse(94, 466, 90, 36);
      sea.fillStyle(0xf4edce).fillTriangle(70, 465, 106, 465, 89, 360).fillRect(77, 394, 25, 67);
      sea.fillStyle(0xd27d59).fillRect(77, 421, 25, 13).fillRect(71, 387, 37, 10);
      sea.fillStyle(0x294e52).fillRect(78, 368, 24, 19);
      sea.fillStyle(0xe8b96a).fillTriangle(68, 369, 111, 369, 90, 350);
      for (let i = 0; i < 6; i++) {
        const x = 35 + i % 2 * 70; const y = 640 + Math.floor(i / 2) * 60;
        sea.fillStyle(0x285b52).fillTriangle(x - 21, y, x + 21, y, x, y - 60);
        sea.fillStyle(0x39725c).fillTriangle(x - 16, y - 18, x + 16, y - 18, x, y - 65);
      }
      const textStyle = { fontFamily: '"Microsoft YaHei", sans-serif', fontSize: '15px', color: '#d8ece0' };
      this.add.text(165, 628, '归 航 港', textStyle).setAlpha(0.9);
      this.add.text(960, 65, '旧 世 沉 船 区', { ...textStyle, fontSize: '21px' }).setAlpha(0.45);
      this.ink = this.add.graphics();
      const hull = this.add.graphics();
      hull.fillStyle(0x103f48, 0.45).fillEllipse(0, 7, 66, 34);
      hull.fillStyle(0x985740).fillPoints([{ x: -29, y: -17 }, { x: 15, y: -17 }, { x: 36, y: 0 }, { x: 15, y: 17 }, { x: -29, y: 17 }], true);
      hull.fillStyle(0xf3ddb0).fillPoints([{ x: -26, y: -13 }, { x: 14, y: -13 }, { x: 29, y: 0 }, { x: 14, y: 13 }, { x: -26, y: 13 }], true);
      hull.fillStyle(0xc67a53).fillRoundedRect(-22, -10, 19, 20, 3);
      hull.fillStyle(0x42686c).fillRoundedRect(-1, -10, 17, 20, 3);
      hull.fillStyle(0xc5e7df).fillRect(2, -7, 10, 14);
      hull.fillStyle(0xf2bf69).fillCircle(-13, 0, 5);
      this.boat = this.add.container(DOCK.x, DOCK.y, [hull]);
      this.cameras.main.setBounds(0, 0, WORLD.width, WORLD.height);
      this.resize(); this.scale.on('resize', this.resize, this);
      this.events.once('shutdown', () => this.scale.off('resize', this.resize, this));
      ready();
    }
    resize() {
      this.cameras.main.setZoom(this.scale.width < 600 ? 0.72 : 0.95);
    }
    update(_time: number, delta: number) {
      const s = bridge.state;
      if (s.phase === 'playing') {
        this.accumulator += Math.min(delta / 1000, 0.25);
        while (this.accumulator >= 1 / 60) { step(s, bridge.input, 1 / 60); bridge.input.boost = false; this.accumulator -= 1 / 60; }
      } else this.accumulator = 0;
      this.hudElapsed += delta;
      if (this.hudElapsed > 100 || this.event !== s.event) { this.hudElapsed = 0; this.event = s.event; bridge.publish(); }
      this.draw(s);
    }
    draw(s: GameState) {
      const g = this.ink; g.clear();
      const t = reducedMotion ? 0 : 180 - s.time;
      g.lineStyle(2, 0xcce8bd, 0.38).strokeCircle(DOCK.x, DOCK.y, DOCK.radius);
      if (s.phase === 'won') {
        g.fillStyle(0xffe6a1, 0.18).fillTriangle(90, 380, 1200, 120, 1200, 680);
        g.fillStyle(0xffecb1).fillCircle(90, 378, 10);
      }
      for (const item of s.loot) {
        if (item.collected) continue;
        const y = item.y + Math.sin(t * 2 + item.id) * 2;
        g.fillStyle(0x123e49, 0.25).fillEllipse(item.x, y + 13, 38, 16);
        if (item.relic) {
          g.lineStyle(1, 0xf6cc7b, 0.4).strokeCircle(item.x, y, 27);
          g.fillStyle(0xf3c778).fillTriangle(item.x, y - 16, item.x - 13, y, item.x + 13, y);
          g.fillStyle(0xc79551).fillTriangle(item.x - 13, y, item.x + 13, y, item.x, y + 16);
          g.lineStyle(2, 0xffebba).lineBetween(item.x, y - 10, item.x - 6, y);
        } else {
          g.fillStyle(0xbb8757).fillRoundedRect(item.x - 13, y - 13, 26, 26, 3);
          g.lineStyle(2, 0xe4c28b).strokeRect(item.x - 10, y - 10, 20, 20).lineBetween(item.x - 10, y - 10, item.x + 10, y + 10);
        }
        if (s.salvageId === item.id) {
          g.lineStyle(4, 0xffedb7).beginPath().arc(item.x, y, 33, -Math.PI / 2, -Math.PI / 2 + s.salvageProgress * Math.PI * 2, false).strokePath();
        }
      }
      for (const h of hazards(s)) {
        g.lineStyle(2, 0xf3ba98, 0.3).strokeCircle(h.x, h.y, 40);
        g.fillStyle(0x184951, 0.3).fillEllipse(h.x, h.y + 10, 73, 27);
        g.fillStyle(0x795a47).fillRoundedRect(h.x - 30, h.y - 10, 60, 20, 8);
        g.lineStyle(2, 0xc3906a).lineBetween(h.x - 22, h.y - 3, h.x + 22, h.y - 3);
        g.fillStyle(0xe0b482).fillCircle(h.x + 26, h.y, 9);
        g.lineStyle(2, 0x98704e).strokeCircle(h.x + 26, h.y, 5);
      }
      if (!reducedMotion && Math.hypot(bridge.input.x, bridge.input.y) > 0 && s.phase === 'playing' && !s.respawn) {
        for (let i = 0; i < 4; i++) {
          const offset = 35 + i * 13 + (t * 22 % 13);
          g.fillStyle(0xd7ede0, 0.26 - i * 0.05).fillCircle(s.player.x - Math.cos(s.angle) * offset, s.player.y - Math.sin(s.angle) * offset, 10 - i);
        }
      }
      this.boat.setPosition(s.player.x, s.player.y).setRotation(s.angle).setVisible(s.respawn === 0);
      this.boat.setAlpha(s.invincible > 0 ? 0.65 : 1);
      if (s.invincible > 0) g.lineStyle(2, 0xf7e6b9, 0.65).strokeCircle(s.player.x, s.player.y, 41);
      this.cameras.main.centerOn(s.player.x + 80, s.player.y);
      // The storm tint rises with urgency without obscuring navigational cues.
      this.cameras.main.setBackgroundColor('#246f78');
    }
  }
  const game = new Phaser.Game({
    type: Phaser.AUTO, parent, backgroundColor: '#246f78', scene: SeaScene,
    scale: { mode: Phaser.Scale.RESIZE, width: parent.clientWidth, height: parent.clientHeight },
    render: { antialias: true, roundPixels: true },
    input: { keyboard: false, mouse: false, touch: false },
    audio: { noAudio: true }, banner: false,
  });
  const observer = new ResizeObserver(() => {
    if (parent.clientWidth > 0 && parent.clientHeight > 0) game.scale.resize(parent.clientWidth, parent.clientHeight);
  });
  observer.observe(parent);
  return () => { observer.disconnect(); game.destroy(true); };
}
