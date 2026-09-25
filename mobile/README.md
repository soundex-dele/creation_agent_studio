# Agent Studio Mobile

Android 和 iOS 共用的 React Native WebView 外壳。启动后输入网址，APP 在内部
打开对应网站。网页可以部署在任意手机可访问的服务器上，无需把网站打包进 APP。

## 功能

- Android WebView 与 iOS WKWebView 共用一套 TypeScript 外壳
- 同源 Cookie 会话、网页上传控件和媒体播放
- 账户登录页默认勾选“记住密码”：仅在登录成功后保存，下次打开同一服务器的登录页自动填入；取消勾选删除该服务器保存的凭据
- 密码使用 Android Keystore / iOS Keychain 安全存储，按协议、域名和端口隔离；需要同时更新服务器上的前端登录页和 APP，普通浏览器使用其自带密码管理器
- 启动页输入网址，保留路径、查询参数和端口，顶部随时更换网址
- 连接页保留最近使用的 20 个服务器网址，自动去重，点击历史记录即可连接
- 顶部提供主页、刷新、更换网址、切换窗口按钮，不再显示网址；主页会在当前窗口重新加载连接时输入的完整服务器网址，并重置当前窗口的浏览历史；窗口列表显示标题、网址和当前窗口标记，支持切换和关闭
- 网页的新窗口链接在 APP 内创建独立 WebView，切换保留页面状态；返回键优先后退当前页面，无历史时关闭当前窗口，关闭最后一个窗口返回连接页
- HTTP / HTTPS 网页及跨域跳转留在 WebView，电话和邮件链接交给系统应用
- 顶部操作使用图标，窗口图标带数量角标；设置页可查看 Android / iOS 下载任务的文件名、大小、百分比与状态，每秒自动更新，保留下载历史
- Android 使用系统 DownloadManager；iOS 使用 WKDownload，保留原始下载请求的 Cookie 和 POST 请求体，文件保存到“文件”App → 我的 iPhone / iPad → Agent Studio → Downloads，同名文件自动编号
- 下载进度仅涵盖本 APP 接管的 HTTP/HTTPS 附件和下载链接；外部浏览器、网页内存 Blob 或电脑端传输不属于此列表。iOS 下载时请保持 APP 打开，进程终止后未完成的任务会标记为中断，需要回到网页重新下载
- Android 物理返回键和 iOS 前进/后退手势
- 联网检测、原生加载态、错误态与重新加载
- 网络恢复或切回失败的窗口时重新请求失败网址；从后台返回后 15 秒内发生连接异常，最多延迟重试两次，正常页面保留状态；错误页提供中文说明、服务器地址和更换网址入口
- `agentstudio://open?path=/apps/123` 自定义深链接
- 网页到原生的外链、系统分享和重载桥接
- 浅色/深色模式及原生安全区域适配

## 打开服务器上的网站

打开 APP，在“网站地址”中输入部署好的网址，再点击“打开网页”，例如：

```text
https://your-server.example.com/apps/123
http://192.168.1.20:3030/
```

省略协议时默认使用 HTTPS。首次打开时将输入的网址保存在手机本地，以后启动
APP 会自动打开这个网址。“更换网址”后成功保存的新地址会替换原地址；网页内部
跳转不会覆盖启动地址。域名不再写死在源码里，Debug 与 Release 使用相同行为。

Android 和 iOS 默认的 Debug / Release 安装包均内置 APP 自身的 JavaScript，不需要 Metro、电脑或 USB 连接。
网站和 API 仍从服务器加载，手机需能访问对应地址。部署 Agent Studio 时，建议
网页和 `/api/v1` 使用同一 HTTPS Origin，以支持 Secure Cookie 会话。

需要访问电脑上的开发网页时：

- Android USB / 模拟器：转发 3030 端口后，在 APP 输入 `http://localhost:3030`。
- iOS 模拟器：输入 `http://localhost:3030`。
- Wi-Fi 真机：输入电脑局域网 IP 和端口，并让 Vite 监听 `0.0.0.0`。

网页跳转可以跨域，但原生桥接仅接受用户输入网址的 Origin，以及
`src/appConfig.ts` 的 `trustedAuthOrigins` 中配置的来源。脚本、`file:` 和
`data:` 导航会被拒绝，HTTPS 证书校验保持启用。

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

需要支持 AGP 8.12.2 的 Android Studio、Android SDK Platform 36、Build Tools
36.0.0、Java 17，并配置 `ANDROID_HOME`。项目固定使用 AGP 8.12.2 和 Gradle
8.13，避免 React Native 的传递依赖将 AGP 升级到当前 IDE 不支持的版本。
`npm ci` / `npm install` 会通过 `patch-package` 应用 `patches/` 中的补丁，
让 React Native Gradle 插件也使用 AGP 8.12.2 编译，避免 AGP 9 与 8 的 API
二进制不兼容。升级 React Native 时需要重新检查这份补丁。

可先验证 Gradle 配置和 Android 依赖：

```powershell
cd mobile/android
.\gradlew.bat :app:checkDebugAarMetadata
```

默认的 Debug 和 Release 构建都会内置 APP 的 JavaScript。直接在 Android Studio
运行，或执行下面的命令即可，无需启动 Metro：

```powershell
cd mobile
npm run android
```

仅当要打开电脑上的本地网页时，才需要启动 3030 端口的网页服务器并转发该端口。
访问服务器网站无需端口转发。重新连接 USB 后需重新执行转发；多个设备时给
`adb` 加上 `-s <设备序列号>`：

```powershell
& "$env:ANDROID_HOME/platform-tools/adb.exe" reverse tcp:3030 tcp:3030
```

只有开发 APP 自身的 TypeScript、需要 Fast Refresh 时才启用 Metro。先在独立
终端执行 `cd mobile; npm start`，再在另一个终端安装显式启用 Metro 的调试包：

```powershell
& "$env:ANDROID_HOME/platform-tools/adb.exe" reverse tcp:8081 tcp:8081
cd mobile/android
.\gradlew.bat :app:installDebug -PuseMetro=true
```

Metro 模式需要持续连接开发服务器。结束开发后，不带 `-PuseMetro=true` 重新构建
并安装，即恢复独立运行。若旧安装包出现 “Unable to load script”，安装默认构建
的新 APK；仅重开旧包不会改变它依赖 Metro 的行为。

发布签名通过 Gradle Property 或环境变量提供，不要把密钥和密码提交到仓库：

```text
AGENT_STUDIO_UPLOAD_STORE_FILE=D:\keys\agent-studio-upload.keystore
AGENT_STUDIO_UPLOAD_STORE_PASSWORD=...
AGENT_STUDIO_UPLOAD_KEY_ALIAS=...
AGENT_STUDIO_UPLOAD_KEY_PASSWORD=...
```

构建独立运行的安装包：

```powershell
cd mobile/android
.\gradlew.bat :app:assembleRelease
```

APK 输出到 `app/build/outputs/apk/release/`。未提供上述四项时会生成未签名 APK，
需要签名后才能安装；release 构建不会自动使用模板的 debug keystore。

### iOS

iOS 必须在 macOS 上使用 Xcode 16.1 或更新版本构建（React Native 0.87 的最低要求），部署目标为 iOS 15.1：

```bash
cd mobile
npm ci
bundle install
cd ios && bundle exec pod install && cd ..
npm run ios
```

默认调试包（包括模拟器）内置 JavaScript，`npm run ios` 不启动 Metro。直接在
Xcode 打开 `ios/AgentStudioMobile.xcworkspace` 并运行也可独立启动。
开发 APP 的 TypeScript、需要 Fast Refresh 时，在单独终端运行 `npm start`，
再运行 `npm run ios:metro`。也可在 Xcode 的 Build Settings 中将用户自定义设置
`AGENT_STUDIO_USE_METRO` 改为 `YES`；完成后恢复 `NO` 并重新构建。
Release 始终内置 JavaScript，即使传入 Metro 开关也不会依赖开发服务器。

iOS 下载通过 `patches/react-native-webview+14.0.1.patch` 将 WebView 的下载响应
直接交给 WKDownload，并由原生模块 `DownloadStatus` 提供进度；`npm ci` 自动应用
补丁。升级 WebView 时需重新检查补丁及 Cookie、附件、POST 下载行为。下载继续使用
WebKit 的网络策略，无需扩大 ATS 例外，也不会绕过 HTTPS 证书校验。

macOS 上可额外运行 `npm run test:ios-native`，验证下载历史持久化、进程中断处理、
文件名处理、WebKit 下载委托的类型检查，以及 Debug / Release 的打包开关。

在 Xcode 中设置 Apple Team、正式 Bundle Identifier、签名和 Associated
Domains。Universal Links 还需要服务端托管 `apple-app-site-association`；当前
仓库已经支持无需域名配置的 `agentstudio://` 自定义 Scheme。

## 发布前清单

- 将 `com.creationagentstudio.mobile` 替换为实际持有的 Bundle/Application ID
- 配置 Android release keystore 和 iOS Distribution 签名
- 替换模板应用图标和启动页品牌资源
- 验证目标服务器网址及 HTTPS 证书，确认没有忽略证书错误
- 用真机验证登录、Cookie 刷新、文件上传、下载、相机/麦克风、SSO 和深链接
- 为 iOS 商店审核准备原生分享、错误恢复等非纯网页能力说明
