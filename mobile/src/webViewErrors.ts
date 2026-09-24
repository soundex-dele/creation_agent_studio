export function isRecoverableWebViewError(
  platform: string,
  code: number,
): boolean {
  return platform === 'android'
    ? [-2, -6, -7, -8].includes(code)
    : [-1001, -1003, -1004, -1005, -1009].includes(code);
}

export function describeWebViewError(
  platform: string,
  code: number,
  description: string,
  url: string,
): string {
  if (platform === 'android') {
    if (code === -6) {
      let loopback = false;
      try {
        loopback = ['localhost', '127.0.0.1', '[::1]'].includes(
          new URL(url).hostname,
        );
      } catch {
        /* Keep the connection explanation for an invalid URL. */
      }
      return loopback
        ? '无法连接服务器（-6）。手机上的本机地址指向手机自身；访问电脑服务请使用电脑的局域网 IP，或恢复 USB 端口转发。'
        : '无法连接服务器（-6）。请确认服务器已启动、网址及端口正确，并且手机能够访问该服务器。';
    }
    if (code === -2) return '无法解析服务器地址（-2），请检查网址和网络连接。';
    if (code === -7) return '连接在传输中断开（-7），请重新加载。';
    if (code === -8) return '连接服务器超时（-8），请稍后重新加载。';
    if (code === -11)
      return '无法建立安全连接（-11），请检查服务器的 HTTPS 配置和证书。';
  }
  return description || '网络请求失败，请重新加载。';
}

/** Show the requested destination without exposing tokens in its query string. */
export function connectionAddress(url: string): string {
  try {
    const address = new URL(url);
    return `${address.origin}${address.pathname}`;
  } catch {
    return '';
  }
}
