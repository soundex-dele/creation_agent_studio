import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Dropdown, Empty } from 'antd';
import type { MenuProps } from 'antd';
import {
  CloseOutlined,
  FolderOutlined,
  PlusOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { api } from '@/services/api';
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
  onSendMessage: (content: string, context: ComposerContext) => void;
  disabled?: boolean;
  placeholder?: string;
  currentAgent?: ComposerAgent | null;
  workspaceLocked?: boolean;
}

const MessageInput: React.FC<MessageInputProps> = ({
  value: controlledValue,
  onValueChange,
  onSendMessage,
  disabled = false,
  placeholder = '输入消息...',
  currentAgent = null,
  workspaceLocked = false,
}) => {
  const [internalValue, setInternalValue] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [selectedSystemDirectory, setSelectedSystemDirectory] = useState('');
  const [folderPickerOpen, setFolderPickerOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<ComposerAgent | null>(currentAgent);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const defaultPermissionMode = usePreferencesStore((state) => state.defaultPermissionMode);
  const sendShortcut = usePreferencesStore((state) => state.sendShortcut);
  const [permissionMode, setPermissionMode] = useState<'default' | 'allow_all'>(defaultPermissionMode);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const { projects, loadProjects } = useProjectStore();
  const { agents, loadAgents } = useAgentStore();

  useEffect(() => {
    void loadProjects();
    void loadAgents();
    api.get<{ skills: SkillOption[] }>('/conversations/composer-options/')
      .then((response) => setSkills(response.skills || []))
      .catch(() => setSkills([]));
  }, [loadAgents, loadProjects]);

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

  const handleSend = () => {
    if (content.trim() && !disabled) {
      onSendMessage(content.trim(), {
        projectId: selectedProject?.id,
        workingDirectory: selectedSystemDirectory || undefined,
        agentId: selectedAgent?.id ?? null,
        agent: selectedAgent,
        permissionMode,
        skillNames: selectedSkills,
      });
      setContent('');
      setSelectedSkills([]);
    }
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
    { key: 'allow_all', label: '自动允许', extra: '工具无需逐次确认' },
  ];

  const attachmentItems = useMemo<MenuProps['items']>(() => [
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
  ], [agents, skills]);

  const handleAttachmentClick: MenuProps['onClick'] = ({ key }) => {
    if (key.startsWith('skill:')) {
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
      handleSend();
    }
  };

  return (
    <div className={`chat-input-box ${isFocused ? 'chat-input-box--focused' : ''}`}>
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
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!content.trim() || disabled}
        >
          <SendOutlined />
        </button>
      </div>

      {(selectedAgent || selectedSkills.length > 0) && (
        <div className="chat-composer-attachments">
          {selectedAgent && (
            <span className="chat-composer-chip">
              <RobotOutlined /> {selectedAgent.name}
              <button onClick={() => setSelectedAgent(null)} aria-label="移除 Agent"><CloseOutlined /></button>
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

      <div className="chat-composer-toolbar">
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
          <button className="chat-composer-action" disabled={disabled || workspaceLocked}>
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
            <span>{permissionMode === 'default' ? '默认权限' : '自动允许'}</span>
          </button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          placement="topLeft"
          menu={{ items: attachmentItems, onClick: handleAttachmentClick }}
        >
          <button className="chat-composer-plus" disabled={disabled} aria-label="添加 Skill 或 Agent">
            <PlusOutlined />
          </button>
        </Dropdown>
      </div>
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
