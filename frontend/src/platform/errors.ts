export function documentError(error: unknown): string {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (data) return Object.values(data).map((value) => Array.isArray(value) ? value.join('；') : String(value)).join('；');
  return error instanceof Error ? error.message : '操作失败，请稍后重试。';
}
