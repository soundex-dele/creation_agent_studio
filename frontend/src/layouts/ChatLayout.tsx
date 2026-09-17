import React from 'react';
import Header from '@/components/Header/Header';

interface ChatLayoutProps {
  children: React.ReactNode;
}

const ChatLayout: React.FC<ChatLayoutProps> = ({ children }) => {
  return (
    <div className="chat-layout flex h-screen flex-col bg-void">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <main className="flex-1 overflow-hidden bg-void">
          {children}
        </main>
      </div>
    </div>
  );
};

export default ChatLayout;
