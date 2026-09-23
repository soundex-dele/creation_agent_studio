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
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useChatConnection } from './ChatConnectionContext';
import { loadConnectionCollection } from '@/services/chatConnection';
import { useAgentStore, type Agent } from '@/stores/useAgentStore';
import { useProjectStore, type Project } from '@/stores/useProjectStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
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
  placeholder?: string;
  currentAgent?: ComposerAgent | null;
  workspaceLocked?: boolean;
  mode?: 'default' | 'study' | 'document';
}

const MessageInput: React.FC<MessageInputProps> = ({
  value: controlledValue,
  onValueChange,
  onSendMessage,
  disabled = false,
  placeholder = '输入消息...',
  currentAgent = null,
  workspaceLocked = false,
  mode = 'default',
}) => {
  const { api, remote } = useChatConnection();
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
  const defaultPermissionMode = usePreferencesStore((state) => state.defaultPermissionMode);
  const sendShortcut = usePreferencesStore((state) => state.sendShortcut);
  const [permissionMode, setPermissionMode] = useState<'default' | 'allow_all'>(defaultPermissionMode);
  const [collaborationMode, setCollaborationMode] = useState<'default' | 'plan'>('default');
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const { projects, loadProjects } = useProjectStore();
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
      loadConnectionCollection<ComposerAgent>(api, '/agents/')
        .then(result => { if (!cancelled) setRemoteAgents(result); })
        .catch(() => { if (!cancelled) setRemoteAgents([]); });
    } else {
      void loadProjects();
      void loadAgents();
    }
    api.get<{ skills: SkillOption[] }>('/conversations/composer-options/')
      .then((response) => { if (!cancelled) setSkills(response.skills || []); })
      .catch(() => { if (!cancelled) setSkills([]); });
    return () => { cancelled = true; };
  }, [loadAgents, loadProjects, mode, api, remote]);

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
  useEffect(autosizeTextarea, [content]);

  const handleSend = async () => {
    if ((content.trim() || selectedImages.length > 0) && !disabled && !isSubmitting) {
      setIsSubmitting(true);
      try {
        await onSendMessage(content.trim(), {
          projectId: selectedProject?.id,
          workingDirectory: selectedSystemDirectory || undefined,
          agentId: selectedAgent?.id ?? null,
          agent: selectedAgent,
          permissionMode,
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

  const workspaceItems: MenuProps['items'] = [
    { key: 'none', label: '不使用工作空间' },
    { key: 'system-directory', label: '选择系统目录…' },
    ...(projects.length
      ? projects.map((project) => ({ key: String(project.id), label: project.title }))
      : [{ key: 'empty', disabled: true, label: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工作空间" /> }]),
  ];

  const permissionItems: MenuProps['items'] = [
    { key: 'default', label: '默认权限', extra: '按需确认高风险工具' },
    { key: 'allow_all', label: '完全控制', extra: '完整文件访问，无需逐次确认' },
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
          disabled={disabled}
          rows={1}
          className="chat-input-textarea"
        />
        <button
          type="button"
          className="chat-send-btn"
          onClick={() => void handleSend()}
          disabled={(!content.trim() && selectedImages.length === 0) || disabled || isSubmitting}
          aria-label="发送消息"
        >
          <SendOutlined />
        </button>
      </div>

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
              setSelectedSystemDirectory('');
              setSelectedProject(
                key === 'none' ? null
                  : projects.find((project) => String(project.id) === key) || null,
              );
            },
          }}
        >
          <button className="chat-composer-action" disabled={disabled || workspaceLocked || remote}>
            <FolderOutlined />
            <span>{selectedProject?.title
              || (selectedSystemDirectory ? selectedSystemDirectory : '选择工作空间')}</span>
          </button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          menu={{
            items: permissionItems,
            selectedKeys: [permissionMode],
            onClick: ({ key }) => setPermissionMode(key as 'default' | 'allow_all'),
          }}
        >
          <button className="chat-composer-action" disabled={disabled}>
            <SafetyCertificateOutlined />
            <span>{permissionMode === 'default' ? '默认权限' : '完全控制'}</span>
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
        open={folderPickerOpen}
        onClose={() => setFolderPickerOpen(false)}
        onSelect={(path) => {
          setSelectedSystemDirectory(path);
          setSelectedProject(null);
          setFolderPickerOpen(false);
        }}
      />
    </div>
  );
};

export default MessageInput;
