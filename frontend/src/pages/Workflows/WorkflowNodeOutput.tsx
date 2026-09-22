import { useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { Button, Modal, Typography } from 'antd';
import { DownOutlined, ExpandOutlined, FileTextOutlined, UpOutlined } from '@ant-design/icons';

const PREVIEW_HEIGHT = 240;

export default function WorkflowNodeOutput({ output, name, running }: {
  output: string;
  name: string;
  running: boolean;
}) {
  const contentId = useId();
  const textRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useLayoutEffect(() => {
    const element = textRef.current;
    if (!element) return;
    const measure = () => setOverflowing(element.getBoundingClientRect().height > PREVIEW_HEIGHT);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [output]);

  const collapse = () => {
    setExpanded(false);
    // Keep the node in view when collapsing from the end of a long output.
    if (headerRef.current && headerRef.current.getBoundingClientRect().top < 0) {
      headerRef.current.scrollIntoView({ block: 'center' });
    }
  };
  const clipped = overflowing && !expanded;

  return (
    <div className="workflow-execution-output">
      <div className="workflow-execution-output-header" ref={headerRef}>
        <div className="workflow-execution-output-label"><FileTextOutlined aria-hidden />节点输出</div>
        <div className="workflow-execution-output-controls">
          {(overflowing || expanded) && <Button type="text" size="small"
            icon={expanded ? <UpOutlined aria-hidden /> : <DownOutlined aria-hidden />}
            aria-expanded={expanded} aria-controls={contentId}
            onClick={() => expanded ? collapse() : setExpanded(true)}>
            {expanded ? '收起' : '展开输出'}
          </Button>}
          <Button type="text" size="small" icon={<ExpandOutlined aria-hidden />}
            onClick={() => setModalOpen(true)}>大窗查看</Button>
        </div>
      </div>
      <div id={contentId} role="region" aria-label={`${name}的节点输出`}
        className={`workflow-execution-output-preview${expanded ? ' is-expanded' : ''}${clipped ? ' is-clipped' : ''}${running ? ' is-running' : ''}`}
        style={{ '--output-preview-height': `${PREVIEW_HEIGHT}px` } as CSSProperties}>
        <div ref={textRef} className="workflow-execution-output-text">{output}</div>
      </div>
      {(clipped || expanded) && <div className="workflow-execution-output-footer">
        <span>{expanded ? '已展开全部输出' : running ? '实时预览最新输出' : '当前为部分预览'}</span>
        <Button type="link" size="small" aria-expanded={expanded} aria-controls={contentId}
          onClick={() => expanded ? collapse() : setExpanded(true)}>
          {expanded ? '收起输出' : '展开全部'}
        </Button>
      </div>}
      <Modal title={`${name} · 节点输出`} open={modalOpen} onCancel={() => setModalOpen(false)}
        footer={null} width="min(1200px, 96vw)" style={{ top: '4vh' }}
        className="workflow-node-output-modal" destroyOnHidden>
        <div className="workflow-node-output-modal-toolbar">
          <span>{running ? '输出实时更新中' : '完整输出'}</span>
          <Typography.Text copyable={{ text: output }}>复制全文</Typography.Text>
        </div>
        <div className="workflow-node-output-modal-content" tabIndex={0} role="region"
          aria-label={`${name}的完整节点输出`}>{output}</div>
      </Modal>
    </div>
  );
}
