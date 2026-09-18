# Agent Studio Mobile

Android 和 iOS 共用的 React Native WebView 外壳。App 只加载受信任的 Agent
Studio 网页，业务逻辑继续由现有 React 前端和 Django API 提供。

## 功能

- Android WebView 与 iOS WKWebView 共用一套 TypeScript 外壳
- 同源 Cookie 会话、网页上传控件和媒体播放
- 仅允许配置的业务域名及 SSO 域名留在 WebView
- 普通网页、电话和邮件链接交给系统应用打开
- Android 物理返回键和 iOS 前进/后退手势
- 联网检测、原生加载态、错误态与重新加载
- `agentstudio://open?path=/apps/123` 自定义深链接
- 网页到原生的外链、系统分享和重载桥接
- 浅色/深色模式及原生安全区域适配

## 服务地址配置

编辑 `src/appConfig.ts`：

```ts
const PRODUCTION_APP_ORIGIN = 'https://studio.example.com';
```

正式发布前必须改成真实 HTTPS 域名。网页和 `/api/v1` 应部署在同一 Origin，
以继续使用现有 HttpOnly、Secure、SameSite=Strict Refresh Cookie。

开发模式默认地址：

- Android 模拟器：`http://10.0.2.2:3030`
- iOS 模拟器：`http://localhost:3030`

真机调试时，将开发地址改成电脑可从局域网访问的地址，并让 Vite 监听
`0.0.0.0`。正式包仍只应使用 HTTPS。

如果企业 SSO 必须嵌入 WebView，在 `trustedAuthOrigins` 中加入身份提供商的
精确 HTTPS Origin。未列入白名单的地址会交给系统浏览器，脚本、`file:` 和
`data:` 导航会被拒绝。

## 网页调用原生能力

WebView 初始化后会触发 `agentstudio:native-ready`，并注入：

```ts
window.AgentStudioNative.postMessage({
  type: 'share',
  title: '运行结果',
  message: '任务已完成',
  url: window.location.href,
});
```

支持的消息：

```ts
{ type: 'reload' }
{ type: 'openExternal', url: 'https://example.com' }
{ type: 'share', title?: string, message: string, url?: string }
```

原生层仍会校验 URL 协议；网页消息不能打开脚本或本地文件 URL。

## 本地验证

需要 Node.js 22.11+。

```powershell
cd mobile
npm ci
npm run typecheck
npm run lint
npm test
```

### Android

需要 Android Studio、Android SDK、Java 17，并配置 `ANDROID_HOME`：

```powershell
cd mobile
npm run android
```

发布签名通过 Gradle Property 或环境变量提供，不要把密钥和密码提交到仓库：

```text
AGENT_STUDIO_UPLOAD_STORE_FILE=D:\keys\agent-studio-upload.keystore
AGENT_STUDIO_UPLOAD_STORE_PASSWORD=...
AGENT_STUDIO_UPLOAD_KEY_ALIAS=...
AGENT_STUDIO_UPLOAD_KEY_PASSWORD=...
```

未提供这四项时，release 构建不会使用模板的 debug keystore 签名。

### iOS

iOS 必须在 macOS 上使用 Xcode 构建：

```bash
cd mobile
bundle install
cd ios && bundle exec pod install && cd ..
npm run ios
```

在 Xcode 中设置 Apple Team、正式 Bundle Identifier、签名和 Associated
Domains。Universal Links 还需要服务端托管 `apple-app-site-association`；当前
仓库已经支持无需域名配置的 `agentstudio://` 自定义 Scheme。

## 发布前清单

- 将 `studio.example.com` 替换为正式域名
- 将 `com.creationagentstudio.mobile` 替换为实际持有的 Bundle/Application ID
- 配置 Android release keystore 和 iOS Distribution 签名
- 替换模板应用图标和启动页品牌资源
- 确认生产环境只允许 HTTPS，且没有忽略证书错误
- 用真机验证登录、Cookie 刷新、文件上传、下载、相机/麦克风、SSO 和深链接
- 为 iOS 商店审核准备原生分享、错误恢复等非纯网页能力说明
