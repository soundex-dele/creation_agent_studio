import { NativeModules, Platform } from 'react-native';
import {
  downloadPercent,
  downloadStatus,
  formatBytes,
  listDownloads,
  type DownloadTask,
} from '../src/downloads';

const task: DownloadTask = {
  id: '1',
  filename: 'report.pdf',
  status: 'running',
  downloadedBytes: 512,
  totalBytes: 1024,
  reason: 0,
  updatedAt: 10,
};
const originalOS = Platform.OS;

afterEach(() => {
  Platform.OS = originalOS;
  delete NativeModules.DownloadStatus;
});

it('reads system tasks and keeps active downloads above finished ones', async () => {
  Platform.OS = 'android';
  const completed = { ...task, id: '2', status: 'completed', updatedAt: 20 };
  const list = jest.fn(async () => [completed, task]);
  NativeModules.DownloadStatus = { listDownloads: list };
  expect(await listDownloads()).toEqual([task, completed]);
  expect(list).toHaveBeenCalledTimes(1);
});

it('reports a missing native module instead of pretending the list is empty', async () => {
  Platform.OS = 'android';
  await expect(listDownloads()).rejects.toThrow('下载管理器不可用');
});

it('does not invent progress for unknown size or claim success before the system finishes', () => {
  expect(downloadPercent(task)).toBe(50);
  expect(downloadPercent({ ...task, totalBytes: -1 })).toBeUndefined();
  expect(downloadPercent({ ...task, downloadedBytes: 2048 })).toBe(99);
  expect(
    downloadPercent({ ...task, totalBytes: -1, status: 'completed' }),
  ).toBe(100);
  expect(formatBytes(-1)).toBe('大小未知');
  expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
});

it('explains network pauses and download failures', () => {
  expect(downloadStatus({ ...task, status: 'paused', reason: 2 })).toBe(
    '等待网络连接',
  );
  expect(downloadStatus({ ...task, status: 'failed', reason: 404 })).toContain(
    'HTTP 404',
  );
  expect(downloadStatus({ ...task, status: 'failed', reason: 1006 })).toContain(
    '存储空间不足',
  );
});
