import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Dropdown, Empty, message } from 'antd';
import type { MenuProps } from 'antd';
import {
  CloseOutlined,
  ProfileOutlined,
  FolderOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  StopOutlined,
  LoadingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useChatConnection } from './ChatConnectionContext';
import { loadConnectionCollection } from '@/services/chatConnection';
import { useAgentStore, type Agent } from '@/stores/useAgentStore';
import { useProjectStore, type Project } from '@/stores/useProjectStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import FolderPickerModal from '@/pages/Apps/FolderPickerModal';
import './MessageInput.css';

export interface ComposerContext {
  projectId?: number;
  workingDirectory?: string;
  agentId: number | null;
  agent: ComposerAgent | null;
  permissionMode: 'default' | 'allow_all';
  collaborationMode: 'default' | 'plan';
  skillNames: string[];
}

interface SkillOption {
  name: string;
  display_name: string;
  description?: string;
}

export type ComposerAgent = Pick<Agent, 'id' | 'name' | 'description'>;

interface MessageInputProps {
  value?: string;
  onValueChange?: (value: string) => void;
  onSendMessage: (
    content: string,
    context: ComposerContext,
    images: File[],
  ) => void | Promise<void>;
  disabled?: boolean;
  isRunning?: boolean;
  onStop?: () => void | Promise<void>;
  stopDisabled?: boolean;
  isStopping?: boolean;
  visible?: boolean;
  placeholder?: string;
  currentAgent?: ComposerAgent | null;
  workspaceLocked?: boolean;
  workspace?: Pick<ComposerContext, 'projectId' | 'workingDirectory'>;
  onWorkspaceChange?: (workspace: Pick<ComposerContext, 'projectId' | 'workingDirectory'>) => Promise<void>;
  mode?: 'default' | 'study' | 'document';
}

const MessageInput: React.FC<MessageInputProps> = ({
  value: controlledValue,
  onValueChange,
  onSendMessage,
  disabled = false,
  isRunning = false,
  onStop,
  stopDisabled = false,
  isStopping = false,
  visible = true,
  placeholder = '输入消息...',
  currentAgent = null,
  workspaceLocked = false,
  workspace,
  onWorkspaceChange,
  mode = 'default',
}) => {
  const { api, remote, online = true } = useChatConnection();
  const [internalValue, setInternalValue] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [selectedSystemDirectory, setSelectedSystemDirectory] = useState('');
  const [folderPickerOpen, setFolderPickerOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<ComposerAgent | null>(currentAgent);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedImages, setSelectedImages] = useState<Array<{
    file: File;
    previewUrl: string;
  }>>([]);
  const selectedImagesRef = useRef(selectedImages);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const permissionMode = usePreferencesStore((state) => state.defaultPermissionMode);
  const setPermissionMode = usePreferencesStore((state) => state.setDefaultPermissionMode);
  const sendShortcut = usePreferencesStore((state) => state.sendShortcut);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [approvalPolicy, setApprovalPolicy] = useState<{
    api: typeof api;
    organizationId: string | null;
    required: boolean | undefined;
    failed?: boolean;
  } | null>(null);
  const [policyAttempt, setPolicyAttempt] = useState(0);
  // Never reuse a different computer's or organization's permission policy.
  const requireToolApproval = approvalPolicy?.api === api
    && approvalPolicy.organizationId === organizationId ? approvalPolicy.required : undefined;
  const fullControlAllowed = requireToolApproval === false;
  const permissionPending = permissionMode === 'allow_all' && requireToolApproval === undefined;
  const policyFailed = approvalPolicy?.api === api
    && approvalPolicy.organizationId === organizationId && approvalPolicy.failed;
  const effectivePermissionMode = requireToolApproval === true ? 'default' : permissionMode;
  const [collaborationMode, setCollaborationMode] = useState<'default' | 'plan'>('default');
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const { projects: localProjects, loadProjects } = useProjectStore();
  const [remoteProjects, setRemoteProjects] = useState<Project[]>([]);
  const projects = remote ? remoteProjects : localProjects;
  useEffect(() => {
    if (!workspace) return;
    setSelectedProject(projects.find(project => project.id === workspace.projectId) || null);
    setSelectedSystemDirectory(workspace.workingDirectory || '');
  }, [workspace?.projectId, workspace?.workingDirectory, projects, workspace]);
  const { agents: serverAgents, loadAgents } = useAgentStore();
  const [remoteAgents, setRemoteAgents] = useState<ComposerAgent[]>([]);
  const agents = remote ? remoteAgents : serverAgents;

  useEffect(() => {
    selectedImagesRef.current = selectedImages;
  }, [selectedImages]);

  useEffect(() => () => {
    selectedImagesRef.current.forEach(({ previewUrl }) => URL.revokeObjectURL(previewUrl));
  }, []);

  useEffect(() => {
    if (mode !== 'default') return;
    let cancelled = false;
    if (remote) {
      setRemoteProjects([]);
      void loadConnectionCollection<Project>(api, '/projects/')
        .then(result => { if (!cancelled) setRemoteProjects(result); })
        .catch(() => { if (!cancelled) setRemoteProjects([]); });
      loadConnectionCollection<ComposerAgent>(api, '/agents/')
        .then(result => { if (!cancelled) setRemoteAgents(result); })
        .catch(() => { if (!cancelled) setRemoteAgents([]); });
    } else {
      void loadProjects();
      void loadAgents();
    }
    return () => { cancelled = true; };
  }, [loadAgents, loadProjects, mode, api, remote, organizationId]);

  useEffect(() => {
    let cancelled = false;
    setApprovalPolicy(null);
    if (!online) return;
    api.get<{ skills: SkillOption[]; require_tool_approval: boolean }>('/conversations/composer-options/')
      .then((response) => {
        if (cancelled) return;
        setSkills(response.skills || []);
        const required = typeof response.require_tool_approval === 'boolean'
          ? response.require_tool_approval : undefined;
        setApprovalPolicy({ api, organizationId, required, failed: required === undefined });
      })
      .catch(() => {
        if (cancelled) return;
        setSkills([]);
        setApprovalPolicy({ api, organizationId, required: undefined, failed: true });
      });
    return () => { cancelled = true; };
  }, [api, organizationId, online, policyAttempt]);

  useEffect(() => {
    setSelectedAgent(currentAgent);
  }, [currentAgent]);

  // Support both controlled and uncontrolled modes
  const content = controlledValue !== undefined ? controlledValue : internalValue;
  const setContent = (val: string) => {
    if (controlledValue !== undefined) {
      onValueChange?.(val);
    } else {
      setInternalValue(val);
    }
  };

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Grow the textarea to fit its content, capped at max-height (160px) so long
  // drafts scroll internally instead of expanding the composer without bound.
  // Recompute on every keystroke and whenever the value changes externally
  // (e.g. suggestion click, draft prefill, post-send clear).
  const autosizeTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  };
  useEffect(autosizeTextarea, [content, visible]);

  const handleSend = async () => {
    if ((content.trim() || selectedImages.length > 0) && !disabled && !permissionPending && !isSubmitting && !isRunning) {
      setIsSubmitting(true);
      try {
        await onSendMessage(content.trim(), {
          projectId: selectedProject?.id,
          workingDirectory: selectedSystemDirectory || undefined,
          agentId: selectedAgent?.id ?? null,
          agent: selectedAgent,
          permissionMode: effectivePermissionMode,
          collaborationMode,
          skillNames: selectedSkills,
        }, selectedImages.map(({ file }) => file));
        setContent('');
        setSelectedSkills([]);
        selectedImages.forEach(({ previewUrl }) => URL.revokeObjectURL(previewUrl));
        setSelectedImages([]);
      } catch {
        // Keep the draft and selected images so the user can retry.
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  const handleImageSelection = (files: FileList | null) => {
    if (!files?.length) return;
    const availableSlots = 4 - selectedImages.length;
    if (availableSlots <= 0) {
      message.warning('每条消息最多上传 4 张图片');
      return;
    }
    const allowedTypes = new Set([
      'image/jpeg', 'image/jpg', 'image/png', 'image/webp',
    ]);
    const accepted: Array<{ file: File; previewUrl: string }> = [];
    Array.from(files).slice(0, availableSlots).forEach((file) => {
      const hasAllowedExtension = /\.(?:jpe?g|png|webp)$/i.test(file.name);
      const hasGenericType = file.type === '' || file.type === 'application/octet-stream';
      if (!allowedTypes.has(file.type) && !(hasGenericType && hasAllowedExtension)) {
        message.error(`${file.name} 不是支持的 JPG、PNG 或 WebP 图片`);
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        message.error(`${file.name} 超过 10MB`);
        return;
      }
      accepted.push({ file, previewUrl: URL.createObjectURL(file) });
    });
    if (files.length > availableSlots) {
      message.warning('每条消息最多上传 4 张图片');
    }
    if (accepted.length) setSelectedImages((current) => [...current, ...accepted]);
  };

  const removeImage = (previewUrl: string) => {
    URL.revokeObjectURL(previewUrl);
    setSelectedImages((current) => current.filter((item) => item.previewUrl !== previewUrl));
  };

  const changeWorkspace = async (project: Project | null, directory = '') => {
    if (disabled || workspaceLocked) return;
    try {
      await onWorkspaceChange?.({ projectId: project?.id, workingDirectory: directory });
      setSelectedProject(project);
      setSelectedSystemDirectory(directory);
    } catch {
      message.error('切换工作空间失败，原工作空间保持不变，请重试。');
    }
  };

  const workspaceItems: MenuProps['items'] = [
    { key: 'none', label: onWorkspaceChange ? '使用默认会话目录' : '不使用工作空间' },
    { key: 'system-directory', label: '选择系统目录…' },
    ...(projects.length
      ? projects.map((project) => ({ key: String(project.id), label: project.title }))
      : [{ key: 'empty', disabled: true, label: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工作空间" /> }]),
  ];

  const permissionItems: MenuProps['items'] = [
    { key: 'default', label: '默认权限', extra: '按需确认高风险工具' },
    {
      key: 'allow_all', label: '完全控制', disabled: !fullControlAllowed,
      extra: requireToolApproval === true ? '组织要求工具审批，无法开启'
        : fullControlAllowed ? '完整文件访问，无需逐次确认' : '尚未获取组织权限，暂不可用',
    },
  ];

  const attachmentItems = useMemo<MenuProps['items']>(() => [
    ...(!remote ? [{
      key: 'images',
      icon: <PictureOutlined />,
      label: '图片',
    }] : []),
    {
      key: 'skills',
      icon: <ThunderboltOutlined />,
      label: 'Skill',
      children: skills.length
        ? skills.map((skill) => ({
            key: `skill:${skill.name}`,
            label: skill.display_name || skill.name,
            title: skill.description,
          }))
        : [{ key: 'skills-empty', disabled: true, label: '暂无可用 Skill' }],
    },
    {
      key: 'agents',
      icon: <RobotOutlined />,
      label: 'Agent',
      children: agents.length
        ? agents.map((agent) => ({
            key: `agent:${agent.id}`,
            label: agent.name,
            title: agent.description,
          }))
        : [{ key: 'agents-empty', disabled: true, label: '暂无可用 Agent' }],
    },
  ], [agents, skills, remote]);

  const handleAttachmentClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'images') {
      imageInputRef.current?.click();
    } else if (key.startsWith('skill:')) {
      const name = key.slice(6);
      setSelectedSkills((current) => current.includes(name) ? current : [...current, name]);
    } else if (key.startsWith('agent:')) {
      const id = Number(key.slice(6));
      setSelectedAgent(agents.find((agent) => agent.id === id) || null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const shouldSend = sendShortcut === 'enter'
      ? e.key === 'Enter' && !e.shiftKey
      : e.key === 'Enter' && (e.ctrlKey || e.metaKey);
    if (shouldSend) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className={`chat-input-box chat-input-box--${mode} ${isFocused ? 'chat-input-box--focused' : ''}`}>
      <div className="chat-input-main">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={placeholder}
          aria-label="消息内容"
          disabled={disabled}
          rows={1}
          className="chat-input-textarea"
        />
        <button
          type="button"
          className={`chat-send-btn ${isRunning ? 'chat-send-btn--stop' : ''}`}
          onClick={() => { if (isRunning) void onStop?.(); else void handleSend(); }}
          disabled={isRunning
            ? stopDisabled || isStopping || !onStop
            : (!content.trim() && selectedImages.length === 0) || disabled || permissionPending || isSubmitting}
          aria-label={isRunning ? '结束任务' : '发送消息'}
          title={isRunning ? '结束任务' : permissionPending ? '正在确认已保存的完全控制权限' : '发送消息'}
          aria-busy={isStopping || isSubmitting}
        >
          {isRunning ? (isStopping ? <LoadingOutlined /> : <StopOutlined />) : <SendOutlined />}
        </button>
      </div>

      {permissionPending && (
        <div role="status" className="chat-composer-attachments">
          {policyFailed ? <button type="button" className="chat-composer-action"
            onClick={() => setPolicyAttempt(attempt => attempt + 1)}>
            权限校验失败，点击重试
          </button> : <span>{online ? '正在确认已保存的完全控制权限…' : '连接恢复后确认已保存的完全控制权限'}</span>}
        </div>
      )}

      {selectedImages.length > 0 && (
        <div className="chat-composer-images" aria-label="待发送图片">
          {selectedImages.map(({ file, previewUrl }) => (
            <div className="chat-composer-image" key={previewUrl}>
              <img src={previewUrl} alt={file.name} />
              <button
                type="button"
                onClick={() => removeImage(previewUrl)}
                aria-label={`移除图片 ${file.name}`}
              >
                <CloseOutlined />
              </button>
              <span title={file.name}>{file.name}</span>
            </div>
          ))}
        </div>
      )}

      {(selectedAgent || selectedSkills.length > 0) && (
        <div className="chat-composer-attachments">
          {selectedAgent && (
            <span className="chat-composer-chip">
              <RobotOutlined /> {selectedAgent.name}
              {mode === 'default' && <button type="button" onClick={() => setSelectedAgent(null)} aria-label="移除 Agent"><CloseOutlined /></button>}
            </span>
          )}
          {selectedSkills.map((skillName) => {
            const skill = skills.find((item) => item.name === skillName);
            return (
              <span className="chat-composer-chip" key={skillName}>
                <ThunderboltOutlined /> {skill?.display_name || skillName}
                <button
                  onClick={() => setSelectedSkills((current) => current.filter((item) => item !== skillName))}
                  aria-label={`移除 ${skill?.display_name || skillName}`}
                ><CloseOutlined /></button>
              </span>
            );
          })}
        </div>
      )}

      {mode === 'document' ? null : mode === 'study' ? (
        <div className="chat-composer-toolbar chat-composer-toolbar--study">
          <button
            type="button"
            className="chat-composer-action"
            disabled={disabled}
            onClick={() => imageInputRef.current?.click()}
          >
            <PictureOutlined /><span>添加题图</span>
          </button>
          <input
            ref={imageInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => {
              handleImageSelection(event.target.files);
              event.target.value = '';
            }}
          />
        </div>
      ) : <div className="chat-composer-toolbar">
        <Dropdown
          trigger={['click']}
          menu={{
            items: workspaceItems,
            selectedKeys: [selectedProject
              ? String(selectedProject.id)
              : selectedSystemDirectory ? 'system-directory' : 'none'],
            onClick: ({ key }) => {
              if (key === 'system-directory') {
                setFolderPickerOpen(true);
                return;
              }
              void changeWorkspace(
                key === 'none' ? null
                  : projects.find((project) => String(project.id) === key) || null,
              );
            },
          }}
        >
          <button className="chat-composer-action" disabled={disabled || workspaceLocked} aria-label="选择工作空间"
            title={workspaceLocked ? '当前对话不支持切换工作空间' : selectedProject?.title || selectedSystemDirectory || '选择工作空间'}>
            <FolderOutlined />
            <span>{selectedProject?.title
              || (selectedSystemDirectory ? selectedSystemDirectory : '选择工作空间')}</span>
          </button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          menu={{
            items: permissionItems,
            selectedKeys: [effectivePermissionMode],
            onClick: ({ key }) => {
              if (key === 'default' || (key === 'allow_all' && fullControlAllowed)) setPermissionMode(key);
            },
          }}
        >
          <button className="chat-composer-action" disabled={disabled} aria-label="对话权限（所有会话）" title="修改后应用于所有会话的后续消息">
            <SafetyCertificateOutlined />
            <span>{effectivePermissionMode === 'default' ? '默认权限'
              : permissionPending ? '完全控制（待确认）' : '完全控制'}</span>
          </button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              { key: 'default', label: '执行模式', extra: '直接处理任务' },
              { key: 'plan', label: 'Plan 模式', extra: '先讨论并制定计划' },
            ],
            selectedKeys: [collaborationMode],
            onClick: ({ key }) => setCollaborationMode(key as 'default' | 'plan'),
          }}
        >
          <button className="chat-composer-action" disabled={disabled} aria-label="设置执行模式">
            <ProfileOutlined aria-hidden="true" />
            <span>{collaborationMode === 'plan' ? 'Plan 模式' : '执行模式'}</span>
          </button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          placement="topLeft"
          menu={{ items: attachmentItems, onClick: handleAttachmentClick }}
        >
          <button className="chat-composer-plus" disabled={disabled} aria-label={remote ? '添加 Skill 或 Agent' : '添加图片、Skill 或 Agent'}>
            <PlusOutlined />
          </button>
        </Dropdown>
        <input
          ref={imageInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          hidden
          onChange={(event) => {
            handleImageSelection(event.target.files);
            event.target.value = '';
          }}
        />
      </div>
      }
      <FolderPickerModal
        apiClient={api}
        title={remote ? '选择电脑上的文件夹' : '选择文件夹'}
        open={folderPickerOpen}
        onClose={() => setFolderPickerOpen(false)}
        onSelect={(path) => {
          void changeWorkspace(null, path);
          setFolderPickerOpen(false);
        }}
      />
    </div>
  );
};

export default MessageInput;
