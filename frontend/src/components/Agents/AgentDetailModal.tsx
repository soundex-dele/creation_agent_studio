import React, { useEffect, useRef, useState } from 'react';
import { Spin, message } from 'antd';
import { useNavigate } from 'react-router-dom';
import { api } from '@/services/api';
import { useConversationStore } from '@/stores/useConversationStore';
import '../Modal/Modal.css';

const AGENT_ICON_GRADIENTS = [
  'icon-gradient-1', 'icon-gradient-2', 'icon-gradient-3',
  'icon-gradient-4', 'icon-gradient-5', 'icon-gradient-6',
];

interface AgentDetailModalProps {
  agentId: number | null;
  open: boolean;
  onClose: () => void;
}

const AgentDetailModal: React.FC<AgentDetailModalProps> = ({
  agentId,
  open,
  onClose,
}) => {
  const [agent, setAgent] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const createConversation = useConversationStore((s) => s.createConversation);

  useEffect(() => {
    if (open && agentId) {
      setLoading(true);
      api
        .get(`/agents/${agentId}/`)
        .then((data) => setAgent(data))
        .catch(() => message.error('加载智能体失败'))
        .finally(() => setLoading(false));
    }
    if (!open) {
      setAgent(null);
    }
  }, [open, agentId]);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleStartConversation = async () => {
    if (!agentId || !agent) return;
    setIsStarting(true);
    try {
      const conversation = await createConversation(agent.name, agentId);
      message.success('对话已创建');
      onClose();
      navigate(`/chat?conversation=${encodeURIComponent(conversation.id)}`);
    } catch (error: any) {
      message.error(error.message || '创建对话失败');
    } finally {
      setIsStarting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-overlay active" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="modal">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Spin size="large" />
          </div>
        ) : agent ? (
          <>
            <div className="modal-header">
              <div className={`modal-icon ${AGENT_ICON_GRADIENTS[(agentId || 0) % 6]}`}>
                {agent.icon || '🤖'}
              </div>
              <div className="modal-header-text">
                <h2>{agent.name}</h2>
                <p>{agent.category?.name || '智能体'}</p>
              </div>
              <button className="modal-close" onClick={onClose}>✕</button>
            </div>
            <div className="modal-body">
              <div className="modal-section">
                <div className="modal-section-title">描述</div>
                <div className="modal-section-content">{agent.description}</div>
              </div>
              <div className="modal-section">
                <div className="modal-section-title">系统提示词</div>
                <div className="modal-prompt-block">
                  <pre>{agent.system_prompt}</pre>
                </div>
              </div>
              <div className="modal-actions">
                <button className="btn-primary" onClick={handleStartConversation} disabled={isStarting}>
                  {isStarting ? '创建中...' : '开始对话'}
                </button>
                <button className="btn-secondary" onClick={onClose}>关闭</button>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default AgentDetailModal;
