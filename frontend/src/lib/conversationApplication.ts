import type { AppItem } from '@/types';

export const CONVERSATION_APP_ID = 'platform-conversation';
export const CONVERSATION_APP: AppItem = {
  id: CONVERSATION_APP_ID,
  name: '对话',
  description: '通过持续对话处理日常需求，围绕文件夹组织项目，与 AI 协作完成任务。',
  category: 'chat',
  icon: 'message',
  color: '#6d5dfc',
  tags: ['AI 助手', '多轮对话', '文件夹', '项目'],
};

export const isCoworkApplication = (app: AppItem) => app.id === 'cowork' || app.rendererKey === 'cowork';
export const conversationApplicationId = (id: string) => id === 'cowork' ? CONVERSATION_APP_ID : id;

export function mergeConversationHomePreferences(preferences: { order: string[]; hidden: string[] }) {
  const hasConversationPreference = [...preferences.order, ...preferences.hidden].includes(CONVERSATION_APP_ID);
  const order = hasConversationPreference
    ? preferences.order.filter(id => id !== 'cowork')
    : preferences.order.map(conversationApplicationId);
  const hidden = hasConversationPreference
    ? preferences.hidden.filter(id => id !== 'cowork')
    : preferences.hidden.map(conversationApplicationId);
  return { order: [...new Set(order)], hidden: [...new Set(hidden)] };
}
