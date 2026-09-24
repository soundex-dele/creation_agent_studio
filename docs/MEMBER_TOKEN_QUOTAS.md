# 组织成员 Token 配额

在「组织治理 → 成员与角色」中，所有者和管理员可为每位成员（包括所有者）设置每月 Token 配额。添加成员时也可同时设置。

- 留空：不设置成员独立限制，仍遵守已有组织配额。
- `0`：阻止新增运行和需要模型的知识库检索。
- 正整数：该成员在当前组织内每月允许使用的 Token 数。
- 配额独立生效，不受组织配额的 `hard_limit` 开关影响。

成员列表展示本月已用量、配额及剩余额度。用量按服务器配置的时区、自然月、组织和用户统计，包含输入与输出 Token。跨组织用量互不影响，月初自动进入新的统计周期；修改配额、停用再启用成员不会清除用量。

达到配额后，新的应用、智能体、工作流、子运行和知识库运行会被拒绝。API 返回 HTTP 429，错误信息为 `Member monthly token quota exceeded.`。已经成功创建的请求仍可通过原幂等键重放。

限制使用已有 `UsageRecord` 中的实际用量进行准入判断，不预留 Token，也不强制终止已入队或正在执行的运行。并发运行或一次较大的模型请求可能超过剩余额度；供应商未返回或系统未记录的用量不在此统计中。

## API

现有接口新增以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `monthly_token_limit` | integer / null | 可写，范围为 0 至 9007199254740991；默认 null |
| `monthly_tokens_used` | integer | 只读，当前月份的已记录用量 |

读取成员：`GET /api/v1/enterprise/organizations/{organization_id}/members/`

设置或清除配额：`PATCH /api/v1/enterprise/organizations/{organization_id}/members/{membership_id}/`

```json
{"monthly_token_limit": 1000000}
```

```json
{"monthly_token_limit": null}
```

`POST` 添加成员时同样支持 `monthly_token_limit`。成员 ID 是组织成员关系的 ID，而非用户 ID。普通成员只可查看；修改接口检查组织边界和管理员权限。

## 升级

在仓库根目录使用项目虚拟环境应用迁移：

```powershell
backend\venv\Scripts\python.exe backend\manage.py migrate enterprise
```

现有成员的初始配额为 null，不改变原有使用权限。
