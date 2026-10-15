export function localDate(date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function entryError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (data && typeof data === 'object') {
    const labels: Record<string, string> = { title: '标题', body: '正文', tags: '标签', description: '说明', due_date: '截止日期', priority: '优先级' };
    return Object.entries(data).map(([key, value]) => `${labels[key] ? `${labels[key]}：` : ''}${Array.isArray(value) ? value.join('；') : String(value)}`).join('；');
  }
  return '操作失败，请检查网络后重试。';
}
