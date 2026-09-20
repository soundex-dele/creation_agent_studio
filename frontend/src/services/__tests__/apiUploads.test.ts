import { createServer, type Server } from 'node:http';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('antd', () => ({ message: { error: vi.fn() } }));
vi.mock('../authSession', () => ({
  clearAuthSession: vi.fn(),
  getAccessToken: () => 'upload-test-token',
  refreshAccessToken: vi.fn(),
}));

import { api } from '../api';

interface CapturedRequest {
  contentType: string;
  authorization: string;
  body: string;
}

describe('API file uploads', () => {
  let server: Server;
  let url: string;

  beforeAll(async () => {
    server = createServer(async (request, response) => {
      const chunks: Buffer[] = [];
      for await (const chunk of request) chunks.push(Buffer.from(chunk));
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({
        contentType: request.headers['content-type'],
        authorization: request.headers.authorization,
        body: Buffer.concat(chunks).toString('base64'),
      }));
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('Missing test server port');
    url = `http://127.0.0.1:${address.port}/assets`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  });

  it.each(['post', 'patch', 'put'] as const)('sends %s file bodies as multipart with intact bytes', async (method) => {
    const bytes = new Uint8Array([0, 137, 80, 78, 71, 255, 13, 10]);
    const data = new FormData();
    data.append('file', new Blob([bytes], { type: 'image/png' }), 'cover.png');
    data.append('folder_id', 'folder-123');

    const captured = await api[method]<CapturedRequest>(url, data);

    expect(captured.contentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(captured.authorization).toBe('Bearer upload-test-token');
    const received = await new Response(Buffer.from(captured.body, 'base64'), {
      headers: { 'Content-Type': captured.contentType },
    }).formData();
    const file = received.get('file') as File;
    expect(file.name).toBe('cover.png');
    expect(file.type).toBe('image/png');
    expect(new Uint8Array(await file.arrayBuffer())).toEqual(bytes);
    expect(received.get('folder_id')).toBe('folder-123');
  });

  it('keeps ordinary object requests encoded as JSON', async () => {
    const payload = { name: '素材工程', description: '上传测试' };
    const captured = await api.post<CapturedRequest>(url, payload);

    expect(captured.contentType).toBe('application/json');
    expect(JSON.parse(Buffer.from(captured.body, 'base64').toString())).toEqual(payload);
  });
});
