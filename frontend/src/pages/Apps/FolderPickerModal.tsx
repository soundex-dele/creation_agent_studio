import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Button, Input, Spin, List, Typography, message } from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  FolderOpenOutlined,
  FolderOutlined,
} from '@ant-design/icons';
import { api } from '@/services/api';

interface DirEntry {
  name: string;
  path: string;
}

interface ListResp {
  path: string;       // '' when viewing roots
  parent: string;     // '' when there is no parent (roots / drive root)
  roots: DirEntry[];  // populated only when viewing roots
  dirs: DirEntry[];   // immediate subdirectories of `path`
}

interface Props {
  apiClient?: typeof api;
  title?: string;
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
}

/**
 * Server-side folder browser. The browser can't read real filesystem paths, so
 * we navigate the server filesystem through the backend
 * and hand the picked real absolute path back to the caller.
 *
 * Click a row to descend; "选择此文件夹" confirms the folder currently in view.
 */
const FolderPickerModal: React.FC<Props> = ({ apiClient = api, title = '选择文件夹', open, onClose, onSelect }) => {
  const [data, setData] = useState<ListResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [jump, setJump] = useState('');  // manual path entry for power users
  const requestId = useRef(0);

  const load = useCallback(async (p: string) => {
    const id = ++requestId.current;
    setLoading(true);
    setData(null);
    try {
      const resp = await apiClient.get<ListResp>('/apps/runtime-files/list/', { path: p });
      if (id !== requestId.current) return;
      setData(resp);
      setJump(resp.path);
    } catch (e: any) {
      if (id !== requestId.current) return;
      message.error(e.response?.data?.detail || '读取目录失败');
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [apiClient]);

  // Reset to roots each time the modal opens.
  useEffect(() => {
    if (open) {
      setJump('');
      void load('');
    }
    return () => { requestId.current += 1; };
  }, [open, load]);

  const viewingRoots = !data?.path;
  const items = viewingRoots ? data?.roots ?? [] : data?.dirs ?? [];

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      width={560}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="select"
          type="primary"
          icon={<CheckOutlined />}
          disabled={loading || !data?.path}
          onClick={() => data?.path && onSelect(data.path)}
        >
          选择此文件夹
        </Button>,
      ]}
    >
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Input
          aria-label="文件夹路径"
          prefix={<FolderOpenOutlined />}
          placeholder="直接输入路径，回车跳转"
          value={jump}
          onChange={(e) => setJump(e.target.value)}
          onPressEnter={() => load(jump.trim())}
        />
        <Button
          icon={<ArrowLeftOutlined />}
          disabled={!data?.parent}
          onClick={() => data?.parent && load(data.parent)}
        >
          上一级
        </Button>
      </div>

      <div style={{ minHeight: 280 }}>
        {loading ? (
          <div style={{ textAlign: 'center', paddingTop: 100 }}><Spin /></div>
        ) : (
          <List
            size="small"
            locale={{ emptyText: viewingRoots ? '没有可用磁盘' : '没有子文件夹' }}
            dataSource={items}
            renderItem={(item) => (
              <List.Item style={{ cursor: 'pointer' }} onClick={() => load(item.path)}>
                <List.Item.Meta
                  avatar={<FolderOutlined style={{ fontSize: 18, color: '#faad14' }} />}
                  title={<Typography.Text>{item.name}</Typography.Text>}
                />
              </List.Item>
            )}
          />
        )}
      </div>

      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        当前：{data?.path || '（我的电脑）'}
      </Typography.Text>
    </Modal>
  );
};

export default FolderPickerModal;
