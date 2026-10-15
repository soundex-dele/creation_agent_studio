/** Short, locally synthesized effects; no network assets or autoplay. */
export class GameAudio {
  private context: AudioContext | null = null;
  unlock() {
    try { this.context ??= new AudioContext(); void this.context.resume().catch(() => {}); } catch { /* Audio is optional. */ }
  }
  play(kind: 'pickup' | 'bank' | 'hit' | 'win') {
    const ctx = this.context;
    if (!ctx || ctx.state !== 'running') return;
    const notes = kind === 'win' ? [523, 659, 784, 1047] : kind === 'bank' ? [440, 660, 880] : kind === 'hit' ? [140, 80] : [660, 880];
    notes.forEach((frequency, i) => {
      const osc = ctx.createOscillator(); const gain = ctx.createGain();
      const start = ctx.currentTime + i * 0.09;
      osc.type = kind === 'hit' ? 'triangle' : 'sine'; osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0, start); gain.gain.linearRampToValueAtTime(0.075, start + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.18);
      osc.connect(gain); gain.connect(ctx.destination); osc.start(start); osc.stop(start + 0.2);
      osc.onended = () => { osc.disconnect(); gain.disconnect(); };
    });
  }
  dispose() { void this.context?.close().catch(() => {}); this.context = null; }
}
