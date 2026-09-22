import { createContext, useContext } from 'react';
import { api } from '@/services/api';
import { useConversationStore } from '@/stores/useConversationStore';

export interface ChatConnectionValue {
  store: typeof useConversationStore;
  api: typeof api;
  remote: boolean;
  online: boolean;
}

export const ChatConnectionContext = createContext<ChatConnectionValue>({
  store: useConversationStore, api, remote: false, online: true,
});
export const useChatConnection = () => useContext(ChatConnectionContext);
