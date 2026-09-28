import { AppstoreOutlined, CloudOutlined, DesktopOutlined, WechatOutlined } from '@ant-design/icons';
import type { AppItem } from '@/types';
import { Boxes, Ship } from 'lucide-react';

export default function ApplicationIcon({ app }: {
  app: Pick<AppItem, 'id' | 'icon' | 'rendererKey'>;
}) {
  if (app.rendererKey === 'pocket-salvager' || app.id === 'pocket-salvager') {
    return <Ship size="1em" aria-hidden="true" />;
  }
  if (app.rendererKey === 'sokoban' || app.id === 'sokoban') {
    return <Boxes size="1em" aria-hidden="true" />;
  }
  if (app.rendererKey === 'wechat-assistant' || app.id === 'wechat-assistant') {
    return <WechatOutlined aria-hidden="true" />;
  }
  if (app.rendererKey === 'my-computer') {
    return <DesktopOutlined aria-hidden="true" />;
  }
  if (app.rendererKey === 'my-drive') {
    return <CloudOutlined aria-hidden="true" />;
  }
  return <>{app.icon || <AppstoreOutlined aria-hidden="true" />}</>;
}
