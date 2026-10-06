// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import MainLayout from '../MainLayout';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { hasSidebarContent } from '@/components/Sidebar/Sidebar';

const state = vi.hoisted(() => ({ mobile: false, layoutMode: 'left-right' }));
vi.mock('@/hooks/useMediaQuery', () => ({ default: () => state.mobile }));
vi.mock('@/stores/usePreferencesStore', () => ({
  usePreferencesStore: (select: (value: typeof state) => unknown) => select(state),
}));
vi.mock('@/components/Header/Header', () => ({ default: () => <nav data-platform-navigation /> }));
vi.mock('@/components/Navigation/MobileNavigation', () => ({ default: () => <nav data-mobile-navigation /> }));
vi.mock('@/components/Sidebar/HomeApplicationsSidebar', () => ({ default: () => <div>应用入口</div> }));
vi.mock('@/components/Sidebar/AgentCategoriesSidebar', () => ({ default: () => null }));
vi.mock('@/components/Sidebar/TemplateHistorySidebar', () => ({ default: () => null }));
vi.mock('@/components/Sidebar/AppHistorySidebar', () => ({ default: () => null }));
vi.mock('@/components/Sidebar/ProjectListSidebar', () => ({ default: () => null }));
vi.mock('@/components/ConversationHistory/ConversationHistory', () => ({ default: () => <div>旧对话历史</div> }));
vi.mock('antd', () => ({
  Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
  Drawer: ({ children, open }: { children: ReactNode; open: boolean }) => open ? <div>{children}</div> : null,
}));

afterEach(() => vi.unstubAllGlobals());

function LaunchShell() {
  const { pathname, search } = useLocation();
  const isHome = pathname === '/';
  const { showPlatformChrome } = resolveApplicationPresentation(new URLSearchParams(search));
  return <MainLayout hideHeader={!isHome && !showPlatformChrome} hideSidebar={!isHome && !showPlatformChrome} fullBleed={!isHome}>
    {isHome ? <div>工作台</div> : <aside aria-label="对话导航">项目、最近对话</aside>}
  </MainLayout>;
}

it.each(['/chat', '/chat/'])('does not register a platform history sidebar for %s', path => {
  expect(hasSidebarContent(path)).toBe(false);
});

it.each(['left-right', 'top-bottom'].flatMap(layoutMode => (
  [320, 375, 390, 767, 768, 844, 1440].map(width => ({ layoutMode, width }))
)))('keeps chat navigation inside the page after a workbench launch: $layoutMode at $width px', async ({ layoutMode, width }) => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  state.layoutMode = layoutMode;
  state.mobile = width < 768;
  const host = document.createElement('div');
  const root = createRoot(host);
  const entries = ['entry=home', 'entry=apps', 'entry=home&standalone=1', 'entry=home&embedded=1'];
  const paths = ['/chat', '/chat/'];
  const router = createMemoryRouter([{ path: '*', element: <LaunchShell /> }]);
  try {
    await act(async () => root.render(<RouterProvider router={router} />));
    expect(host.querySelector('[data-platform-navigation]')).not.toBeNull();
    for (const path of paths) {
      for (const query of entries) {
        const { showPlatformChrome } = resolveApplicationPresentation(new URLSearchParams(query));
        await act(async () => { await router.navigate(`${path}?${query}`); });
        expect(host.querySelector('.app-sidebar'), `${path}?${query}`).toBeNull();
        expect(host.querySelector('.app-context-toolbar')).toBeNull();
        expect(host.querySelector('[data-mobile-navigation]')).toBeNull();
        expect(host.querySelector('[aria-label="对话导航"]')).not.toBeNull();
        expect(host.querySelector('.app-main--padded')).toBeNull();
        if (layoutMode === 'left-right' || state.mobile || !showPlatformChrome) {
          expect(host.querySelector('[data-platform-navigation]')).toBeNull();
        }
      }
    }
  } finally {
    await act(async () => root.unmount());
    router.dispose();
  }
});
