# Guardian-AI 配置手册（可直接交给 AI 执行）

> 本手册用于让另一个 AI 在 Windows 电脑上为用户安装、配置、验收 Guardian-AI。  
> **使用方法：把本文件完整发给 AI，并对它说：“请严格按这份手册为用户配置 Guardian-AI，逐项验证，不要只给步骤。”**  
> AI 必须按步骤执行并验证；遇到需要 UAC 的步骤可以让用户点“是”，但不要反复弹控制台窗口。

---

## 0. 给 AI 的总指令

你是 Guardian-AI 的部署助手。请先判断用户要配置的是哪一类：

| 用户身份 | 安装内容 | 使用哪个包 |
|---|---|---|
| 管理员 / 服务端所有者 | 完整后端 + 数据库 + 托盘 + 公网入口 | **Guardian-AI_Server** |
| 普通用户 | 仅本地快捷方式，连管理员电脑上的中心数据库 | **Guardian-AI_Client** |

执行原则：

1. **普通用户只装 Client 包**，绝对不要把 Server 包发给普通用户。
2. **Server 包只装在管理员自己的电脑上**，不要装在普通用户电脑上。
3. 所有安装路径、数据路径优先放 **D 盘**，按“服务端 / 数据库 / 客户端 / 工具”分类。
4. 不重置、不删除、不重建已有数据库；不修改已有用户数据。
5. 不读取、不打印、不提交以下敏感信息：
   - `access_key.txt`
   - `.env` 中的 API Key / 管理员密码
   - 数据库连接字符串
6. 不把 SQL Server 1433 端口直接暴露公网；普通用户只通过网页/客户端访问。
7. 每完成一步都做验证；验证失败先排查，不要盲目重装。
8. 需要用户选择时，只问：安装模式、安装路径（默认 D 盘）、是否使用免费公共 API。其余用默认值。

---

## 1. 当前这台电脑的既有环境（仅当目标就是本机时参考）

- 项目目录：`D:\A_NGIT`
- 数据库：`D:\A_NGIT\database\mssql`（SQL Server LocalDB）
- 后端端口：`8000`
- 稳定公网地址：`https://goudan.tailf0dbf6.ts.net`
- 公网方式：Tailscale Funnel → `127.0.0.1:8000`
- 统一访问密钥文件：`D:\A_NGIT\access_key.txt`
- 最新安装包：
  - `D:\A_NGIT\dist\Guardian-AI_Server_v2.0.0_20261128_0730.zip`
  - `D:\A_NGIT\dist\Guardian-AI_Client_v2.0.0_20261128_0730.zip`
- 普通用户客户端默认：`D:\Guardian-AI\client`
- 服务器默认：`D:\Guardian-AI`

如果目标就是这台电脑：**不要重装、不要重建数据库**，只做验收、API 配置和客户端分发。  
如果目标不是这台电脑，忽略上面的固定 URL，按第 5 节为新机器生成新的 Tailscale 地址。

---

## 2. 安装 Server（管理员 / 本地部署）

### 2.1 前置条件

- Windows 10/11
- Python 3.10–3.12（优先使用机器上已有的 Python；没有则安装到 D 盘工具目录）
- SQL Server Express LocalDB
- 解压工具
- 管理员权限（安装器/快捷方式/UAC 需要）

### 2.2 安装步骤

1. 把 `Guardian-AI_Server_*.zip` 解压到 D 盘临时目录。
2. 双击 `install.bat`。
3. 安装路径填：`D:\Guardian-AI`（或用户指定的 D 盘子目录）。
4. 端口保持 `8000`，除非用户明确要求修改。
5. 等待安装器完成：
   - 复制文件
   - 创建 `.venv`
   - 安装 Python 依赖
   - 初始化数据库
   - 创建桌面/开始菜单快捷方式
6. 安装完成后，检查：
   - `D:\Guardian-AI\access_key.txt` 是否存在
   - `D:\Guardian-AI\database\mssql` 是否有数据库文件
   - 桌面 `Guardian-AI.lnk` 是否存在

### 2.3 启动与验收

1. 双击桌面 Guardian-AI，允许 UAC。
2. 本机访问：`http://127.0.0.1:8000/`
3. 健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health
```

期望：HTTP 200，返回 `"ok": true`。

4. 不要在这里打印访问密钥；只确认文件存在。

### 2.4 安装后禁止事项

- 不要删除 `database\mssql`。
- 不要重置 `users` 表 IDENTITY。
- 不要把 `.env`、`access_key.txt` 提交到 GitHub。
- 不要在普通用户电脑上运行 Server 的 `install.bat`。

---

## 3. 安装 Client（普通用户）

### 3.1 前置条件

- Windows 10/11
- Edge 或 Chrome
- 不需要 Python、SQL Server、后端
- 不需要管理员权限（安装到 D 盘用户目录时）

### 3.2 安装步骤

1. 只把 `Guardian-AI_Client_*.zip` 发给普通用户。
2. 解压后双击 `Client-Setup.bat`。
3. 安装目录默认：`D:\Guardian-AI\client`。
4. 服务器地址默认已预填管理员提供的稳定地址；如果目标服务器不是当前这台，改成新的 HTTPS 地址。
5. 点击“开始安装”。
6. 安装完成后，桌面/开始菜单出现 `Guardian-AI` 快捷方式。

### 3.3 登录

- 打开快捷方式，进入中心网页。
- 使用：**邮箱 + 密码 + 统一访问密钥**。
- 访问密钥由管理员私下提供，不在安装包内。
- 普通用户最多 7 个，每用户 1GB。
- 普通用户可读取科普、案例、知识库等非用户数据，只能读写自己的用户数据。

### 3.4 禁止事项

- 不要给普通用户 Server 包。
- 不要让普通用户安装 Python/SQL Server。
- 不要把 `access_key.txt` 打包进客户端。
- 不要把数据库连接串发给普通用户。

---

## 4. 目录与数据规范

| 内容 | 路径 |
|---|---|
| 服务端项目 | `D:\A_NGIT`（当前机器）或安装时选择的 D 盘子目录 |
| 数据库文件 | `<安装目录>\database\mssql` |
| 数据库备份 | `<安装目录>\database\backup` |
| 运行数据/日志 | `<安装目录>\backend\data` |
| 客户端 | `D:\Guardian-AI\client` |
| 发布包 | `D:\A_NGIT\dist` |
| Tailscale | `C:\Program Files\Tailscale`（系统组件例外） |

---

## 5. 公网访问（Tailscale Funnel）

### 5.1 检查 Tailscale

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' status
```

如果显示 `Logged out`：

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' up
```

按提示在浏览器登录 Tailscale。

### 5.2 启用 Funnel

如果首次使用，先打开命令给出的启用链接，在 Tailscale 管理页启用 Funnel；然后执行：

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel --bg 8000
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

期望看到：

```text
https://<机器名>.<tailnet>.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8000
```

### 5.3 验收

在外部网络或手机浏览器打开该 `https://...ts.net` 地址，应能打开 Guardian-AI 首页；`/api/health` 返回 200。

### 5.4 注意

- 不需要购买域名。
- 不需要 Cloudflare 命名隧道。
- 普通用户不需要安装 Tailscale 客户端。
- 电脑关机/休眠/后端未启动时，公网不可用。

---

## 6. AI API 配置

### 6.1 推荐：免费公共 API（Pollinations）

在网页 **API** 页点击“使用免费公共 API”，会自动填入：

```text
API 地址：https://text.pollinations.ai/openai
API Key：sk-dummy
文本模型：openai
视觉模型：openai
```

点击“保存并测试”，看到“连接正常”即可。

### 6.2 自有 API

也可以填写任意 OpenAI 兼容接口：

- 基础地址：如 `https://api.deepseek.com`
- 或完整端点：如 `https://text.pollinations.ai/openai`
- Key：真实 Key
- 模型：服务商提供的模型名

### 6.3 注意

- Pollinations 是公开免费接口，匿名限流，可能变慢/变更。
- 聊天原文会发送到公共第三方；不要提交身份证、银行卡、验证码等敏感原文。
- 正式使用建议换成自己的 API Key。
- API Key 只保存在本机数据库，页面只回显掩码。

---

## 7. 账号与访问控制

- 全系统只有一个统一 32 位访问密钥。
- 普通用户登录/注册都必须填写该密钥。
- 普通用户名必须是邮箱格式。
- 普通用户最多 7 个，每用户 1GB。
- 管理员账号不受密钥和普通配额限制，不在安装器/普通界面展示，不能重复注册。
- 普通用户数据按 `user_id + user_key` 隔离；知识库/案例库等非用户数据共享。

---

## 8. 验收清单

逐项确认：

- [ ] 本机 `/api/health` 返回 200
- [ ] 桌面快捷方式可启动，且只出现一个托盘图标
- [ ] 已运行时再次双击只打开 Web，不重复启动
- [ ] 稳定公网地址可打开首页
- [ ] 普通用户可登录/注册，且必须填访问密钥
- [ ] 无密钥普通登录被拒绝
- [ ] 普通用户达到 7 个后不能继续注册
- [ ] 普通用户看不到其他用户数据
- [ ] 普通用户能看到科普/案例/知识库
- [ ] API 页“使用免费公共 API”测试成功
- [ ] Client 安装后快捷方式能打开中心网页
- [ ] 退出程序后无残留 pythonw/托盘/浮层进程

---

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| 找不到 Python | 安装 Python 3.10–3.12，勾选 Add to PATH |
| LocalDB 连接失败 | 运行 `sqllocaldb info`，安装 SQL Server Express LocalDB |
| 8000 被占用 | 关闭占用程序，或修改 `.env` 的 `APP_PORT` |
| 页面打不开 | 看 `backend\data\backend.log`，用 `start_console.bat` 看报错 |
| 普通用户登录提示密钥错误 | 使用管理员提供的 `access_key.txt` 中的 32 位密钥 |
| 普通用户无法注册 | 检查是否已达 7 个普通用户 |
| 公网地址打不开 | 检查后端是否运行、`tailscale funnel status` 是否 Funnel on |
| Tailscale 提示 Funnel 未启用 | 打开管理页链接启用后重新执行 funnel |
| 客户端打开空白 | 检查 Client-Setup 填的服务器地址是否可访问 |
| 客户端连到本地空库 | 确认普通用户装的是 Client 包，不是 Server 包 |

---

## 10. AI 执行结束时的回报格式

请向用户回报：

1. 安装模式：Server / Client
2. 安装路径
3. 本机访问地址
4. 公网地址（Server）
5. 健康检查结果
6. 登录方式（不要输出访问密钥/密码）
7. 未完成项或需要用户确认的事项

---

## 11. 绝对禁止

- 禁止把 Server 包发给普通用户。
- 禁止把 `access_key.txt`、`.env`、数据库文件打包外发。
- 禁止直接开放 SQL Server 1433 到公网。
- 禁止删除/重建用户数据库。
- 禁止重置管理员账号或把管理员密码写入日志。
- 禁止在未备份的情况下迁移 `database\mssql`。
