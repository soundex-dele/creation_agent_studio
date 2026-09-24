import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Collapse, Select, Space, Spin, Typography } from 'antd';
import { allBrandPages, brandModules, type BrandConfig, type BrandItem, type BrandModule, type BrandProfile, type BrandSelection } from '@/services/brandLibrary';
import { entryError } from '@/services/ideasTodos';

export default function BrandReferencePicker({ root, config, value, onChange }: {
  root: string; config: BrandConfig; value: BrandSelection | null; onChange: (value: BrandSelection | null) => void;
}) {
  const [profiles, setProfiles] = useState<BrandProfile[]>([]);
  const [products, setProducts] = useState<BrandItem[]>([]);
  const [examples, setExamples] = useState<BrandItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const profileId = value?.profile.id;
  const applicationId = value?.profile.application_id;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setProfiles([]);
    void allBrandPages<BrandProfile>(`${root}/brand-library/profiles`, controller.signal)
      .then((items) => { if (!controller.signal.aborted) setProfiles(items); })
      .catch((failure) => { if (!controller.signal.aborted) setError(entryError(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [root, retry]);
  useEffect(() => {
    const controller = new AbortController();
    setProducts([]); setExamples([]); setItemsLoading(false);
    if (profileId && applicationId) {
      setItemsLoading(true); setError('');
      const base = `${root}/applications/${applicationId}/brand-library/profiles/${profileId}`;
      void Promise.all([allBrandPages<BrandItem>(`${base}/products`, controller.signal), allBrandPages<BrandItem>(`${base}/examples`, controller.signal)])
        .then(([p, e]) => { if (!controller.signal.aborted) { setProducts(p); setExamples(e); } })
        .catch((failure) => { if (!controller.signal.aborted) setError(entryError(failure)); })
        .finally(() => { if (!controller.signal.aborted) setItemsLoading(false); });
    }
    return () => controller.abort();
  }, [root, profileId, applicationId, retry]);
  const choose = (id?: string) => {
    const profile = profiles.find((item) => item.id === id);
    onChange(profile ? { profile, reference: { profile_id: profile.id, modules: config.default_modules, product_ids: [], example_ids: [] } } : null);
  };
  return <Collapse style={{ marginBottom: 20 }} items={[{
    key: 'brand', label: value ? `引用品牌资料 · ${value.profile.name}` : '引用品牌资料（可选）',
    children: <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text type="secondary">仅自己可见。选择本次需要的资料，发送后保存在对话中。</Typography.Text>
      {error && <Alert type="error" message={error} action={<Button onClick={() => setRetry((n) => n + 1)}>重试</Button>} />}
      <label htmlFor="brand-profile">品牌或账号</label>
      <Select id="brand-profile" style={{ width: '100%' }} showSearch optionFilterProp="label" allowClear
        placeholder={loading ? '加载品牌档案…' : '不引用品牌资料'} loading={loading} value={profileId}
        options={profiles.map((profile) => ({ label: profile.name, value: profile.id }))} onChange={choose} />
      {!loading && !error && profiles.length === 0 && <Typography.Text>还没有档案，请先在应用中心的“品牌资料库”中创建。</Typography.Text>}
      {value && <>
        <Checkbox.Group aria-label="引用模块" value={value.reference.modules} options={Object.entries(brandModules).map(([key, label]) => ({ value: key, label }))}
          onChange={(keys) => onChange({ ...value, reference: { ...value.reference, modules: keys as BrandModule[],
            product_ids: keys.includes('products') ? value.reference.product_ids : [], example_ids: keys.includes('examples') ? value.reference.example_ids : [],
          } })} />
        {!value.reference.modules.length && <Alert type="warning" message="请选择至少一个模块，或取消品牌引用。" />}
        {itemsLoading && <Spin size="small" />}
        {(['products', 'examples'] as const).filter((kind) => value.reference.modules.includes(kind)).map((kind) => {
          const key = kind === 'products' ? 'product_ids' : 'example_ids';
          return <div key={kind} style={{ width: '100%' }}><label htmlFor={`brand-${kind}`}>{brandModules[kind]}（仅引用勾选条目）</label>
            <Select id={`brand-${kind}`} mode="multiple" style={{ width: '100%' }} value={value.reference[key]} loading={itemsLoading}
              options={(kind === 'products' ? products : examples).map((item) => ({ value: item.id, label: item.name }))}
              onChange={(ids: string[]) => onChange({ ...value, reference: { ...value.reference, [key]: ids } })} /></div>;
        })}
      </>}
    </Space>,
  }]} />;
}
