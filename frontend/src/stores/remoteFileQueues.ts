import { useAuthStore } from './useAuthStore';
import { RemoteFileQueue } from '@/services/remoteFileQueue';

const queues = new Map<string, RemoteFileQueue>();
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id || (previous.isAuthenticated && !state.isAuthenticated)) {
    queues.forEach(queue => queue.dispose()); queues.clear();
  }
});
export function remoteFileQueue(device: string) {
  const key = `${useAuthStore.getState().user?.id}:${device}`;
  let queue = queues.get(key);
  if (!queue) { queue = new RemoteFileQueue(device); queues.set(key, queue); }
  return queue;
}
window.addEventListener('beforeunload', event => {
  if ([...queues.values()].some(queue => queue.getSnapshot().some(task => task.direction === 'upload' && !['completed', 'cancelled'].includes(task.status)))) {
    event.preventDefault(); event.returnValue = '';
  }
});
