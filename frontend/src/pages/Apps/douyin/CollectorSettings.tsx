import { useEffect, useState } from 'react';
import { Alert, Button, Input, Modal, Spin } from 'antd';
import type { DouyinClient, CollectorConfig } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';

export function CollectorSettings({ client, onClose, onSaved }: { client: DouyinClient; onClose: () => void; onSaved: () => void }) {
  const [config, setConfig] = useState<CollectorConfig | null>(null);
  const [cookies, setCookies] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    void client.collectorConfig().then((data) => { if (active) setConfig(data); }).catch((e) => { if (active) setError(documentError(e)); });
    return () => { active = false; };
  }, [client, attempt]);
  const save = async () => {
    if (!config) return;
    setBusy(true); setError('');
    try {
      await client.saveCollectorConfig({ user_agent: config.user_agent, cookies, screen: config.screen, language: config.language, timezone: config.timezone });
      setCookies(''); onSaved(); onClose();
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  };
  const clear = async () => {
    setBusy(true); setError('');
    try { await client.clearCollectorConfig(); setCookies(''); onSaved(); onClose(); }
    catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  };
  return <Modal className="douyin-modal" title="采集设置" open onCancel={() => !busy && onClose()} footer={<div className="douyin-actions">
    {config?.configured && <Button danger disabled={busy} onClick={() => void clear()}>清除已保存配置</Button>}
    <Button disabled={busy} onClick={onClose}>取消</Button>
    <Button type="primary" loading={busy} disabled={!config?.user_agent.trim() || (!config.has_cookies && !cookies.trim())} onClick={() => void save()}>保存配置</Button>
  </div>}>
    <div className="douyin-form">
      <Alert type="info" showIcon message="使用同一桌面 Chrome 浏览器的 User-Agent 和 Cookie" description="打开抖音网页，在开发者工具的网络请求头中复制。Cookie 需包含 UIFID 或 UIFID_TEMP；支持 Cookie 请求头、JSON 对象或浏览器导出的 JSON 数组。" />
      {error && <Alert type="error" message={error} action={!config && <Button onClick={() => setAttempt((v) => v + 1)}>重试</Button>} />}
      {!config ? !error && <Spin /> : <>
        <label>User-Agent<Input.TextArea aria-label="采集 User-Agent" autoComplete="off" spellCheck={false} rows={3} maxLength={2000} value={config.user_agent} onChange={(e) => setConfig({ ...config, user_agent: e.target.value })} /></label>
        <label>Cookie{config.has_cookies && <small>（已保存，留空保留原值）</small>}<Input.TextArea aria-label="采集 Cookie" autoComplete="off" spellCheck={false} rows={4} maxLength={64000} value={cookies} placeholder={config.has_cookies ? '粘贴新 Cookie 可替换原值' : '粘贴 Cookie 请求头或 JSON'} onChange={(e) => setCookies(e.target.value)} /></label>
        <p>配置仅供当前用户在此应用中采集。Cookie 加密保存，保存后不再回显；不会写入分析提示词或任务日志。</p>
        <label>屏幕尺寸<Input aria-label="采集屏幕尺寸" value={config.screen} maxLength={20} onChange={(e) => setConfig({ ...config, screen: e.target.value })} /></label>
        <label>浏览器语言<Input aria-label="采集浏览器语言" value={config.language} maxLength={50} onChange={(e) => setConfig({ ...config, language: e.target.value })} /></label>
        <label>时区<Input aria-label="采集时区" value={config.timezone} maxLength={100} onChange={(e) => setConfig({ ...config, timezone: e.target.value })} /></label>
        <small>保存时校验配置格式和运行环境，是否能采集以实际结果为准。</small>
      </>}
    </div>
  </Modal>;
}
