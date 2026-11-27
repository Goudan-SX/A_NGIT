# Guardian-AI 技术手册

**AI 诈骗识别与个人信息保护助手**

版本：2.0.0 · 答辩用  
日期：2026 年 11 月 28 日

---

## 摘要

Guardian-AI 面向青年群体，解决聊天诈骗“发现晚、判断难、取证散”的问题。系统以“本地规则 + 案例库 + 大模型语义复审”为双引擎，支持文本、图片、多图关联和语音转写检测；桌面端可自动识别 QQ/微信聊天区域，只分析左侧对方消息，并在风险达到阈值时优先弹出本机告警，再同步 Web。

后端采用 Python FastAPI + SQL Server，前端采用原生 HTML/CSS/JavaScript；通过统一访问密钥、多租户键、7 用户上限和 1GB 配额实现多用户隔离；部署上分为 Server（管理员本地部署）和 Client（普通用户轻量客户端）两款安装包，使用 Tailscale Funnel 提供免费稳定公网入口。

**关键词**：反诈识别；多模态；大语言模型；FastAPI；SQL Server；多租户；桌面监测

---

## 1. 项目概述

### 1.1 背景

电信网络诈骗从“广撒网”转向“精准话术”，聊天场景中的冒充客服、刷单返利、虚假贷款、杀猪盘等话术具有强上下文、强诱导和快速变种特点。传统关键词工具存在三个问题：

1. 只做单句关键词，容易漏掉口语化索财、冒充身份和跨句诱导；
2. 只给“是否诈骗”，缺少风险维度、证据和处置建议；
3. 检测与聊天窗口割裂，用户需要手动复制粘贴，发现时往往已经转账。

### 1.2 建设目标

- 打开程序即自动监测，不依赖用户手动点击；
- 文本、图片、语音多模态统一接入；
- 先查数据库/本地规则给出初步可能性，再由 AI 强制复审；
- 本机告警优先，Web 同步不超过 20 秒；
- 多用户数据隔离，普通用户不接触数据库凭据；
- 免费、可本地部署、可演示、可扩展。

### 1.3 功能矩阵

| 模块 | 能力 | 支撑技术 |
|---|---|---|
| 文本检测 | 五维评分、关键词/案例匹配、AI 复审 | AC 自动机、bigram 相似度、LLM |
| 图片检测 | OCR、视觉理解、单图/多图关联 | OCR、视觉模型、跨图分析 |
| 语音检测 | 语音转写后进入文本链路 | Qwen-ASR |
| 桌面监测 | 自动找聊天区、只取对方消息、托盘告警 | 窗口捕获、UIA、OCR、Tk 浮层 |
| 交易风控 | 交易欺诈概率与规则解释 | LightGBM |
| 知识科普 | 分省案例、反诈问答、每日一反诈 | 案例库、知识库 |
| 用户中心 | 注册登录、API 配置、配额、租户隔离 | FastAPI、SQL Server |
| 部署分发 | Server/Client 安装包、公网访问 | Python 安装器、PowerShell 客户端安装器、Tailscale |

> 说明：桌面端使用 Python 原生托盘/浮层，不使用浏览器扩展；安装器为 Python 图形界面，客户端为无 Python 依赖的轻量快捷方式安装器。

### 1.4 技术栈

| 层次 | 选型 | 理由 |
|---|---|---|
| 前端 | HTML5 + CSS3 + 原生 JavaScript | 轻量、易部署、无构建链 |
| 主后端 | Python 3.12 + FastAPI + Uvicorn | 异步 IO、WebSocket、自动文档 |
| 授权微服务 | Flask | 轻量接口，职责分离 |
| 数据库 | SQL Server Express LocalDB | 结构化事务、Windows 生态 |
| 桌面端 | pystray + Tk + uiautomation + OCR | 托盘、浮层、窗口自动化 |
| AI | OpenAI 兼容接口；DeepSeek/Qwen；Pollinations 免费兜底 | 可替换、可降级 |
| 交易模型 | LightGBM | 表格数据强、可解释 |
| 公网 | Tailscale Funnel | 免费、稳定、无需域名 |
| 打包 | Python 安装器 + PowerShell 客户端安装器 | 自定义路径、低门槛 |

---

## 2. 系统总体架构

### 2.1 分层架构

| 层 | 组成 | 职责 |
|---|---|---|
| 展示层 | 主页面、历史、日志、API、图片采集 | 交互、结果展示、告警呈现 |
| 接入层 | FastAPI 路由、CORS、本地令牌、会话 Cookie | 请求校验、限流、鉴权 |
| 业务层 | 文本/图片/语音分析、监测、案例、报告 | 编排规则、AI、存储 |
| AI 层 | runtime_ai、deepseek 适配、Qwen/OCR 降级 | 模型调用、JSON 校验、降级 |
| 数据层 | AntiFraudGuard、[user]、SQLite 对话库 | 持久化、租户隔离、TTL |
| 桌面层 | launcher、tray、overlay、single_instance | 启动、监测、告警、退出清理 |
| 部署层 | Server/Client 安装包、Tailscale Funnel | 安装、升级、公网入口 |

### 2.2 部署拓扑

```text
普通用户浏览器 / Client 快捷方式
        │ HTTPS
        ▼
Tailscale Funnel（https://goudan.tailf0dbf6.ts.net）
        │ 反向代理到 127.0.0.1:8000
        ▼
FastAPI 主服务（Uvicorn）
   ├── 文本/图片/语音分析
   ├── 监测/告警/历史
   ├── 用户中心/配额/租户
   └── SQL Server LocalDB
          ├── AntiFraudGuard（业务数据）
          └── [user]（账号/密钥/会话）
        ▲
        │ 本地回环
Windows 桌面端：launcher → tray → overlay
```

### 2.3 一次检测请求链路

1. 前端提交文本/图片/语音，携带本地访问令牌和用户会话。
2. 中间件校验来源、令牌、会话，绑定当前租户上下文。
3. 文本先做归一化、AC 关键词、案例库匹配；图片先做 SHA 缓存/OCR/视觉。
4. 本地规则给出初步分和证据；若配置了 AI，则强制 AI 复审。
5. 结果融合、PII 脱敏、写入数据库；返回风险分、等级、证据、建议。
6. 桌面监测场景下，托盘先弹本机告警，再 publish 给 Web。

### 2.4 Server / Client 分离

| 包 | 适用对象 | 内容 | 数据位置 |
|---|---|---|---|
| Guardian-AI_Server | 管理员/服务端 | 完整后端、数据库、托盘、安装器 | 本机数据库 |
| Guardian-AI_Client | 普通用户 | 仅快捷方式/配置，无 Python/数据库 | 中心服务器 |

Client 通过 Edge/Chrome 应用窗口打开中心地址，不接触 SQL Server；这既降低安装门槛，也避免把数据库凭据分发出去。

### 2.5 关键目录

| 目录 | 作用 |
|---|---|
| HTML+CSS/ | 前端页面、样式、脚本、资源 |
| backend/app/ | FastAPI、分析、AI、租户、用户库 |
| backend/desktop/ | 启动器、托盘、浮层、单实例 |
| backend/database/ | 业务/用户库 schema |
| backend/models/ | LightGBM 等模型文件 |
| backend/data/ | 运行数据、日志、案例种子 |
| license_server/ | Flask 授权/数据库接口 |
| scripts/ | 安装、打包、客户端安装、密钥轮换 |
| docs/ | 需求、配置手册、技术手册 |

---

## 3. 核心业务流程

### 3.1 文本检测

1. 预处理：NFKC、去零宽字符、合并汉字间空格、截断超长文本。
2. 关键词：265 条关键词经 Aho-Corasick 一次扫描，记录命中与频次。
3. 案例库：先精确哈希，再汉字 bigram 相似度；≥0.74 视为命中，复用案例结果。
4. 本地评分：话术操控、资金诱导、信息窃取、渠道异常、身份伪装五维加权。
5. AI 复审：强制调用已配置的 OpenAI 兼容接口，要求返回 JSON；校验字段与分值范围。
6. 融合：本地分与 AI 分加权，保留证据、命中关键词、建议；AI 失败则回退本地结果并标注。
7. 持久化：save=true 时写入 analyses/staging；命中/未命中按策略写入案例库。

### 3.2 图片与多图

- 单图：SHA-256 查 image_cases；未命中则 OCR + 视觉模型；结果写缓存。
- 多图：asyncio.gather 并发单图分析，再由 AI 做跨图联合分析，输出 relationships、image_findings、整体风险，避免简单取最高分。
- 证据：OCR 行包围盒、图片摘要、风险点；前端支持点击放大。

### 3.3 语音

语音先由 Qwen-ASR 转写，再进入文本检测链路；转写文本按文本案例库存储，原音频只作为临时文件。

### 3.4 桌面监测

1. 托盘定时捕获前台聊天窗口。
2. AI 视觉识别聊天区域，返回归一化 contact/chat 框；置信度低时回退固定比例。
3. OCR 返回行包围盒，按聊天区中线过滤：只保留左侧对方消息，右侧自己的消息不参与。
4. 从聊天头部/窗口标题提取对方 ID，拒绝当前用户昵称、拒绝相似度≥0.75 的候选。
5. 组装对话文本，调用本地/数据库预判；命中高风险立即托盘告警。
6. 后台 AI 强制复审，托盘每 1.5 秒拉取结果补弹；Web 2.5 秒轮询。

### 3.5 告警优先级

- 70–89：白色浮层，淡入、闪烁一次、5 秒自动隐藏。
- ≥90：红色浮层常驻，直到窗口关闭、离开允许窗口 12 秒或程序退出。
- 托盘/本机通知先于 Web；Web 可延迟但目标 ≤20 秒。
- 退出时按链路清理：停止监测 → 关闭浮层 → 结束后端 → 停止托盘，避免残留进程。

---

## 4. 关键技术与算法

### 4.1 五维评分

| 维度 | 分值 | 典型信号 |
|---|---:|---|
| 话术操控 | 20 | 紧迫、恐吓、保密、限时 |
| 资金诱导 | 30 | 转账、垫付、刷单、贷款验资 |
| 信息窃取 | 25 | 身份证、银行卡、验证码、屏幕共享 |
| 渠道异常 | 15 | 私人链接、陌生 APP、会议软件 |
| 身份伪装 | 10 | 冒充客服、公检法、熟人、平台 |

0–19 低、20–49 中、50–89 高、90–100 极高；证件+银行卡+验证码组合泄露时风险下限 70。

### 4.2 关键词频率与案例匹配

- 关键词命中 3–5 次 +8，6–9 次 +18，10–14 次 +30，≥15 次 +35，封顶 100。
- 案例库精确哈希或 bigram 相似度≥0.74 命中；命中后仍由 AI 复审，避免“旧案例误伤”。
- 新案例入库前替换 PII，保留话术结构。

### 4.3 交易风控模型

| 指标 | 数值 |
|---|---:|
| 数据量 | 25 万+ 条，欺诈率 5.39% |
| 模型 | LightGBM |
| AUC-ROC | 0.9814 |
| AUC-PR | 0.8667 |
| 阈值 | 0.8878 |
| F1 | 0.7654 |
| 规则 | 7 条，落库 transaction_rules |

交易数据只用于表格分类和规则提炼，不用于话术大模型微调；话术识别仍依赖文本案例库。

### 4.4 AI 适配与输出校验

- 统一 OpenAI 兼容协议：base_url + /chat/completions；支持完整端点（如 /openai）。
- 要求模型输出 JSON；解析失败重试/降级，不让异常文本直接进入前端。
- 低置信、超时、限流均回退本地规则；前端明确标注“AI 未复核”。
- API Key 只存本机数据库，页面只回显掩码；支持启动时恢复 root 配置。

### 4.5 性能优化

- AC 自动机一次扫描 265 关键词。
- 相同文本 10 分钟内存 TTL；图片 SHA 缓存；多图并发。
- 数据库/PIL 等阻塞操作走线程池；总耗时取多路最慢一路。
- 高置信/明显低风险直接返回，模糊文本才调用 AI。

---

## 5. 数据设计

### 5.1 数据库拓扑

| 数据库 | 内容 |
|---|---|
| AntiFraudGuard | analyses、images、reports、logs、knowledge、text_cases、image_cases、staging_contents、guardian_*、transaction_* |
| [user] | users、user_sessions、user_data、access_keys |
| SQLite | conversations.db，当前聊天窗口临时对话 |

数据库文件位于 `D:\A_NGIT\database\mssql`，备份位于 `database\backup`。

### 5.2 核心表

| 表 | 作用 | 关键字段 |
|---|---|---|
| analyses | 检测主记录 | id、user_id、user_key、risk_score、result_json |
| images | 图片记录 | analysis_id、sha256、ocr_text、user_key |
| reports | 报告 | id、analysis_id、content |
| logs | 运行日志 | level、event、message |
| knowledge | 科普知识 | category、title、content |
| text_cases | 文本案例 | hash、text、similarity、risk_score |
| image_cases | 图片缓存 | sha256、ocr_text、vision_json |
| staging_contents | 暂存内容 | user_id、user_key、content_type、content |
| users | 账号 | user_id、username、role、api_config |
| user_sessions | 会话 | token_hash、user_id、expires_at |
| access_keys | 统一密钥 | key_hash、is_active |
| transaction_rules | 交易规则 | rule_name、condition、weight |

### 5.3 租户键

- 用户键：`u{user_id}:{username}`，例如 `u1001:root`。
- 对话键：`{user_key}:c:{contact_id}`。
- 所有个人数据表带 `user_id + user_key`；查询必须带租户条件，禁止跨用户读取。
- 未登录/托盘/后台任务默认 root，保证历史数据与桌面监测不中断。

### 5.4 数据生命周期

| 数据 | 保留策略 |
|---|---|
| 当前对话 | 1 天 TTL |
| staging 暂存 | 默认 7 天 |
| 自动收录案例 | 90 天 |
| 软删除 | 回收站 30 天 |
| 日志 | 按运维策略清理 |

---

## 6. 安全与权限

### 6.1 统一访问密钥

- 全系统一个 32 位访问密钥，数据库只存 SHA-256。
- 普通用户登录/注册必须填写；root 免密钥。
- 密钥文件 `access_key.txt` 只保存在服务器，不打包、不外发。
- 可通过脚本轮换，旧密钥立即失效。

### 6.2 账号与配额

- 普通用户名必须邮箱格式；最多 7 个；每用户 1GB。
- root 不占普通名额、不受普通配额限制；root 不能重复注册，界面不展示。
- root 是应用管理员，不是 SQL Server 登录账号；不能拿 root 账号直接连数据库。

### 6.3 多租户隔离

- 登录后绑定 user_id/user_key；仓储层自动加租户条件。
- 普通用户只能读写自己的 analyses/images/reports/staging；知识库/案例库全局共享。
- 管理员接口仅 root：用户列表、维护任务；没有“任意 SQL 查询”入口。

### 6.4 公网与数据库边界

- 后端只监听 127.0.0.1:8000；公网通过 Tailscale Funnel 反代。
- SQL Server LocalDB 不开放 1433；普通用户只访问 HTTPS API。
- 客户端不保存数据库连接串；数据库账号只在本机。
- 风险：root 密码泄露仍可登录网页管理员；SQL 账号泄露可读全库，必须本地保管。

### 6.5 隐私

- 本地规则/案例优先，减少原文外发。
- PII 入库前替换；日志不记录完整敏感信息。
- 公共免费 API 会把聊天原文发往第三方；页面明确提示不要提交身份证、银行卡、验证码。
- 正式场景建议使用自有 API 或本地模型。

---

## 7. 部署与运维

### 7.1 Server 安装

1. 解压 Server 包到 D 盘。
2. 运行 `install.bat`，选择 `D:\Guardian-AI`。
3. 安装器创建 `.venv`、安装依赖、初始化数据库、创建快捷方式。
4. 启动后访问 `http://127.0.0.1:8000`。
5. 统一密钥写入 `access_key.txt`；管理员账号不对外展示。

### 7.2 Client 安装

1. 普通用户只拿 Client 包。
2. 运行 `Client-Setup.bat`，默认 `D:\Guardian-AI\client`。
3. 服务器地址已预填；创建桌面/开始菜单快捷方式。
4. 不装 Python/数据库；登录用邮箱+密码+访问密钥。

### 7.3 Tailscale Funnel

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel --bg 8000
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

稳定地址形如 `https://<机器名>.<tailnet>.ts.net`；无需域名，普通用户无需安装 Tailscale。

### 7.4 路径规范

| 内容 | 路径 |
|---|---|
| 服务端 | D:\A_NGIT 或 D:\Guardian-AI |
| 数据库 | <安装目录>\database\mssql |
| 运行数据 | <安装目录>\backend\data |
| 客户端 | D:\Guardian-AI\client |
| 发布包 | D:\A_NGIT\dist |

---

## 8. 测试与结果

### 8.1 功能测试

| 项目 | 结果 |
|---|---|
| 文本高风险识别 | 贷款话术本地 98%，AI 复审 100% |
| 客服退款+屏幕共享 | 98 分，极高风险 |
| 图片/多图 | 单图 OCR/视觉；两图约 10 秒 |
| 用户隔离 | 普通用户互查 404，admin 接口 403 |
| 无密钥登录 | 400 |
| root 登录 | 免密钥 200 |
| 配额 | 1GB/用户，7 用户上限 |
| 客户端 | 快捷方式打开中心网页，无本地库 |

### 8.2 AI 接入测试

- Pollinations：`https://text.pollinations.ai/openai`，模型 `openai`，Key `sk-dummy`。
- 连接测试约 1.4 秒；反诈文本分析约 8 秒；返回 88/98 分并正常解析 JSON。
- 免费公共接口匿名限流，只作演示兜底；正式使用换自有 Key。

### 8.3 交易模型

AUC-ROC 0.9814、AUC-PR 0.8667、F1 0.7654；7 条规则入库，提供 `/api/transaction/risk`。

### 8.4 测试局限

- 真实聊天样本规模有限，案例库仍在积累；
- 免费 API 延迟/限流会波动；
- OCR 对深色主题、缩放、遮挡仍可能失败；
- 未做正式第三方安全审计与大并发压测。

---

## 9. 创新点

1. **双引擎**：本地规则/案例先判，AI 强制复审，兼顾速度与语义。
2. **多模态跨图**：多图并发 + 联合分析，不是简单取最高分。
3. **桌面监测闭环**：自动找聊天区、只取对方消息、托盘先告警、Web 后同步。
4. **告警优先级**：本机告警不被 Web 轮询拖慢，Web 目标 ≤20 秒。
5. **多租户 + 轻客户端**：普通用户零数据库依赖，数据统一存中心。
6. **免费稳定公网**：Tailscale Funnel 无需域名，降低演示/部署成本。

---

## 10. 不足与改进

| 不足 | 改进方向 |
|---|---|
| LocalDB 能力有限 | 迁移完整 SQL Server Express/PostgreSQL |
| 免费 API 不稳定 | 自有 Key、本地模型、多 Provider 路由 |
| 聊天软件适配 | 扩展到更多 IM，增加 UI 自动化回归 |
| 测试样本有限 | 构建标注集，做准确率/召回率评测 |
| Client 是网页壳 | 可演进为 Tauri/Electron 原生客户端 |
| 管理端能力弱 | 增加 root 只读审计页，不开放任意 SQL |
| 规模上限 7 用户/1GB | 连接池、对象存储、水平扩展 |

---

## 11. 答辩演示脚本（约 6 分钟）

1. 打开稳定地址，展示首页、登录/注册、访问密钥必填。
2. 输入“客服退款+屏幕共享+验证码”文本，展示 98 分、证据、建议。
3. 上传一张聊天截图，展示 OCR/视觉结果；再上传两张，展示跨图关联。
4. 打开“对话用户”，展示按联系人隔离和高风险标记。
5. 展示 API 页“使用免费公共 API”，测试连接成功。
6. 展示 Server/Client 两款安装包与 Tailscale 稳定地址，说明普通用户不接触数据库。

---

## 12. 答辩问答

**Q1：为什么主后端用 FastAPI，而不是 Flask？**

A：主服务需要异步 IO、WebSocket、并发多模态和自动文档；FastAPI 更合适。Flask 只用于轻量授权/数据库接口，职责分离。

**Q2：为什么用 SQL Server？**

A：结构化事务、Windows 生态、与现有代码匹配；当前用 LocalDB 便于本地部署，后续可迁移完整 Express。

**Q3：AI 会不会被话术欺骗或提示注入？**

A：AI 不是唯一判据；本地规则/案例先判，AI 输出必须为 JSON 并校验字段，异常回退本地结果；系统提示明确要求只做风险分析。

**Q4：如何保证准确率？**

A：265 关键词 + 411 分省案例 + 五维评分 + 案例相似度 + AI 复审；交易模型 AUC 0.9814；但真实样本仍有限，持续积累。

**Q5：用户隐私怎么保护？**

A：本地优先、PII 脱敏、租户隔离、数据库不暴露公网；公共免费 API 有明确隐私提示，正式场景换自有 Key/本地模型。

**Q6：为什么普通用户不直接连数据库？**

A：避免分发连接串/SQL 权限，防止越权；统一走 API，按 user_id 隔离，客户端零数据库依赖。

**Q7：7 用户/1GB 怎么实现？**

A：注册时统计普通用户数；存储统计跨库汇总 staging；超限拒绝上传；root 不受限。

**Q8：桌面端怎么识别 QQ/微信？**

A：窗口捕获 + AI 识别聊天区域 + OCR 行框 + 中线过滤左侧消息 + 联系人头部提取；不写死坐标，适配同类软件。

**Q9：为什么本机告警优先？**

A：诈骗提醒的价值在“当下”；托盘先弹，Web 后同步，避免轮询延迟；Web 目标 ≤20 秒。

**Q10：没有域名怎么公网访问？**

A：Tailscale Funnel 提供免费稳定 `*.ts.net`；普通用户不需要域名或 Tailscale 账号。

**Q11：AI 挂了怎么办？**

A：本地规则/案例仍可返回；AI 失败标注“未复核”，不阻塞主流程。

**Q12：为什么做 Server/Client 两个包？**

A：最小权限；普通用户只需浏览器壳，管理员才需要后端/数据库。

**Q13：root 能看所有数据吗？**

A：应用 root 是管理员，但不是 SQL 账号；普通页面仍按租户隔离，只有用户列表/维护接口。SQL 账号才能读全库，必须本地保管。

**Q14：项目最大的创新点？**

A：双引擎 + 多模态跨图 + 桌面监测告警闭环 + 轻客户端多租户，四者组合而不是单点功能。

**Q15：如果继续做一年？**

A：补标注集与评测、扩展到更多 IM、迁移完整数据库、加本地模型/多 Provider、做原生客户端和管理审计。

---

## 13. 结论

Guardian-AI 不是单点“聊天检测器”，而是“本地规则/案例 + AI 语义 + 多模态 + 桌面监测 + 多租户部署”的完整反诈闭环。当前版本已能演示文本、图片、多图、语音、交易风控、告警、用户隔离和公网访问；下一步重点是评测集、模型稳定性和更大规模部署。

---

## 附录 A：主要 API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /api/health | 健康检查 |
| POST | /api/analyze/text | 文本检测 |
| POST | /api/analyze | 图片/语音检测 |
| POST | /api/analyze/preview | Web 快速预判 |
| POST | /api/monitor/analyze | 监测预判 |
| POST | /api/monitor/publish | 发布到 Web |
| GET | /api/monitor/latest | 拉取最新告警 |
| POST | /api/auth/login | 登录/注册 |
| GET | /api/auth/quota | 配额 |
| PUT | /api/auth/api-config | 保存 API |
| POST | /api/auth/api-test | 测试 API |
| GET | /api/history | 历史 |
| GET | /api/case-library/* | 案例/科普 |
| POST | /api/transaction/risk | 交易风控 |
| GET | /api/admin/users | root 用户列表 |
| POST | /api/admin/maintenance | root 维护 |

## 附录 B：当前演示环境

- 项目：D:\A_NGIT
- 数据库：D:\A_NGIT\database\mssql
- 稳定地址：https://goudan.tailf0dbf6.ts.net
- 服务端包：Guardian-AI_Server_v2.0.0_20261128_0730.zip
- 客户端包：Guardian-AI_Client_v2.0.0_20261128_0730.zip
- 免费 API：Pollinations（演示兜底）

## 附录 C：术语

- **AC 自动机**：多关键词一次扫描算法。
- **bigram 相似度**：汉字二元组重合度，用于案例匹配。
- **租户键**：user_id + user_key，隔离不同用户数据。
- **Funnel**：Tailscale 的公网反向代理能力。
- **LocalDB**：SQL Server Express 的本地轻量实例。
