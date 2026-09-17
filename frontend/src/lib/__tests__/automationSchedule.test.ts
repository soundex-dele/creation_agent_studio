import { describe, expect, it } from 'vitest';

import {
  automationSchedulePresets,
  isoToZonedLocal,
  zonedLocalToIso,
} from '../automationSchedule';


describe('automation schedule helpers', () => {
  it('converts a Shanghai wall-clock time to UTC and back', () => {
    const iso = zonedLocalToIso('2026-01-02T09:30', 'Asia/Shanghai');
    expect(iso).toBe('2026-01-02T01:30:00.000Z');
    expect(isoToZonedLocal(iso, 'Asia/Shanghai')).toBe('2026-01-02T09:30');
  });

  it('exposes daily, weekly and monthly presets', () => {
    const values = automationSchedulePresets.map(item => item.value);
    expect(values).toContain('0 9 * * *');
    expect(values).toContain('0 9 * * 1');
    expect(values).toContain('0 9 1 * *');
  });
});
