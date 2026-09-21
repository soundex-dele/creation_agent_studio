import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Empty, Form, Input, InputNumber, List, Modal, Progress,
  Popconfirm, Space, Tabs, Tag, Typography, Upload, message,
} from 'antd';
import {
  DeleteOutlined, FileTextOutlined, InboxOutlined, PlusOutlined,
  ReloadOutlined, SearchOutlined, BookOutlined, FolderOpenOutlined,
} from '@ant-design/icons';

import { useRunStream } from '@/features/run-stream';
import { createIdempotencyKey } from '@/lib/idempotencyKey';
import { api } from '@/services/api';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type {
  KnowledgeBaseDetail, KnowledgeBaseSummary, KnowledgeDocument,
  KnowledgeAnswerOutput, KnowledgeCitation, KnowledgeSearchResponse,
} from '@/types/knowledge';
import type { RunResource } from '@/services/applicationRuntime';
import WorkspaceHeader from '@/components/Workspace/WorkspaceHeader';
import './KnowledgePage.css';

const roleLevel: Record<string, number> = {
  viewer: 10, auditor: 20, operator: 30, developer: 40, admin: 50, owner: 60,
};

const statusColor: Record<string, string> = {
  pending: 'default', indexing: 'processing', ready: 'success', failed: 'error',
};
const statusLabel: Record<string, string> = {
  pending: '等待索引', indexing: '索引中', ready: '可检索', failed: '索引失败',
};

export default function KnowledgePage() {
  const {
    organizations, currentOrganizationId, loadOrganizations,
  } = useOrganizationStore();
  const currentOrganization = organizations.find(item => item.id === currentOrganizationId);
  const level = roleLevel[currentOrganization?.role || ''] || 0;
  const canWrite = level >= roleLevel.developer;
  const canAdmin = level >= roleLevel.admin;
  const root = currentOrganizationId ? tenantApiRoot(currentOrganizationId) : '';

  const [bases, setBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<KnowledgeBaseDetail | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [baseModal, setBaseModal] = useState(false);
  const [pasteModal, setPasteModal] = useState(false);
  const [baseForm] = Form.useForm();
  const [pasteForm] = Form.useForm();
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState<KnowledgeSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [answerRunId, setAnswerRunId] = useState<string | null>(null);
  const [answerOutput, setAnswerOutput] = useState<KnowledgeAnswerOutput | null>(null);
  const answerStream = useRunStream({
    organizationId: currentOrganizationId || '',
    runId: answerRunId,
    enabled: Boolean(currentOrganizationId && answerRunId),
  });

  const loadBases = useCallback(async () => {
    if (!currentOrganizationId) return;
    setLoading(true);
    try {
      const values = await api.get<KnowledgeBaseSummary[]>(`${root}/knowledge-bases/`);
      setBases(values);
      setSelectedId(current => current && values.some(item => item.id === current)
        ? current : values[0]?.id ?? null);
    } finally { setLoading(false); }
  }, [currentOrganizationId, root]);

  const loadSelected = useCallback(async () => {
    if (!selectedId) { setSelected(null); setDocuments([]); return; }
    const [detail, docs] = await Promise.all([
      api.get<KnowledgeBaseDetail>(`${root}/knowledge-bases/${selectedId}/`),
      api.get<KnowledgeDocument[]>(`${root}/knowledge-bases/${selectedId}/documents/`),
    ]);
    setSelected(detail); setDocuments(docs);
  }, [selectedId, root]);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);
  useEffect(() => { void loadBases(); }, [loadBases]);
  useEffect(() => { void loadSelected(); }, [loadSelected]);
  useEffect(() => {
    if (!documents.some(item => item.status === 'pending' || item.status === 'indexing')) return undefined;
    const timer = window.setInterval(() => { void loadSelected(); }, 2_000);
    return () => window.clearInterval(timer);
  }, [documents, loadSelected]);
  useEffect(() => {
    if (!answerRunId || answerStream.state.status !== 'succeeded') return;
    void api.get<RunResource>(`${root}/runs/${answerRunId}`).then((run) => {
      setAnswerOutput(run.output_summary as unknown as KnowledgeAnswerOutput);
    });
  }, [answerRunId, answerStream.state.status, root]);

  const saveBase = async () => {
    const values = await baseForm.validateFields();
    if (selected && baseModal && baseForm.getFieldValue('id')) {
      await api.patch(`${root}/knowledge-bases/${selected.id}/`, values);
    } else {
      await api.post(`${root}/knowledge-bases/`, values);
    }
    message.success('知识库已保存'); setBaseModal(false); baseForm.resetFields();
    await loadBases(); await loadSelected();
  };

  const openSettings = () => {
    if (!selected) return;
    baseForm.setFieldsValue({ ...selected, id: selected.id }); setBaseModal(true);
  };

  const uploadFile = async (file: File) => {
    if (!selected) return;
    const data = new FormData(); data.append('file', file); data.append('title', file.name);
    await api.post(`${root}/knowledge-bases/${selected.id}/documents/`, data, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    message.success(`${file.name} 已加入索引队列`); await loadSelected();
  };

  const pasteText = async () => {
    if (!selected) return;
    const values = await pasteForm.validateFields();
    await api.post(`${root}/knowledge-bases/${selected.id}/documents/`, values);
    message.success('文本已加入索引队列'); setPasteModal(false); pasteForm.resetFields();
    await loadSelected();
  };

  const previewCitation = async (citation: Pick<KnowledgeCitation, 'knowledge_base_id' | 'document_id'>) => {
    const blob = await api.get<Blob>(
      `${root}/knowledge-bases/${citation.knowledge_base_id}/documents/${citation.document_id}/content/`,
      undefined,
      { responseType: 'blob' },
    );
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const previewDocument = async (document: KnowledgeDocument) => {
    await previewCitation({
      knowledge_base_id: document.knowledge_base_id,
      document_id: document.id,
    });
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true); setAnswerRunId(null); setAnswerOutput(null);
    try {
      const result = await api.post<KnowledgeSearchResponse>(`${root}/knowledge-search/`, {
        query: query.trim(), knowledge_base_ids: selectedId ? [selectedId] : [], limit: 10,
      });
      setSearchResult(result);
    } finally { setSearching(false); }
  };

  const ask = async () => {
    if (!query.trim()) return;
    setSearching(true); setAnswerOutput(null);
    try {
      const result = await api.post<{ run: { id: string }; stream_url: string }>(`${root}/knowledge-answer-runs/`, {
        query: query.trim(), knowledge_base_ids: selectedId ? [selectedId] : [], limit: 10,
      }, { headers: { 'Idempotency-Key': createIdempotencyKey('knowledge') } });
      setAnswerRunId(result.run.id);
      if (!searchResult || searchResult.query !== query.trim()) await runSearch();
    } finally { setSearching(false); }
  };

  const tabs = [
    { key: 'documents', label: '文档', children: <>
      <div className="knowledge-toolbar">
        <Typography.Text type="secondary">{documents.length} 个文档</Typography.Text>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void loadSelected()}>刷新</Button>
          {canWrite && <Button onClick={() => setPasteModal(true)}>粘贴文本</Button>}
        </Space>
      </div>
      {canWrite && <Upload.Dragger
        multiple maxCount={20} accept=".pdf,.docx,.md,.markdown,.txt" showUploadList={false}
        beforeUpload={(file) => { void uploadFile(file); return Upload.LIST_IGNORE; }}
      ><p className="ant-upload-drag-icon"><InboxOutlined /></p><p>拖拽或点击上传 PDF、DOCX、Markdown、TXT</p><p className="ant-upload-hint">单文件最大 50 MiB，一次最多选择 20 个</p></Upload.Dragger>}
      <List className="knowledge-documents" dataSource={documents} locale={{ emptyText: <Empty description="暂无文档" /> }} renderItem={document => <List.Item actions={[
        <Button key="preview" size="small" onClick={() => void previewDocument(document)}>查看原文</Button>,
        ...(canWrite ? [<Button key="reindex" size="small" onClick={async () => { await api.post(`${root}/knowledge-bases/${selectedId}/documents/${document.id}/reindex/`, {}); message.success('已重新加入索引队列'); await loadSelected(); }}>{document.status === 'failed' ? '重试' : '重建索引'}</Button>] : []),
        ...(canAdmin ? [<Popconfirm key="delete" title="确认删除文档和索引？" onConfirm={async () => { await api.delete(`${root}/knowledge-bases/${selectedId}/documents/${document.id}/`); await loadSelected(); }}><Button size="small" danger icon={<DeleteOutlined />} aria-label={`删除 ${document.title}`} /></Popconfirm>] : []),
      ]}><List.Item.Meta avatar={<FileTextOutlined className="knowledge-file-icon" />} title={<Space>{document.title}<Tag color={statusColor[document.status]}>{statusLabel[document.status] || document.status}</Tag>{Boolean(document.metadata.retrieval_mode) && <Tag>{String(document.metadata.retrieval_mode)}</Tag>}</Space>} description={<>{document.original_filename || '粘贴文本'} · {Math.ceil(document.byte_size / 1024)} KiB{document.error && <Typography.Text type="danger"> · {document.error}</Typography.Text>}{(document.status === 'pending' || document.status === 'indexing') && <Progress size="small" percent={Number(document.metadata.index_progress || 0)} status="active" format={percent => `${String(document.metadata.index_stage || 'pending')} ${percent}%`} />}</>} /></List.Item>} />
    </> },
    { key: 'search', label: '搜索与问答', children: <div className="knowledge-search">
      <Input.Search size="large" value={query} onChange={event => setQuery(event.target.value)} onSearch={() => void runSearch()} enterButton={<><SearchOutlined /> 搜索</>} placeholder="输入要查找的问题或关键词" />
      <Space><Button type="primary" loading={searching} disabled={!selected?.answer_model} title={selected?.answer_model ? undefined : '请由管理员配置回答模型'} onClick={() => void ask()}>基于资料回答</Button>{searchResult && <Tag color={searchResult.retrieval_mode === 'lexical' ? 'orange' : 'blue'}>{searchResult.retrieval_mode}</Tag>}</Space>
      {searchResult?.retrieval_mode === 'lexical' && <Alert type="warning" showIcon message="当前使用关键词检索" description="嵌入模型未配置或暂时不可用，搜索仍可继续使用。" />}
      {answerRunId && <Card title="知识回答" loading={!answerStream.state.output && !answerStream.state.status}><Typography.Paragraph className="knowledge-answer">{answerOutput?.answer || answerStream.state.output || '正在生成回答…'}</Typography.Paragraph>{answerOutput?.citations?.length ? <List className="knowledge-citations" size="small" header="引用资料" dataSource={answerOutput.citations} renderItem={citation => <List.Item actions={[<Button key="source" type="link" size="small" onClick={() => void previewCitation(citation)}>查看原文</Button>]}><List.Item.Meta title={`${citation.label} ${citation.title}`} description={<>{citation.knowledge_base_name}{citation.page_number ? ` · 第 ${citation.page_number} 页` : ''}{citation.section_path.length ? ` · ${citation.section_path.join(' / ')}` : ''}<br />{citation.snippet}</>} /></List.Item>} /> : null}{answerStream.error && <Alert type="error" message={answerStream.error.message} />}</Card>}
      {searchResult?.results.length === 0 && <Empty description="没有找到相关资料" />}
      <List dataSource={searchResult?.results || []} renderItem={(item, index) => <List.Item><Card className="knowledge-result" title={<Space><Tag>[{index + 1}]</Tag>{item.title}</Space>} extra={item.page_number ? `第 ${item.page_number} 页` : undefined}><Typography.Paragraph>{item.snippet}</Typography.Paragraph><Typography.Text type="secondary">{item.knowledge_base_name} · {item.citation}</Typography.Text></Card></List.Item>} />
    </div> },
  ];

  return <div className="knowledge-page workspace-page">
    <WorkspaceHeader
      icon={<BookOutlined />} eyebrow="团队知识" title="知识库"
      description="让分散的资料成为可检索的知识，通过搜索与有据问答，快速找到需要的答案。"
      loading={loading || (selectedId !== null && selected?.id !== selectedId)}
      action={canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={() => { baseForm.resetFields(); baseForm.setFieldsValue({ chunk_size: 600, chunk_overlap: 80 }); setBaseModal(true); }}>新建知识库</Button>}
      metrics={[
        { label: '知识库', value: bases.length, hint: '按主题组织资料' },
        { label: '当前库文档', value: documents.length, hint: '当前选择的知识库' },
        { label: '可检索文档', value: documents.filter(item => item.status === 'ready').length, hint: '当前库已完成索引' },
      ]}
    />
    <div className="knowledge-layout">
      <Card className="knowledge-bases" title={<span className="knowledge-library-title"><FolderOpenOutlined aria-hidden="true" />资料目录</span>} extra={<span className="knowledge-library-count">{bases.length}</span>} loading={loading}>
        <List dataSource={bases} locale={{ emptyText: <Empty description="暂无知识库" /> }} renderItem={item => (
          <List.Item>
            <button type="button" className={`knowledge-base-button${item.id === selectedId ? ' active' : ''}`} aria-pressed={item.id === selectedId} onClick={() => setSelectedId(item.id)}>
              <span className="knowledge-base-icon" aria-hidden="true"><BookOutlined /></span>
              <span className="knowledge-base-copy"><strong>{item.name}</strong><small>{item.document_count} 个文档</small></span>
            </button>
          </List.Item>
        )} />
      </Card>
      <Card className="knowledge-main">{selected ? <><div className="knowledge-title"><div><Typography.Title level={3}>{selected.name}</Typography.Title><Typography.Text type="secondary">{selected.description || '暂无描述'}</Typography.Text></div><Space>{canWrite && <Button onClick={openSettings}>设置</Button>}{canAdmin && <Popconfirm title="确认删除整个知识库？" onConfirm={async () => { await api.delete(`${root}/knowledge-bases/${selected.id}/`); setSelectedId(null); await loadBases(); }}><Button danger>删除</Button></Popconfirm>}</Space></div><Tabs items={tabs} /></> : <Empty description="选择或新建一个知识库" />}</Card>
    </div>
    <Modal className="knowledge-base-modal" title={baseForm.getFieldValue('id') ? '知识库设置' : '新建知识库'} open={baseModal} onCancel={() => setBaseModal(false)} onOk={() => void saveBase()} width={680}><Form layout="vertical" form={baseForm}><Form.Item name="id" hidden><Input /></Form.Item><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item><Space className="knowledge-chunk-fields" align="start"><Form.Item name="chunk_size" label="分块 Token 数"><InputNumber min={100} max={1500} /></Form.Item><Form.Item name="chunk_overlap" label="重叠 Token 数"><InputNumber min={0} max={749} /></Form.Item></Space>{canAdmin && <><Form.Item name="embedding_provider" label="嵌入供应商名称"><Input /></Form.Item><Form.Item name="embedding_model" label="嵌入模型"><Input /></Form.Item><Form.Item name="answer_provider" label="回答供应商名称"><Input /></Form.Item><Form.Item name="answer_model" label="回答模型"><Input /></Form.Item></>}</Form></Modal>
    <Modal title="粘贴文本" open={pasteModal} onCancel={() => setPasteModal(false)} onOk={() => void pasteText()} width={720}><Form layout="vertical" form={pasteForm}><Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="text" label="正文" rules={[{ required: true }]}><Input.TextArea rows={12} showCount maxLength={2 * 1024 * 1024} /></Form.Item></Form></Modal>
  </div>;
}
