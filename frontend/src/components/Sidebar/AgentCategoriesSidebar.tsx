import React, { useEffect } from 'react';
import { Menu } from 'antd';
import { useAgentStore } from '@/stores/useAgentStore';
import SidebarCategoryLabel from './SidebarCategoryLabel';

const AgentCategoriesSidebar: React.FC = () => {
  const { categories, selectedCategory, loadCategories, selectCategory } = useAgentStore();

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  const menuItems = [
    { key: 'all', label: '全部智能体' },
    ...categories.map((cat) => ({
      key: cat.slug,
      label: (
        <SidebarCategoryLabel
          label={cat.name}
          count={cat.agent_count}
          countUnit="智能体"
        />
      ),
    })),
  ];

  return (
    <Menu
      mode="inline"
      selectedKeys={[selectedCategory || 'all']}
      items={menuItems}
      onClick={({ key }) => selectCategory(key === 'all' ? null : key)}
    />
  );
};

export default AgentCategoriesSidebar;
