type SearchParamsReader = Pick<URLSearchParams, 'get'>;

export type ApplicationEntry = 'home' | 'apps';

export interface ApplicationPresentation {
  entry: ApplicationEntry;
  embedded: boolean;
  showPlatformChrome: boolean;
  showApplicationHeader: boolean;
}

/**
 * Keeps platform and application navigation chrome mutually exclusive.
 * Home owns navigation, same-window catalog launches let the application own it,
 * and standalone windows / workflow embeds hide both navigation shells.
 */
export function resolveApplicationPresentation(
  searchParams: SearchParamsReader,
): ApplicationPresentation {
  const entry: ApplicationEntry = searchParams.get('entry') === 'home' ? 'home' : 'apps';
  const embedded = searchParams.get('embedded') === '1';
  const standalone = searchParams.get('standalone') === '1';

  return {
    entry,
    embedded,
    showPlatformChrome: entry === 'home' && !embedded && !standalone,
    showApplicationHeader: entry === 'apps' && !embedded && !standalone,
  };
}

/** Keep the launch presentation when navigating inside an application. */
export function applicationNavigationPath(path: string, searchParams: SearchParamsReader): string {
  const url = new URL(path, 'https://application.local');
  for (const key of ['entry', 'standalone', 'embedded']) {
    const value = searchParams.get(key);
    if (value !== null) url.searchParams.set(key, value);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** All separate application windows use the same chrome-free presentation. */
export function applicationWindowPath(path: string): string {
  const url = new URL(path, 'https://application.local');
  url.searchParams.delete('embedded');
  return applicationNavigationPath(`${url.pathname}${url.search}${url.hash}`, new URLSearchParams('entry=apps&standalone=1'));
}

/** Call from the launch gesture so the browser can open the new window. */
export function openApplicationWindow(path: string): void {
  window.open(applicationWindowPath(path), '_blank', 'noopener,noreferrer');
}

/** Reserve the window before an async creation request loses user activation. */
export async function openApplicationWindowWhenReady(resolvePath: () => Promise<string | null>): Promise<boolean> {
  const applicationWindow = window.open('about:blank', '_blank');
  if (!applicationWindow) throw new Error('新窗口被浏览器拦截，请允许弹出窗口后重试');
  applicationWindow.opener = null;
  try {
    const path = await resolvePath();
    if (!path) {
      applicationWindow.close();
      return false;
    }
    if (!applicationWindow.closed) applicationWindow.location.replace(applicationWindowPath(path));
    return true;
  } catch (error) {
    applicationWindow.close();
    throw error;
  }
}
