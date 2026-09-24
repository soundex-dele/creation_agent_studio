import React from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import TestRenderer, { act } from 'react-test-renderer';
import { SettingsScreen } from '../src/SettingsScreen';
import {
  listDownloads,
  supportsDownloadProgress,
  type DownloadTask,
} from '../src/downloads';

jest.mock('../src/downloads', () => ({
  ...jest.requireActual('../src/downloads'),
  listDownloads: jest.fn(),
  supportsDownloadProgress: jest.fn(() => true),
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: require('react-native').View,
}));

const task: DownloadTask = {
  id: '1',
  filename: 'report.pdf',
  status: 'running',
  downloadedBytes: 512,
  totalBytes: 1024,
  reason: 0,
  updatedAt: 10,
};
let renderer: TestRenderer.ReactTestRenderer;
let onAppState: (state: AppStateStatus) => void;
const progress = () =>
  renderer.root.findAllByProps({ accessibilityRole: 'progressbar' })[0].props
    .accessibilityValue;
const onBack = jest.fn();
const originalAppState = AppState.currentState;

beforeEach(async () => {
  AppState.currentState = 'active';
  jest.useFakeTimers();
  jest.clearAllMocks();
  jest.mocked(supportsDownloadProgress).mockReturnValue(true);
  jest.mocked(listDownloads).mockResolvedValue([task]);
  jest
    .spyOn(AppState, 'addEventListener')
    .mockImplementation((_event, callback) => {
      onAppState = callback;
      return { remove: jest.fn() };
    });
  await act(async () => {
    renderer = TestRenderer.create(<SettingsScreen onBack={onBack} />);
  });
});

afterEach(async () => {
  await act(async () => renderer.unmount());
  jest.restoreAllMocks();
  AppState.currentState = originalAppState;
  jest.useRealTimers();
});

it('updates actual progress and stops polling when the screen unmounts', async () => {
  expect(progress().now).toBe(50);
  jest
    .mocked(listDownloads)
    .mockResolvedValue([
      { ...task, status: 'completed', downloadedBytes: 1024 },
    ]);
  await act(async () => jest.advanceTimersByTime(1000));
  expect(progress().now).toBe(100);
  await act(async () => renderer.unmount());
  const calls = jest.mocked(listDownloads).mock.calls.length;
  await act(async () => jest.advanceTimersByTime(3000));
  expect(listDownloads).toHaveBeenCalledTimes(calls);
});

it('pauses polling in the background and refreshes on return', async () => {
  await act(async () => onAppState('background'));
  await act(async () => jest.advanceTimersByTime(4000));
  expect(listDownloads).toHaveBeenCalledTimes(1);
  await act(async () => onAppState('active'));
  expect(listDownloads).toHaveBeenCalledTimes(2);
});

it('shows a recoverable error and retains the last known progress', async () => {
  jest
    .mocked(listDownloads)
    .mockRejectedValueOnce(new Error('Provider unavailable'));
  await act(async () => jest.advanceTimersByTime(1000));
  expect(
    renderer.root.findAllByProps({ accessibilityRole: 'alert' }).length,
  ).toBeGreaterThan(0);
  expect(progress().now).toBe(50);
  await act(async () => jest.advanceTimersByTime(1000));
  expect(
    renderer.root.findAllByProps({ accessibilityRole: 'alert' }),
  ).toHaveLength(0);
});

it('marks unknown lengths without a fabricated percentage and provides a return action', async () => {
  jest.mocked(listDownloads).mockResolvedValue([{ ...task, totalBytes: -1 }]);
  await act(async () => jest.advanceTimersByTime(1000));
  expect(progress()).toEqual({ text: '总大小未知' });
  await act(async () =>
    renderer.root
      .findAll(
        node =>
          node.props.accessibilityLabel === '返回网页' &&
          typeof node.props.onPress === 'function',
      )[0]
      .props.onPress(),
  );
  expect(onBack).toHaveBeenCalledTimes(1);
});
