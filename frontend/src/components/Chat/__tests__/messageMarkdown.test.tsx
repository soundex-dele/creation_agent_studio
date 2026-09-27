// @vitest-environment jsdom
import React, { useContext } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import MessageList, { type ChatMessage } from '../MessageList';
import { ChatConnectionContext } from '../ChatConnectionContext';

const content = [
  '| 项目 | 结果 |',
  '| :--- | ---: |',
  '| **公式** | $x^2$ |',
  '| 转义竖线 | a\\|b |',
  '| 链接 | [详情](https://example.com) |',
].join('\n');

function RemoteMessages({ message }: { message: ChatMessage }) {
  const connection = useContext(ChatConnectionContext);
  return <ChatConnectionContext.Provider value={{ ...connection, remote: true }}>
    <MessageList messages={[message]} />
  </ChatConnectionContext.Provider>;
}

it.each(['reply', 'agentMessage', 'plan', 'remote'] as const)(
  'renders GFM tables with inline formatting in %s content', (kind) => {
    const message: ChatMessage = {
      id: 'table-reply', role: 'assistant', content, created_at: '2026-09-27T00:00:00Z',
      ...(kind === 'agentMessage' || kind === 'plan' ? {
        metadata: { agent: { activity: { items: {
          table: { id: 'table', type: kind, completed: true, text: content },
        } } } },
      } : {}),
    };
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(kind === 'remote'
      ? <RemoteMessages message={message} /> : <MessageList messages={[message]} />);
    const table = host.querySelector('.message-markdown table');
    expect(table).not.toBeNull();
    expect(Array.from(table!.querySelectorAll('th'), cell => cell.textContent)).toEqual(['项目', '结果']);
    expect(table!.querySelectorAll('tbody tr')).toHaveLength(3);
    expect(table!.querySelector('strong')?.textContent).toBe('公式');
    expect(table!.querySelector('.katex')).not.toBeNull();
    expect(table!.textContent).toContain('a|b');
    expect(table!.querySelectorAll('tbody tr')[1].children).toHaveLength(2);
    expect(table!.querySelectorAll('th')[1].style.textAlign).toBe('right');
    if (kind === 'plan') expect(table!.closest('.agent-plan-document')).not.toBeNull();
    if (kind === 'remote') {
      expect(table!.querySelector('a')).toBeNull();
      expect(table!.textContent).toContain('远程访问暂不支持打开文件或链接');
    } else {
      expect(table!.querySelector('a')?.getAttribute('href')).toBe('https://example.com');
    }
  },
);

it('preserves table source in code fences and user messages', () => {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(<MessageList messages={[
    { id: 'code', role: 'assistant', content: `\`\`\`markdown\n${content}\n\`\`\``, created_at: '' },
    { id: 'user', role: 'user', content, created_at: '' },
  ]} />);
  expect(host.querySelector('table')).toBeNull();
  expect(host.querySelector('pre code')?.textContent).toBe(`${content}\n`);
  expect(host.querySelector('.message-user-text')?.textContent).toBe(content);
});
