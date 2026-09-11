import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Empty, Form, Input, List, Modal, Select, Space, Spin, Tag, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';

import { api } from '@/services/api';
import './SkillsPage.css';

interface SkillResource {
  id: string;
  slug: string;
  name: string;
  description: string;
  visibility: 'private' | 'organization' | 'public';
  source_type: 'bundled' | 'upload' | 'git' | 'registry';
  source_uri: string;
  artifact_key: string;
  manifest: Record<string, unknown>;
  content_hash: string;
  is_active: boolean;
  updated_at: string;
}

type SkillForm = Pick<
  SkillResource,
  'slug' | 'name' | 'description' | 'visibility' | 'source_type' | 'source_uri' | 'artifact_key'
> & { manifest_text?: string };

const unwrap = <T,>(value: T[] | { results?: T[] }): T[] =>
  Array.isArray(value) ? value : value.results ?? [];

const errorText = (error: any, fallback: string) =>
  error?.response?.data?.detail || error?.message || fallback;

const SkillsPage = () => {
  const [skills, setSkills] = useState<SkillResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<SkillResource | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<SkillForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<SkillResource[] | { results?: SkillResource[] }>(
        '/apps/skills/',
      );
      setSkills(unwrap(response));
    } catch (error) {
      message.error(errorText(error, '加载技能失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return skills;
    return skills.filter((skill) => [skill.name, skill.slug, skill.description]
      .some((value) => value.toLowerCase().includes(keyword)));
  }, [query, skills]);

  const openEditor = (skill?: SkillResource) => {
    setEditing(skill || ({ id: '' } as SkillResource));
    form.setFieldsValue(skill ? {
      ...skill,
      manifest_text: JSON.stringify(skill.manifest || {}, null, 2),
    } : {
      visibility: 'organization',
      source_type: 'upload',
      manifest_text: '{}',
    } as SkillForm);
  };

  const save = async () => {
    if (!editing) return;
    const values = await form.validateFields();
    let manifest: Record<string, unknown>;
    try {
      manifest = JSON.parse(values.manifest_text || '{}');
      if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
        throw new Error();
      }
    } catch {
      message.error('Manifest 必须是 JSON 对象');
      return;
    }
    const payload = { ...values, manifest } as Record<string, unknown>;
    delete payload.manifest_text;
    setSaving(true);
    try {
      if (editing.id) await api.patch(`/apps/skills/${editing.slug}/`, payload);
      else await api.post('/apps/skills/', payload);
      message.success(editing.id ? '技能已更新' : '技能已创建');
      setEditing(null);
      form.resetFields();
      await load();
    } catch (error) {
      message.error(errorText(error, '保存技能失败'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (skill: SkillResource) => {
    Modal.confirm({
      title: `删除技能“${skill.name}”？`,
      content: '被 Agent 或 Application 引用的技能将无法删除。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        await api.delete(`/apps/skills/${skill.slug}/`);
        await load();
      },
    });
  };

  return (
    <div className="skills-page animate-fade-in">
      <div className="skills-page-header">
        <div>
          <h1>技能管理</h1>
          <p>唯一 Skill Catalog：Agent、Application 与运行快照均引用这里的资源。</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>
            新增技能
          </Button>
        </Space>
      </div>
      <Input.Search
        allowClear
        placeholder="搜索技能"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        style={{ maxWidth: 420, marginBottom: 20 }}
      />
      <Spin spinning={loading}>
        {filtered.length === 0 ? <Empty description="暂无技能" /> : (
          <List
            grid={{ gutter: 16, xs: 1, sm: 1, md: 2, lg: 3 }}
            dataSource={filtered}
            renderItem={(skill) => (
              <List.Item>
                <Card
                  title={skill.name}
                  extra={<Tag>{skill.visibility}</Tag>}
                  actions={[
                    <EditOutlined key="edit" onClick={() => openEditor(skill)} />,
                    <DeleteOutlined key="delete" onClick={() => remove(skill)} />,
                  ]}
                >
                  <p>{skill.description || '暂无描述'}</p>
                  <Space wrap>
                    <Tag color="blue">{skill.slug}</Tag>
                    <Tag>{skill.source_type}</Tag>
                    {!skill.is_active && <Tag color="default">已停用</Tag>}
                  </Space>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>
      <Modal
        title={editing?.id ? '编辑技能' : '新增技能'}
        open={editing !== null}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => void save()}
        onCancel={() => { setEditing(null); form.resetFields(); }}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="slug" label="Slug" rules={[{ required: true }]}>
            <Input disabled={Boolean(editing?.id)} />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
          <Space size="middle" style={{ display: 'flex' }}>
            <Form.Item name="visibility" label="可见性" rules={[{ required: true }]}>
              <Select style={{ width: 150 }} options={[
                { value: 'private', label: '私有' },
                { value: 'organization', label: '组织' },
                { value: 'public', label: '公开' },
              ]} />
            </Form.Item>
            <Form.Item name="source_type" label="来源" rules={[{ required: true }]}>
              <Select style={{ width: 150 }} options={[
                { value: 'bundled', label: '内置' },
                { value: 'upload', label: '上传' },
                { value: 'git', label: 'Git' },
                { value: 'registry', label: '注册中心' },
              ]} />
            </Form.Item>
          </Space>
          <Form.Item name="source_uri" label="来源 URI"><Input /></Form.Item>
          <Form.Item name="artifact_key" label="Artifact Key"><Input /></Form.Item>
          <Form.Item name="manifest_text" label="Manifest JSON">
            <Input.TextArea rows={8} spellCheck={false} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default SkillsPage;
