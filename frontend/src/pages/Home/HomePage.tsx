import React from 'react';
import { ArrowRightOutlined, AppstoreOutlined, MessageOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import './HomePage.css';

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const username = useAuthStore((state) => state.user?.username);

  return (
    <div className="home-page animate-fade-in">
      <section className="home-hero">
        <span className="home-eyebrow">AGENT STUDIO</span>
        <h1>{username ? `${username}，欢迎回来` : '欢迎回来'}</h1>
        <p>从左侧选择一个应用开始处理任务，或进入应用中心发现更多工具。</p>
        <div className="home-actions">
          <Button type="primary" size="large" icon={<MessageOutlined />} onClick={() => navigate('/chat')}>
            开始对话
          </Button>
          <Button size="large" icon={<AppstoreOutlined />} onClick={() => navigate('/apps')}>
            浏览全部应用 <ArrowRightOutlined />
          </Button>
        </div>
      </section>
      <section className="home-guide" aria-label="首页使用提示">
        <div><span>1</span><strong>选择应用</strong><p>从侧边栏打开常用工具</p></div>
        <div><span>2</span><strong>完成任务</strong><p>按应用指引提交你的需求</p></div>
        <div><span>3</span><strong>随时配置</strong><p>调整首页展示和应用顺序</p></div>
      </section>
    </div>
  );
};

export default HomePage;
