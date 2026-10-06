// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import CoWorkPage from '@/pages/Apps/CoWorkPage';

it('replaces the legacy entry and preserves every launch and selection parameter', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const query = '?conversation=old&project=4&entry=home&standalone=1&embedded=1';
  const router = createMemoryRouter([
    { path: '/', element: <div>Home</div> },
    { path: '/apps/cowork', element: <CoWorkPage /> },
    { path: '/chat', element: <div>Unified chat</div> },
  ], { initialEntries: ['/', `/apps/cowork${query}#message`], initialIndex: 1 });
  const host = document.createElement('div');
  const root = createRoot(host);
  try {
    await act(async () => root.render(<RouterProvider router={router} />));
    expect(router.state.location.pathname).toBe('/chat');
    expect(router.state.location.search).toBe(query);
    expect(router.state.location.hash).toBe('#message');
    await act(async () => router.navigate(-1));
    expect(router.state.location.pathname).toBe('/');
  } finally {
    await act(async () => root.unmount());
    router.dispose();
    vi.unstubAllGlobals();
  }
});
