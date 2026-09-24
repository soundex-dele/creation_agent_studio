export interface SavedCredentials {
  username: string;
  password: string;
}

type CredentialRequest = (
  action: 'load' | 'save' | 'clear',
  values?: SavedCredentials,
) => Promise<SavedCredentials | null>;

export function getNativeCredentialRequest(): CredentialRequest | undefined {
  return (window as Window & {
    AgentStudioNative?: { credentials?: CredentialRequest };
  }).AgentStudioNative?.credentials;
}
