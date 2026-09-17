export const automationSchedulePresets = [
  { value: '0 * * * *', label: '每小时' },
  { value: '0 9 * * *', label: '每天 09:00' },
  { value: '0 9 * * 1-5', label: '工作日 09:00' },
  { value: '0 9 * * 1', label: '每周一 09:00' },
  { value: '0 9 1 * *', label: '每月 1 日 09:00' },
  { value: 'custom', label: '高级 Cron' },
] as const;

export const zonedLocalToIso = (localValue: string, timeZone: string) => {
  const normalized = localValue.length === 16 ? `${localValue}:00` : localValue;
  const wallClock = new Date(`${normalized}Z`);
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(wallClock).map(part => [part.type, part.value]),
  );
  const rendered = Date.UTC(
    Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour), Number(parts.minute), Number(parts.second),
  );
  return new Date(wallClock.getTime() - (rendered - wallClock.getTime())).toISOString();
};

export const isoToZonedLocal = (isoValue: string, timeZone: string) => {
  const formatter = new Intl.DateTimeFormat('sv-SE', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  return formatter.format(new Date(isoValue)).replace(' ', 'T');
};
