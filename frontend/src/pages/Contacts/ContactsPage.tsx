import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Avatar,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  message,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  ContactsOutlined,
  DeleteOutlined,
  EditOutlined,
  MailOutlined,
  MinusCircleOutlined,
  PhoneOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import {
  createContact,
  deleteContact,
  getAddressBook,
  listContacts,
  updateContact,
} from '@/services/contacts';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { AddressBook, Contact, ContactInput, ContactMethod } from '@/types/contact';
import './ContactsPage.css';


const methodLabels: Record<ContactMethod['kind'], string> = {
  phone: '电话',
  email: '邮箱',
  wechat: '微信',
  other: '其他',
};

const blankMethod: ContactMethod = {
  kind: 'phone',
  label: '',
  value: '',
  is_primary: false,
};

function primaryMethod(contact: Contact, kind: ContactMethod['kind']) {
  const candidates = contact.methods.filter((item) => item.kind === kind);
  return candidates.find((item) => item.is_primary) ?? candidates[0];
}

function errorText(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : fallback;
}

export default function ContactsPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const organizations = useOrganizationStore((state) => state.organizations);
  const currentRole = organizations.find((item) => item.id === organizationId)?.role;
  const canWrite = ['developer', 'admin', 'owner'].includes(currentRole ?? '');
  const canDelete = ['admin', 'owner'].includes(currentRole ?? '');

  const [form] = Form.useForm<ContactInput>();
  const [book, setBook] = useState<AddressBook | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [effectiveQuery, setEffectiveQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Contact | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setEffectiveQuery(query.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const reload = useCallback(async () => {
    if (!organizationId || !applicationId) return;
    setLoading(true);
    try {
      const [bookData, pageData] = await Promise.all([
        getAddressBook(organizationId, applicationId),
        listContacts(organizationId, applicationId, {
          q: effectiveQuery || undefined,
          page,
          page_size: 20,
          ordering: 'name',
        }),
      ]);
      setBook(bookData);
      setContacts(pageData.results);
      setCount(pageData.count);
    } catch (error) {
      message.error(errorText(error, '加载通讯录失败'));
    } finally {
      setLoading(false);
    }
  }, [applicationId, effectiveQuery, organizationId, page]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openCreate = () => {
    setEditing(null);
    form.setFieldsValue({
      name: '',
      company: '',
      department: '',
      job_title: '',
      avatar: '',
      notes: '',
      methods: [{ ...blankMethod }],
    });
    setDrawerOpen(true);
  };

  const openEdit = (contact: Contact) => {
    setEditing(contact);
    form.setFieldsValue({
      name: contact.name,
      company: contact.company,
      department: contact.department,
      job_title: contact.job_title,
      avatar: contact.avatar,
      notes: contact.notes,
      methods: contact.methods.length ? contact.methods : [{ ...blankMethod }],
    });
    setDrawerOpen(true);
  };

  const save = async () => {
    if (!organizationId || !applicationId) return;
    try {
      const values = await form.validateFields();
      const input: ContactInput = {
        ...values,
        methods: (values.methods ?? []).filter((item) => item.value?.trim()),
      };
      setSaving(true);
      if (editing) {
        await updateContact(organizationId, applicationId, editing, input);
        message.success('联系人已更新');
      } else {
        await createContact(organizationId, applicationId, input);
        message.success('联系人已添加');
      }
      setDrawerOpen(false);
      await reload();
    } catch (error) {
      if (typeof error === 'object' && error !== null && 'errorFields' in error) return;
      message.error(errorText(error, '保存联系人失败'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (contact: Contact) => {
    if (!organizationId || !applicationId) return;
    Modal.confirm({
      title: `删除联系人“${contact.name}”？`,
      content: '联系人将从通讯录中移除。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteContact(organizationId, applicationId, contact.id);
          message.success('联系人已删除');
          if (contacts.length === 1 && page > 1) setPage(page - 1);
          else await reload();
        } catch (error) {
          message.error(errorText(error, '删除联系人失败'));
        }
      },
    });
  };

  const subtitle = useMemo(() => {
    if (!book) return '组织联系人管理';
    return `${book.name} · 共 ${book.contact_count} 位联系人`;
  }, [book]);

  if (!organizationId || !applicationId) {
    return <Empty description="请选择组织后打开通讯录" />;
  }

  return (
    <div className="contacts-page">
      <header className={`contacts-header ${showApplicationHeader ? '' : 'contacts-header--compact'}`}>
        {showApplicationHeader && <Space align="center" size={14}>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
            应用中心
          </Button>
          <div className="contacts-app-icon"><ContactsOutlined /></div>
          <div>
            <Typography.Title level={2}>通讯录</Typography.Title>
            <Typography.Text type="secondary">{subtitle}</Typography.Text>
          </div>
        </Space>}
        {canWrite && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            添加联系人
          </Button>
        )}
      </header>

      <section className="contacts-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索姓名、公司、部门或联系方式"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </section>

      <section className="contacts-content">
        <Spin spinning={loading}>
          <List
            dataSource={contacts}
            locale={{ emptyText: <Empty description={effectiveQuery ? '没有匹配的联系人' : '还没有联系人'} /> }}
            pagination={count > 20 ? {
              current: page,
              pageSize: 20,
              total: count,
              showSizeChanger: false,
              onChange: setPage,
            } : false}
            renderItem={(contact) => {
              const phone = primaryMethod(contact, 'phone');
              const email = primaryMethod(contact, 'email');
              return (
                <List.Item
                  className="contact-row"
                  actions={[
                    canWrite ? (
                      <Button key="edit" type="text" icon={<EditOutlined />} onClick={() => openEdit(contact)}>
                        编辑
                      </Button>
                    ) : null,
                    canDelete ? (
                      <Button key="delete" danger type="text" icon={<DeleteOutlined />} onClick={() => remove(contact)}>
                        删除
                      </Button>
                    ) : null,
                  ].filter(Boolean)}
                >
                  <List.Item.Meta
                    avatar={<Avatar size={44} src={contact.avatar}>{contact.name.slice(0, 1)}</Avatar>}
                    title={
                      <Space wrap>
                        <span>{contact.name}</span>
                        {contact.job_title && <Tag>{contact.job_title}</Tag>}
                      </Space>
                    }
                    description={
                      <div className="contact-summary">
                        <span>{[contact.company, contact.department].filter(Boolean).join(' · ') || '未填写公司和部门'}</span>
                        <Space wrap size={16}>
                          {phone && <span><PhoneOutlined /> {phone.value}</span>}
                          {email && <span><MailOutlined /> {email.value}</span>}
                        </Space>
                      </div>
                    }
                  />
                </List.Item>
              );
            }}
          />
        </Spin>
      </section>

      <Drawer
        title={editing ? '编辑联系人' : '添加联系人'}
        width={560}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={<Space><Button onClick={() => setDrawerOpen(false)}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></Space>}
      >
        <Form form={form} layout="vertical" requiredMark="optional">
          <div className="contact-form-grid">
            <Form.Item name="name" label="姓名" rules={[{ required: true, whitespace: true, message: '请输入姓名' }]}>
              <Input maxLength={120} autoFocus />
            </Form.Item>
            <Form.Item name="job_title" label="职位"><Input maxLength={160} /></Form.Item>
            <Form.Item name="company" label="公司"><Input maxLength={160} /></Form.Item>
            <Form.Item name="department" label="部门"><Input maxLength={160} /></Form.Item>
          </div>
          <Form.Item name="avatar" label="头像地址" rules={[{ type: 'url', warningOnly: true }]}>
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item label="联系方式">
            <Form.List name="methods">
              {(fields, { add, remove }) => (
                <Space direction="vertical" className="contact-method-list">
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline" className="contact-method-row">
                      <Form.Item name={[field.name, 'kind']} rules={[{ required: true }]}>
                        <Select options={Object.entries(methodLabels).map(([value, label]) => ({ value, label }))} />
                      </Form.Item>
                      <Form.Item name={[field.name, 'label']}><Input placeholder="标签" maxLength={40} /></Form.Item>
                      <Form.Item name={[field.name, 'value']} rules={[{ required: true, whitespace: true, message: '请输入联系方式' }]}>
                        <Input placeholder="号码、邮箱或账号" maxLength={255} />
                      </Form.Item>
                      <Button type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ ...blankMethod })}>
                    添加联系方式
                  </Button>
                </Space>
              )}
            </Form.List>
          </Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={5} maxLength={4000} showCount /></Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
