import { NativeModules, Platform } from 'react-native';

export interface DownloadTask {
  id: string;
  filename: string;
  downloadedBytes: number;
  totalBytes: number;
  updatedAt: number;
  reason: number;
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed';
}

export function supportsDownloadProgress(): boolean {
  return Platform.OS === 'android';
}

export async function listDownloads(): Promise<DownloadTask[]> {
  if (!supportsDownloadProgress()) return [];
  const manager = NativeModules.DownloadStatus as
    | {
        listDownloads: () => Promise<DownloadTask[]>;
      }
    | undefined;
  if (!manager) throw new Error('下载管理器不可用，请更新 APP。');
  const tasks = await manager.listDownloads();
  const active = (task: DownloadTask) =>
    ['pending', 'running', 'paused'].includes(task.status);
  return tasks.sort(
    (left, right) =>
      Number(active(right)) - Number(active(left)) ||
      right.updatedAt - left.updatedAt,
  );
}

export function downloadPercent(task: DownloadTask): number | undefined {
  if (task.status === 'completed') return 100;
  if (task.totalBytes <= 0) return undefined;
  // Only the system's successful status means the file is fully saved.
  return Math.min(
    99,
    Math.max(0, Math.floor((task.downloadedBytes / task.totalBytes) * 100)),
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 0) return '大小未知';
  if (bytes < 1024) return `${bytes} B`;
  const unit = Math.min(3, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** unit).toFixed(1)} ${
    ['B', 'KB', 'MB', 'GB'][unit]
  }`;
}

export function downloadStatus(task: DownloadTask): string {
  switch (task.status) {
    case 'pending':
      return '等待下载';
    case 'running':
      return task.totalBytes > 0 ? '下载中' : '下载中 · 总大小未知';
    case 'completed':
      return '下载完成';
    case 'paused':
      return (
        (
          { 1: '等待重试', 2: '等待网络连接', 3: '等待 Wi-Fi' } as Record<
            number,
            string
          >
        )[task.reason] || '下载已暂停'
      );
    case 'failed':
      if (task.reason >= 400 && task.reason < 600)
        return `下载失败 · HTTP ${task.reason}`;
      return (
        (
          {
            1001: '下载失败 · 无法写入文件',
            1006: '下载失败 · 存储空间不足',
            1007: '下载失败 · 存储设备不可用',
            1008: '下载失败 · 无法恢复下载',
            1009: '下载失败 · 已存在同名文件',
          } as Record<number, string>
        )[task.reason] || '下载失败，请回到网页重新下载'
      );
  }
}
