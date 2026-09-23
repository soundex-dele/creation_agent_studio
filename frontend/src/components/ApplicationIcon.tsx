import { AppstoreOutlined, DesktopOutlined, WechatOutlined } from '@ant-design/icons';
import type { AppItem } from '@/types';

export default function ApplicationIcon({ app }: {
  app: Pick<AppItem, 'id' | 'icon' | 'rendererKey'>;
}) {
  if (app.rendererKey === 'wechat-assistant' || app.id === 'wechat-assistant') {
    return <WechatOutlined aria-hidden="true" />;
  }
  if (app.rendererKey === 'my-computer') {
    return <DesktopOutlined aria-hidden="true" />;
  }
  return <>{app.icon || <AppstoreOutlined aria-hidden="true" />}</>;
}
