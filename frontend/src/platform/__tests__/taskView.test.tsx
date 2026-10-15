// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import DurableApplicationRuntimePage from '@/pages/Apps/DurableApplicationRuntimePage';
import type { ApplicationTaskViewProps } from '../applications';

const mocks = vi.hoisted(() => ({ start: vi.fn(), input: { prompt: 'first' }, props: undefined as ApplicationTaskViewProps | undefined }));
vi.mock('virtual:application-packages', () => ({ default: [{
  rendererKey: 'test-task-view', routes: [],
  taskView: (props: ApplicationTaskViewProps) => {
    mocks.props = props;
    return <button onClick={() => void props.start(mocks.input)}>Submit package task</button>;
  },
}] }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: () => 'org' }));
vi.mock('@/services/applicationRuntime', () => ({ loadApplicationRuntime: async () => ({
  application_id: 17, organization_id: 'org', name: 'Package task', definition: { renderer_key: 'test-task-view' },
}) }));
vi.mock('@/components/Applications/ApplicationRuntimeContext', () => ({
  ApplicationRuntimeProvider: ({ children }: { children: React.ReactNode }) => children,
  useApplicationRuntime: () => ({ startRun: mocks.start }),
}));
vi.mock('@/features/run-stream', () => ({ useRunStream: () => ({ state: { progress: { current: 1, total: 2 }, output: 'working' }, connected: true }) }));
vi.mock('@/components/Applications/RunArtifacts', () => ({ default: () => null }));

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  mocks.start.mockReset(); mocks.input = { prompt: 'first' }; mocks.props = undefined;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it.each(['missing', 'throwing', 'absent'])('hosts a manifest task view and preserves request keys with crypto %s', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : { randomUUID: mode === 'missing' ? undefined : () => { throw new Error('insecure context'); } });
  await act(async () => root.render(<MemoryRouter initialEntries={['/applications/17/run?embedded=1']}><Routes>
    <Route path="/applications/:applicationId/run" element={<DurableApplicationRuntimePage />} />
  </Routes></MemoryRouter>));
  expect(mocks.props).toMatchObject({ percent: 50, total: 2, showApplicationHeader: false });
  const submit = () => act(async () => host.querySelector<HTMLButtonElement>('button')!.click());
  mocks.start.mockRejectedValueOnce(new Error('network failure'));
  await submit();
  mocks.start.mockResolvedValue({ id: 'run', status: 'queued' });
  await submit();
  expect(mocks.start).toHaveBeenCalledTimes(2);
  expect(mocks.start.mock.calls[0][1]).toBe(mocks.start.mock.calls[1][1]);
  await submit();
  expect(mocks.start.mock.calls[2][1]).not.toBe(mocks.start.mock.calls[1][1]);
  mocks.start.mockRejectedValueOnce(new Error('network failure'));
  await submit();
  mocks.input = { prompt: 'changed' };
  await submit();
  expect(mocks.start.mock.calls[4][1]).not.toBe(mocks.start.mock.calls[3][1]);
});
