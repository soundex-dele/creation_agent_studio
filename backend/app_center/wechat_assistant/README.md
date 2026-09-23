# 微信助手

应用中心中的个人微信入口。每个项目用户在每个组织绑定一个微信 Bot，只接受扫码账号的文本私聊。后台使用腾讯公开的 [iLink 插件协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)，不依赖 OpenClaw。协议实现参考版本为 2.4.9，服务端行为仍需真实账号联调。

## 安装与运行

从仓库根目录，在 Windows 上运行：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package wechat-assistant
backend\venv\Scripts\python.exe backend/manage.py run_wechat_connector
```

同时保持项目 Web 服务和 `run_execution_coordinator --worker-pool all` 运行。桌面启动器、`deploy.sh` 和 Docker Compose 已包含连接服务。关闭应用页面不会断开微信；退出桌面后台或关机会停止连接。

进入应用中心的“微信助手”，选择并保存智能体，再点击“扫码绑定”。微信可能要求输入手机显示的验证码。绑定后发送文字开始对话；任务需要补充信息、权限审批或计划批准时，在项目会话中处理。新建会话或更换智能体须等待当前任务结束。语音、图片、文件、群聊和微信内审批不在首版范围内。

可选设置 `WECHAT_ASSISTANT_PUBLIC_URL=https://your-site.example`，在待办提醒中附上会话链接。地址必须可从手机访问；未配置时仅提醒从项目打开会话，不发送 localhost 链接。

## 恢复与凭证

- Bot token、登录数据及回复上下文令牌用安装的 `SECRET_KEY` 派生密钥加密，前端不会收到 Bot token。生产环境应使用私有稳定的密钥；更换密钥后需重新扫码。
- 收消息游标与入站消息在同一事务保存；消息按绑定、Bot 身份和微信消息 ID 去重。Run 的幂等键关联持久化消息，不因发送失败重新执行。
- 每账号数据库租约防止重复轮询。连接进程崩溃后最多等待旧租约 120 秒，再接管处理；正常退出释放租约。
- 回复记录在发送前持久化，最多尝试 5 次，使用固定客户端消息 ID。网络中断时无法保证微信端绝对不重复；界面会标明确认不明确及最终失败。超过次数的结果在项目会话中可查看。
- 解绑会停止后续收发、清除本地凭证并作废待发回复，保留会话和已有 Run。解绑时已交给微信的在途请求无法撤回；解绑不等同于微信侧撤销授权。
- 状态页包含最近连接、收取、发送时间及脱敏错误。Docker 用 `check_wechat_connector` 检查调度心跳。

## 验证

```powershell
backend\venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/app_center/wechat_assistant/backend/tests backend/apps/conversations/tests -q
```

测试使用模拟微信接口，包括扫码、验证码、消息收取、Run 创建、完成回复、重复投递、权限撤销、租约接管、等待输入及发送失败。真实验收另需在微信扫码后完成两轮文本对话、关闭页面后继续收发，并验证一次回项目页面处理待办的流程。自动化测试不等同于真实微信验证。
