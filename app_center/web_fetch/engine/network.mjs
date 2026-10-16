import http from 'node:http';
import net from 'node:net';
import { lookup } from 'node:dns/promises';
import { randomBytes } from 'node:crypto';
import ipaddr from 'ipaddr.js';

export function publicAddress(value) {
  try {
    const address = ipaddr.process(value);
    return address.range() === 'unicast' && address.toString() !== '168.63.129.16';
  } catch { return false; }
}

export function parseTarget(value) {
  const url = new URL(value);
  const host = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '');
  const port = Number(url.port || (url.protocol === 'https:' ? 443 : 80));
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !host
      || ![80, 443].includes(port) || host === 'localhost' || /\.(localhost|local)$/i.test(host)) {
    throw new Error('UNSAFE_URL');
  }
  return { url, host, port };
}

export async function resolveTarget(value, resolver = lookup) {
  const target = parseTarget(value);
  const addresses = net.isIP(target.host) ? [{ address: target.host, family: net.isIP(target.host) }]
    : await resolver(target.host, { all: true, verbatim: true });
  // Reject mixed public/private answers too. The actual connection uses this
  // numeric address, never a second hostname lookup (including CONNECT tunnels).
  if (!addresses.length || addresses.some(item => !publicAddress(item.address))) throw new Error('UNSAFE_URL');
  return { ...target, address: addresses[0].address, family: addresses[0].family };
}

export function dialTarget(target, dial = net.connect) {
  return dial({ host: target.address, family: target.family, port: target.port });
}

export async function startProxy({ resolver = lookup, dial = net.connect, maxBytes = 40 * 1024 * 1024 } = {}) {
  const password = randomBytes(24).toString('hex');
  const authorization = `Basic ${Buffer.from(`fetch:${password}`).toString('base64')}`;
  const sockets = new Set();
  let bytes = 0;
  let closed = false;
  let blocked = false;
  let limited = false;
  let requests = 0;
  function track(socket) {
    sockets.add(socket);
    socket.on('error', () => {});
    socket.on('close', () => sockets.delete(socket));
    socket.setTimeout(30_000, () => socket.destroy());
    if (closed) socket.destroy();
    return socket;
  }
  function count(chunk) {
    bytes += chunk.length;
    if (bytes > maxBytes) {
      limited = true;
      for (const socket of sockets) socket.destroy();
    }
  }
  function permitted(req, socket) {
    if (req.headers['proxy-authorization'] !== authorization) {
      socket.end('HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="fetch"\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
      return false;
    }
    if (closed || limited || ++requests > 500) {
      limited = true;
      socket.destroy();
      return false;
    }
    return true;
  }
  const server = http.createServer(async (req, res) => {
    if (!permitted(req, req.socket)) return;
    try {
      const target = await resolveTarget(req.url, resolver);
      if (closed) return req.destroy();
      if (target.url.protocol !== 'http:') throw new Error('UNSAFE_URL');
      const headers = { ...req.headers, host: target.url.host, connection: 'close' };
      for (const name of ['proxy-authorization', 'proxy-connection', 'upgrade']) delete headers[name];
      const agent = new http.Agent({ keepAlive: false });
      agent.createConnection = () => track(dialTarget(target, dial));
      const upstream = http.request({ method: req.method, host: target.address, port: target.port,
        path: target.url.pathname + target.url.search, headers, agent,
      }, response => {
        res.writeHead(response.statusCode, response.headers);
        response.on('data', count);
        response.on('error', () => res.destroy());
        response.pipe(res);
      });
      upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
      res.on('close', () => { upstream.destroy(); agent.destroy(); });
      req.on('error', () => upstream.destroy());
      req.pipe(upstream);
    } catch (error) {
      if (error.message === 'UNSAFE_URL') blocked = true;
      res.writeHead(403); res.end();
    }
  });
  server.on('connect', async (req, client, head) => {
    if (!permitted(req, client)) return;
    try {
      // An authority, not a URL supplied by an untrusted proxy client.
      if (!/^(?:\[[0-9a-f:]+\]|[a-z0-9.-]+):443$/i.test(req.url)) throw new Error('UNSAFE_URL');
      const target = await resolveTarget(`https://${req.url}/`, resolver);
      if (closed || client.destroyed) return client.destroy();
      const upstream = track(dialTarget(target, dial));
      upstream.on('connect', () => {
        client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        if (head.length) upstream.write(head);
        upstream.on('data', count);
        upstream.pipe(client); client.pipe(upstream);
      });
      upstream.on('error', () => client.destroy());
      client.on('close', () => upstream.destroy());
      upstream.on('close', () => client.destroy());
    } catch (error) {
      if (error.message === 'UNSAFE_URL') blocked = true;
      client.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
    }
  });
  server.on('connection', track);
  server.on('clientError', (_error, socket) => socket.destroy());
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return {
    settings: { server: `http://127.0.0.1:${server.address().port}`, username: 'fetch', password },
    get blocked() { return blocked; },
    get limited() { return limited; },
    async close() {
      closed = true;
      for (const socket of sockets) socket.destroy();
      await new Promise(resolve => server.close(resolve));
    },
  };
}
