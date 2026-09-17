import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Drawer, Empty, Spin, message } from 'antd';
import { ArrowLeftOutlined, FolderOpenOutlined, MenuOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { useProjectStore } from '@/stores/useProjectStore';
import { useConversationStore } from '@/stores/useConversationStore';
import { useAgentStore } from '@/stores/useAgentStore';
import { getProcesses, resolveAgentId } from '@/lib/templateWorkflow';
import type { WorkspaceProject } from '@/types/workflow';
import ChatContainer from '@/components/Chat/ChatContainer';
import ProcessSidebar from '@/components/Workspace/ProcessSidebar';
import GuidedPromptPanel from '@/components/Workspace/GuidedPromptPanel';
import AssetPanel from '@/components/Workspace/AssetPanel';
import './WorkspacePage.css';

const WorkspacePage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { currentProject, isLoading, loadProject } = useProjectStore();
  const {
    createConversation,
    fetchProjectConversations,
    fetchConversationDetail,
    sendMessageStream,
  } = useConversationStore();
  const { agents, loadAgents } = useAgentStore();

  const project = currentProject as WorkspaceProject | null;
  const processes = useMemo(() => getProcesses(project?.structure), [project?.structure]);

  const [activeProcessId, setActiveProcessId] = useState<string | null>(null);
  const [convMap, setConvMap] = useState<Record<string, string>>({});
  const [seeding, setSeeding] = useState(false);
  const [processDrawerOpen, setProcessDrawerOpen] = useState(false);
  const [assetDrawerOpen, setAssetDrawerOpen] = useState(false);
  const creatingRef = useRef<Set<string>>(new Set());
  // Marks a conversation that was just seeded via sendMessageStream, so the
  // activeConvId fetch effect skips it (avoids clobbering the streamed placeholder).
  const justSeededRef = useRef<string | null>(null);

  const activeConvId = activeProcessId ? convMap[activeProcessId] : undefined;

  // Load project on id change.
  useEffect(() => {
    if (id) loadProject(Number(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Once a project is loaded: fetch agents (slug→id) and existing process conversations.
  useEffect(() => {
    if (!project) return;
    loadAgents();
    fetchProjectConversations(project.id).then((list) => {
      const m: Record<string, string> = {};
      list.forEach((c) => {
        if (c.process_id) m[c.process_id] = String(c.id);
      });
      setConvMap(m);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  // Default-select the first process.
  useEffect(() => {
    if (!activeProcessId && processes.length > 0) {
      setActiveProcessId(processes[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processes]);

  // Free-mode process: auto-create its conversation on first activation.
  useEffect(() => {
    if (!project || !activeProcessId) return;
    const proc = processes.find((p) => p.id === activeProcessId);
    if (!proc || proc.mode !== 'free') return;
    if (convMap[proc.id]) return;
    if (agents.length === 0) return; // wait for agent slug map
    if (creatingRef.current.has(proc.id)) return;
    creatingRef.current.add(proc.id);
    const agentId = resolveAgentId(proc.agent_slug, agents);
    createConversation(proc.name, agentId, project.id, proc.id)
      .then((conv) => setConvMap((m) => ({ ...m, [proc.id]: String(conv.id) })))
      .catch(() => {
        creatingRef.current.delete(proc.id);
        message.error('创建对话失败');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProcessId, project?.id, convMap, agents, processes]);

  // Refresh assets after a chat turn completes (message count changes).
  const msgCount = useConversationStore((s) => s.currentConversation?.messages?.length ?? 0);
  useEffect(() => {
    if (!project || msgCount === 0) return;
    const t = setTimeout(() => loadProject(project.id), 900);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [msgCount, project?.id]);

  // Load the active conversation into the store (ChatContainer uses autoFetch={false}
  // in the workspace, so fetching is centralized here to avoid races).
  useEffect(() => {
    if (!activeConvId) return;
    if (justSeededRef.current === activeConvId) {
      justSeededRef.current = null;
      return;
    }
    fetchConversationDetail(activeConvId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId]);

  // Guided start: create conversation bound to project+process, seed with assembled prompt.
  const handleGuidedStart = async (prompt: string) => {
    if (!project || !activeProcessId) return;
    const proc = processes.find((p) => p.id === activeProcessId);
    if (!proc) return;
    setSeeding(true);
    try {
      const agentId = resolveAgentId(proc.agent_slug, agents);
      const conv = await createConversation(proc.name, agentId, project.id, proc.id);
      const convId = String(conv.id);
      // Populate + seed BEFORE exposing as active, so ChatContainer mounts onto
      // an already-streaming conversation (no fetch to clobber the placeholder).
      await fetchConversationDetail(convId);
      sendMessageStream(convId, prompt);
      justSeededRef.current = convId;
      setConvMap((m) => ({ ...m, [proc.id]: convId }));
    } catch {
      message.error('创建对话失败');
    } finally {
      setSeeding(false);
    }
  };

  // ── Render gates (all hooks above are unconditional) ────────────────
  if (!id) {
    return (
      <div className="ws-page ws-page-empty">
        <Empty description="请选择一个应用或工作流">
          <Button type="primary" onClick={() => navigate('/apps')}>浏览应用中心</Button>
        </Empty>
      </div>
    );
  }

  if (isLoading && !project) {
    return (
      <div className="ws-page">
        <div className="flex items-center justify-center h-full">
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="ws-page ws-page-empty">
        <Empty description="工作空间不存在或无权访问">
          <Button onClick={() => navigate('/apps')}>返回应用中心</Button>
        </Empty>
      </div>
    );
  }

  const activeProcess = processes.find((p) => p.id === activeProcessId) || null;

  const handleProcessSelect = (processId: string) => {
    setActiveProcessId(processId);
    setProcessDrawerOpen(false);
  };

  const startedMap: Record<string, boolean> = {};
  processes.forEach((p) => {
    startedMap[p.id] = !!convMap[p.id];
  });

  const renderCenter = () => {
    if (!activeProcess) return null;
    // Guided + not started → option form
    if (activeProcess.mode === 'guided' && !activeConvId) {
      return (
        <GuidedPromptPanel
          process={activeProcess}
          applying={seeding}
          onStart={handleGuidedStart}
        />
      );
    }
    // Has a conversation → chat
    if (activeConvId) {
      return <ChatContainer conversationId={activeConvId} autoFetch={false} />;
    }
    // Free-mode conversation is being created
    return (
      <div className="ws-center-loading">
        <Spin />
      </div>
    );
  };

  return (
    <div className="ws-page">
      <div className="ws-main">
        <ProcessSidebar
          project={project}
          processes={processes}
          activeProcessId={activeProcessId}
          startedMap={startedMap}
          onSelect={handleProcessSelect}
          onBack={() => navigate('/apps')}
        />

        <section className="ws-center">
          <header className="ws-center-head">
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/templates')}
              className="ws-back-btn"
              aria-label="返回模板列表"
            />
            <div className="ws-center-proc">
              {activeProcess && <span className="ws-center-proc-icon">{activeProcess.icon || '✨'}</span>}
              <div>
                <div className="ws-center-proc-name">
                  {activeProcess?.name || '选择一个流程'}
                </div>
                {activeProcess?.description && (
                  <div className="ws-center-proc-desc">{activeProcess.description}</div>
                )}
              </div>
            </div>
            <div className="ws-mobile-tools" aria-label="工作台面板">
              <Button
                icon={<MenuOutlined />}
                onClick={() => setProcessDrawerOpen(true)}
              >
                流程
              </Button>
              <Button
                icon={<FolderOpenOutlined />}
                onClick={() => setAssetDrawerOpen(true)}
              >
                文件
              </Button>
            </div>
          </header>
          <div className="ws-center-content">{renderCenter()}</div>
        </section>

        <AssetPanel assets={project.assets || []} />
      </div>

      <Drawer
        title="任务流程"
        placement="left"
        width="min(88vw, 360px)"
        open={processDrawerOpen}
        onClose={() => setProcessDrawerOpen(false)}
        rootClassName="ws-mobile-drawer"
      >
        <ProcessSidebar
          project={project}
          processes={processes}
          activeProcessId={activeProcessId}
          startedMap={startedMap}
          onSelect={handleProcessSelect}
          onBack={() => navigate('/apps')}
        />
      </Drawer>

      <Drawer
        title="工作空间文件"
        placement="right"
        width="min(92vw, 380px)"
        open={assetDrawerOpen}
        onClose={() => setAssetDrawerOpen(false)}
        rootClassName="ws-mobile-drawer"
      >
        <AssetPanel assets={project.assets || []} />
      </Drawer>
    </div>
  );
};

export default WorkspacePage;
