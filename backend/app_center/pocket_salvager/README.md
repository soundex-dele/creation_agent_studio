# 口袋打捞队 / Pocket Salvager

客户端单人 Phaser 游戏，React 承载中文 HUD 和菜单。无需游戏 API、AI 调用或额外素材下载。

## 启动

从仓库根目录同步到应用中心（无需迁移）：

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package pocket-salvager
```

登录并选择组织后，从“应用 → 休闲游戏 → 口袋打捞队”进入。
也可直接访问 `/apps/pocket-salvager`；应用目录使用 `/applications/:applicationId/pocket-salvager`。
两种入口均支持 `entry=home`、`entry=apps`、`standalone=1`、`embedded=1`。
本机音效设置和最高分按组织、用户、应用 ID 隔离，直接入口与目录入口使用各自的记录。

## 玩法

- WASD / 方向键或虚拟摇杆驾驶，空格 / 加速按钮冲刺。
- 靠近物资后停船约 1 秒自动打捞。木箱占 1 格、值 1 点；金色遗物占 2 格、值 5 点。
- 初始 6 格船舱，负重降低速度。返港自动卸货并修复船体，累计送回 30 点即获胜。
- 限时 180 秒；撞击三次损毁，损失随船货物，5 秒后在港口获救。
- 港内船坞可购买容量、动力和打捞升级，每项两级，价格 4 / 7 点。
  可用余额与累计修复进度分开，消费不会倒扣进度；菜单暂停计时。
- 最高分只保存已完成局：送达物资 × 100 + 胜利剩余秒数 × 10 − 损毁次数 × 50。
- 切换窗口或隐藏标签页自动暂停，需手动继续。

## 实现与验证

`frontend/src/pages/Apps/pocket-salvager/engine.ts` 是独立纯状态模拟，以 60 Hz 固定步长更新。
`renderer.ts` 负责 Phaser 程序绘图和相机；无远程字体、图片或音频。
音效由 Web Audio 合成，仅在用户操作后启用。Phaser 随游戏路由懒加载。

游戏根节点继承父容器的 100% 高度；画布不滚动，菜单以 `max-height: 100%` 和
`overflow-y: auto` 承担滚动。只有摇杆屏蔽默认触摸手势。

```powershell
cd frontend
npm test -- src/pages/Apps/pocket-salvager src/layouts/__tests__/pocketSalvagerLayout.test.ts src/lib/__tests__/applicationCatalog.test.ts
npm run build
cd ..\backend
.\venv\Scripts\python.exe -m pytest app_center/pocket_salvager/test_install.py -q
```

规则测试包含一条使用真实移动、打捞和碰撞模拟完成的获胜航线。
交互测试 mock 图形渲染，CSS 契约检查覆盖 320/375/390/767/768/844/1440px 宽和短横屏。
这些检查不等同于浏览器视觉验收或真机触摸测试；本次不使用 Codex 内置浏览器。
