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
 * Home owns navigation, catalog launches let the application own it, and
 * workflow embeds leave navigation to the workflow shell.
 */
export function resolveApplicationPresentation(
  searchParams: SearchParamsReader,
): ApplicationPresentation {
  const entry: ApplicationEntry = searchParams.get('entry') === 'home' ? 'home' : 'apps';
  const embedded = searchParams.get('embedded') === '1';

  return {
    entry,
    embedded,
    showPlatformChrome: entry === 'home' && !embedded,
    showApplicationHeader: entry === 'apps' && !embedded,
  };
}
