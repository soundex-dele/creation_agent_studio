import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { publicAddress, resolveTarget, dialTarget, startProxy } from '../network.mjs';

test('rejects private, reserved, mapped, metadata and non-HTTP destinations', async () => {
  for (const ip of ['127.0.0.1', '10.0.0.1', '172.16.0.1', '192.168.1.1', '169.254.169.254', '100.100.100.200', '0.0.0.0', '224.0.0.1', '::1', 'fc00::1', 'fe80::1', '::ffff:127.0.0.1', '168.63.129.16']) assert.equal(publicAddress(ip), false, ip);
  assert.equal(publicAddress('93.184.216.34'), true);
  for (const url of ['file:///etc/passwd', 'ftp://example.com/', 'http://user:pass@example.com/', 'http://localhost/', 'http://0x7f000001/', 'http://[::1]/', 'https://example.com:8080/']) await assert.rejects(resolveTarget(url), /UNSAFE_URL/);
});
test('pins a validated numeric IP without a second DNS resolution', async () => {
  let lookups = 0;
  const resolver = async () => [{ address: ++lookups === 1 ? '93.184.216.34' : '127.0.0.1', family: 4 }];
  const target = await resolveTarget('https://rebind.example/', resolver);
  let options;
  dialTarget(target, value => { options = value; return {}; });
  assert.equal(options.host, '93.184.216.34'); assert.equal(lookups, 1);
  await assert.rejects(resolveTarget('https://rebind.example/', resolver), /UNSAFE_URL/);
  await assert.rejects(resolveTarget('https://mixed.example/', async () => [{ address: '93.184.216.34', family: 4 }, { address: '10.0.0.1', family: 4 }]), /UNSAFE_URL/);
});
function request(proxy, path, auth = true) {
  return new Promise((resolve, reject) => {
    const endpoint = new URL(proxy.settings.server);
    const req = http.request({ host: endpoint.hostname, port: endpoint.port, path,
      headers: auth ? { 'Proxy-Authorization': `Basic ${Buffer.from(`fetch:${proxy.settings.password}`).toString('base64')}` } : {} }, res => {
      res.resume(); res.on('end', () => resolve(res.statusCode));
    }); req.on('error', reject); req.end();
  });
}
test('proxy rejects unauthenticated requests and private redirected/subresource destinations', async () => {
  const proxy = await startProxy({ resolver: async () => [{ address: '192.168.1.5', family: 4 }] });
  try {
    assert.equal(await request(proxy, 'http://example.com/', false), 407);
    assert.equal(await request(proxy, 'http://redirect.example/'), 403);
    assert.equal(await request(proxy, 'http://127.0.0.1/secret'), 403);
    assert.equal(proxy.blocked, true);
  } finally { await proxy.close(); }
});
test('CONNECT uses the validated address and rejects an unsafe subsequent tunnel', async () => {
  const targetServer = net.createServer(socket => socket.on('data', data => socket.write(data)));
  await new Promise(resolve => targetServer.listen(0, '127.0.0.1', resolve));
  const seen = [];
  const proxy = await startProxy({ resolver: async host => [{ address: host === 'good.example' ? '93.184.216.34' : '10.0.0.1', family: 4 }],
    dial: options => { seen.push(options); return net.connect({ host: '127.0.0.1', port: targetServer.address().port }); } });
  async function tunnel(host) {
    const endpoint = new URL(proxy.settings.server);
    const socket = net.connect({ host: endpoint.hostname, port: endpoint.port });
    const reply = await new Promise((resolve, reject) => {
      socket.on('error', reject); socket.once('data', chunk => resolve(chunk.toString()));
      socket.write(`CONNECT ${host}:443 HTTP/1.1\r\nHost: ${host}:443\r\nProxy-Authorization: Basic ${Buffer.from(`fetch:${proxy.settings.password}`).toString('base64')}\r\n\r\n`);
    }); socket.destroy(); return reply;
  }
  try {
    assert.match(await tunnel('good.example'), /200 Connection Established/);
    assert.equal(seen[0].host, '93.184.216.34');
    assert.match(await tunnel('bad.example'), /403 Forbidden/);
    assert.equal(seen.length, 1);
  } finally { await proxy.close(); await new Promise(resolve => targetServer.close(resolve)); }
});

test('HTTP follows an untrusted redirect only through another address check, without forwarding proxy credentials', async () => {
  let headers;
  const targetServer = http.createServer((req, res) => {
    headers = req.headers;
    res.writeHead(302, { Location: 'http://127.0.0.1/secret' }); res.end();
  });
  await new Promise(resolve => targetServer.listen(0, '127.0.0.1', resolve));
  const seen = [];
  const proxy = await startProxy({ resolver: async () => [{ address: '93.184.216.34', family: 4 }],
    dial: options => { seen.push(options); return net.connect({ host: '127.0.0.1', port: targetServer.address().port }); } });
  try {
    assert.equal(await request(proxy, 'http://good.example/article'), 302);
    assert.equal(headers.host, 'good.example');
    assert.equal(headers['proxy-authorization'], undefined);
    assert.equal(seen[0].host, '93.184.216.34');
    assert.equal(await request(proxy, 'http://127.0.0.1/secret'), 403);
    assert.equal(seen.length, 1);
  } finally { await proxy.close(); await new Promise(resolve => targetServer.close(resolve)); }
});
