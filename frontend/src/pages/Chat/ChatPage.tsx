import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChatContainer } from '@/components/Chat';

const ChatPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const conversationId = searchParams.get('conversation') || null;

  return (
    <div className="chat-application-layout">
      <div className="chat-application-main">
        <ChatContainer
          conversationId={conversationId}
          createOnFirstSend
          onConversationCreated={(id) => setSearchParams((current) => {
            const next = new URLSearchParams(current);
            next.set('conversation', id);
            return next;
          }, { replace: true })}
        />
      </div>
    </div>
  );
};

export default ChatPage;
