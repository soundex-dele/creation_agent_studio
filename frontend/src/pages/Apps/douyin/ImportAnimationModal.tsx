import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Modal, Select, Spin } from 'antd';
import { openApplicationWindowWhenReady } from '@/lib/applicationPresentation';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { scriptToAnimation, type AnimationDestination } from '@/services/douyinAnimation';
import { projectApi } from '@/services/animationProjects';
import { tenantApiRoot } from '@/services/tenantContext';
import { documentError } from '@/services/documents';
import type { DouyinClient, Script } from '@/services/douyinBenchmark';

export function ImportAnimationModal({ client, script, onClose }: { client: DouyinClient; script: Script; onClose: () => void }) {
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const [apps, setApps] = useState<AnimationDestination[]>([]);
  const [destination, setDestination] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const flight = useRef(false);
  const alive = useRef(true);
  const prepared = useMemo(() => {
    try { return { ...scriptToAnimation(script), error: '' }; }
    catch (e) { return { document: undefined, estimated: false, error: documentError(e) }; }
  }, [script]);
  useEffect(() => {
    alive.current = true;
    let active = true;
    void client.animationDestinations().then(items => {
      if (active) { setApps(items); setDestination(items[0]?.id); }
    }).catch(e => { if (active) setError(documentError(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; alive.current = false; };
  }, [client]);
  const importScript = async () => {
    if (flight.current || !organizationId || !destination || !prepared.document) return;
    flight.current = true; setBusy(true); setError('');
    try {
      const opened = await openApplicationWindowWhenReady(async () => {
        const project = await projectApi(`${tenantApiRoot(organizationId)}/applications/${destination}/animation-studio`).create(prepared.document!, script.title || '抖音创作脚本');
        return alive.current && useOrganizationStore.getState().currentOrganizationId === organizationId
          ? `/applications/${destination}/animation-studio?project=${encodeURIComponent(project.id)}`
          : null;
      });
      if (opened && alive.current) onClose();
    } catch (e) { if (alive.current) setError(documentError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  return <Modal className="douyin-modal" title="导入动画制作" open onCancel={() => !busy && onClose()} maskClosable={!busy}
    okText="创建动画作品并打开" confirmLoading={busy} okButtonProps={{ disabled: loading || !destination || !organizationId || !prepared.document }} onOk={() => void importScript()}>
    <div className="douyin-form">
      <p>将当前已保存的脚本复制为新的动画作品，原脚本和已有动画作品保持不变。</p>
      {prepared.error && <Alert type="warning" message={prepared.error} />}
      {error && <Alert type="error" message={error} />}
      {loading ? <Spin /> : apps.length ? <label>动画制作应用<Select aria-label="动画制作应用" value={destination} disabled={busy} options={apps.map(app => ({ value: app.id, label: app.name }))} onChange={setDestination} /></label>
        : !error && <Alert type="info" message="当前没有可用的动画制作应用，请先在当前组织启用应用并确认访问权限。" />}
      {prepared.document && <>
        <p>{script.title || '未命名脚本'} · {prepared.document.scenes.length} 个分镜 · {Math.round(prepared.document.scenes.reduce((sum, scene) => sum + scene.frames, 0) / 30 * 10) / 10} 秒 · 9:16 竖屏</p>
        <Alert type="info" message="导入后可继续调整分镜、配音和字幕，再生成动画。" description={prepared.estimated ? '部分镜头没有明确时长，已按口播长度估算；不足 5 秒的工程会补足至 5 秒，请在制作前检查。' : '镜头时长按脚本时间段换算，完整口播、封面短句与拍摄清单保存在动画内容中。'} />
      </>}
    </div>
  </Modal>;
}
