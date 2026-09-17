import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Empty, Input, List, Spin, Tag, Tooltip, message,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

import { api } from '@/services/api';
import './SkillsPage.css';

interface RuntimeSkill {
  name: string;
  display_name: string;
  description: string;
  path: string;
  adapter: string;
}

interface RuntimeSkillResponse {
  adapter: string;
  directory: string;
  exists: boolean;
  skills: RuntimeSkill[];
}

const errorText = (error: any, fallback: string) =>
  error?.response?.data?.detail || error?.message || fallback;

const SkillsPage = () => {
  const [runtime, setRuntime] = useState<RuntimeSkillResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<RuntimeSkillResponse>('/apps/runtime-skills/');
      setRuntime(response);
    } catch (error) {
      message.error(errorText(error, '加载技能失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => {
    const skills = runtime?.skills ?? [];
    const keyword = query.trim().toLowerCase();
    if (!keyword) return skills;
    return skills.filter((skill) => [
      skill.name, skill.display_name, skill.description, skill.path,
    ].some((value) => value.toLowerCase().includes(keyword)));
  }, [query, runtime?.skills]);

  return (
    <div className="skills-page animate-fade-in">
      <div className="skills-page-header">
        <div>
          <h1 className="page-title">技能</h1>
          <p className="page-subtitle">实时读取当前 Agent Engine 目录中的最新技能，不使用数据库版本。</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </div>

      {runtime && (
        <div className="skill-root-grid skill-root-grid-active">
          <div className="skill-root-card active">
            <div className="skill-root-title">
              <Tag color="gold">{runtime.adapter}</Tag>
              <strong>{runtime.skills.length} 个技能</strong>
            </div>
            <Tooltip title={runtime.directory}>
              <code>{runtime.directory}</code>
            </Tooltip>
            <span className={runtime.exists ? 'root-ready' : 'root-missing'}>
              {runtime.exists ? '当前 Engine 目录可用' : '当前 Engine 目录不存在'}
            </span>
          </div>
        </div>
      )}

      <Input.Search
        allowClear
        placeholder="搜索技能名称、描述或路径"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        style={{ maxWidth: 480, marginBottom: 20 }}
      />

      <Spin spinning={loading}>
        {filtered.length === 0 ? (
          <Empty description={runtime?.exists === false ? '技能目录不存在' : '暂无技能'} />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, sm: 1, md: 2, lg: 3 }}
            dataSource={filtered}
            renderItem={(skill) => (
              <List.Item key={`${skill.adapter}:${skill.path}`}>
                <Card
                  title={skill.display_name || skill.name}
                  extra={<Tag>{skill.adapter}</Tag>}
                  className="runtime-skill-card"
                >
                  <p>{skill.description || '暂无描述'}</p>
                  <div className="runtime-skill-meta">
                    <Tag color="blue">{skill.name}</Tag>
                    <Tooltip title={skill.path}>
                      <code>{skill.path}</code>
                    </Tooltip>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  );
};

export default SkillsPage;
