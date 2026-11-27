# A_NGIT · Guardian-AI

> Guardian-AI：AI 诈骗识别与个人信息保护助手（赛题 11 · 网络安全）  
> 仓库地址：<https://github.com/Goudan-SX/A_NGIT>  
> 安装包用户请先看 [README_安装说明.md](README_安装说明.md)

Guardian-AI 是统一模型名称；它是一个可运行的全栈反诈演示系统：用户粘贴可疑短信/聊天记录，或上传聊天截图、语音，
系统从**话术操控、资金诱导、信息窃取、渠道异常、身份伪装**五个维度进行可解释风险评分，
并联动高危词汇、风险证据、个人信息暴露、可疑链接、处置建议、历史记录、运行日志、
一键举报材料与反诈科普。

当前版本**不依赖外部 AI 也能完整演示**：文本使用本地规则引擎，图片使用 Windows 自带 OCR
兜底；配置 DeepSeek API Key 后，优先使用 DeepSeek V4.1 Flash 做文本与图片理解，语音由 Qwen-ASR 转写。

检测采用**案例库优先**策略：先匹配 SQL Server 中的反诈案例，命中则复用案例结果并由 AI 二次复核；未命中才走 AI 分析，并自动把新内容收录进案例库，持续扩充。

---

## 一、功能清单

### AI 管家（实时检测）

- 三类存储（同一个 `AntiFraudGuard` 数据库中的三张表）：`staging_contents`（当前用户全部内容暂存）、`text_cases`（文本案例库）、`image_cases`（图片案例库）；语音转写后写入文本库。
- 案例库优先：每次检测先匹配 `text_cases` 表，命中则直接复用并做 AI 复核；未命中才走 AI 分析。
- 关键词规则库：265 条反诈关键词，覆盖游戏皮肤、公检法、刷单、票务、校园收费等；Aho-Corasick 单次扫描。
- 分省案例：411 条青少年案例按省份入库，可在“知识宣传 → 分省案例”中查看，也可通过 API 查询。
- 自动扩充案例库：未命中的有效文本在检测后自动收录，下一次相同/相似内容可直接命中。
- 单人聊天测试页：独立页面，聊天窗口居中，消息按“对方/你”显示秒级时间，内置正常/游戏皮肤/刷单/公检法场景；可选 WebSocket 双人远程对话。
- 聊天图片同步：聊天页发送图片后自动传到主检测页分析；主页面分析完成的图片自动进入“图片采集”导航。
- 图片采集：保存图片缩略图、时间、风险分、等级、摘要、OCR 文本（本地浏览器暂存），支持单张删除与清空。
- 本地托盘后台：用户主动启动后，仅监测勾选窗口的前台可见文本；风险 ≥70% 发 Windows 通知，可暂停/退出，不开机自启。
- 邮箱适配：QQ 邮箱、163/126、Gmail、Outlook 等页面可提取当前邮件正文，支持“紧急借钱/垫付/住院费”等话术识别。
- 多图同步分析：多张图片并发识别后，再由 DeepSeek 做跨图联合分析，输出图片之间的关联、矛盾与整体风险。
- 图片删除：上传区每张图片有删除按钮；图片采集卡片也支持删除/清空。
- 图片放大：点击左侧上传图片或右侧多模态缩略图，可打开原图预览。
- 速度优化：文本先出本地/数据库快速预判，再异步替换为 AI 复核结果；精确文本缓存 7 天 AI 复核，图片按 SHA-256 缓存视觉结果。
- 文本实时分析：输入即评分，展示风险环、风险等级、诈骗类型、结论摘要。
- 五个可解释评分维度：话术操控 20 / 资金诱导 30 / 信息窃取 25 / 渠道异常 15 / 身份伪装 10。
- 高危词汇与风险证据：展示命中的原文完整片段、权重、命中次数、所属维度；长文本自动换行，不再省略。
- 个人信息暴露检测：手机号、身份证号、银行卡号、邮箱、短信验证码、社交账号，
  默认只返回打码后的值，并支持**一键脱敏**。
- 可疑链接检测：HTTP、IP 地址、短链接、高风险后缀、Punycode、仿冒敏感词。
- 多模态检测：
  - 图片：DeepSeek V4.1 视觉优先；未配置时依次降级 Qwen-VL、**Windows.Media.Ocr** 本地 OCR；
  - 语音：Qwen-ASR 转写后分析；浏览器还支持直接录音上传；
  - 文本 + 图片 + 语音结果会做维度合并与跨模态加成。
- 处置闭环：一键生成举报材料（12321 / 110 / 国家反诈中心 / 平台客服）、导出证据 JSON、
  下载处置报告 TXT、复制结论、标记误报。
- 科普推送：内置 8 类高发诈骗知识与防范要点。

### 每日一反诈

- 3 个真实感案例：机票退改签理赔、冒充客服 + 涉诈 APP、学生刷单返利。
- 案情经过、套路拆解、警方提示，支持“换一例”。

### 反诈问答

- 5 道情景题，即时判分、解析与防骗等级。

### 知识宣传

- 从 SQL Server `knowledge` 表读取科普内容；接口不可用时自动回退到前端内置版本。
- 防骗“三不一多”与预警求助渠道。

### 历史记录 / 运行日志

- 历史记录保存在 SQL Server：按关键词、风险等级、来源筛选，查看详情、导出、删除、标记误报。
- 运行日志记录检测、举报、导出、反馈、删除、系统启动等事件，支持级别/事件筛选与自动刷新。

---

## 二、技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | HTML5 + CSS3 + 原生 JavaScript（无框架） |
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 数据库 | SQL Server（默认本机 LocalDB `(localdb)\MSSQLLocalDB`，自动建库建表） |
| 数据访问 | pyodbc |
| 图片处理 | Pillow + Windows.Media.Ocr（本地兜底） |
| 多模态 AI | DeepSeek V4.1 Flash：`deepseek-flash`（文本 + 视觉）；Qwen：`qwen3-asr-flash`（语音，可选） |
| 交易风控 | LightGBM 4.7 + scikit-learn 1.9 + joblib |
| 关键词匹配 | pyahocorasick Aho-Corasick 自动机 |

---

## 三、目录结构

```text
A_NGIT/
├── HTML+CSS/                      # 前端（保持团队约定的 HTML+CSS 目录）
│   ├── html/
│   │   ├── index.html             # AI 管家 + 每日一反诈 + 反诈问答 + 知识宣传
│   │   ├── chat.html              # 可选：双人远程聊天（独立页，不在主导航）
│   │   ├── chat-test.html         # 单人聊天测试页（居中）
│   │   ├── history.html           # 历史检测记录
│   │   └── logs.html              # 运行日志
│   ├── css/
│   │   └── style.css              # 全站样式（设计变量 / BEM / 响应式）
│   └── js/
│       ├── api.js                 # API 客户端
│       ├── app.js                 # 主页面交互与多模态检测
│       ├── chat.js                # 可选：双人远程聊天 WebSocket
│       ├── chat-test.js           # 单人聊天测试页脚本
│       ├── history.js             # 历史记录页（含回收站）
│       ├── user.js                # 用户中心 / API 配置页
│       └── logs.js                # 日志页
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 路由、上传、报告、静态页面
│   │   ├── analyzer.py            # 五维评分、话术库、PII、链接、跨模态合并
│   │   ├── case_matcher.py        # 文本案例匹配、相似度、自动收录
│   │   ├── content_store.py       # 用户暂存库与图片案例库
│   │   ├── guardian.py            # Guardian-AI 关键词/加权评分/分省案例
│   │   ├── text_normalize.py      # 全角转半角与干扰符号清洗
│   │   ├── result_cache.py        # 相同文本短 TTL 缓存
│   │   ├── deepseek.py            # DeepSeek 文本/视觉适配
│   │   ├── ai_common.py           # AI JSON 解析与证据转换
│   │   ├── qwen.py                # Qwen 语音/备用视觉适配
│   │   ├── ocr.py                 # Windows OCR 本地兜底
│   │   ├── ocr_windows.ps1        # WinRT OCR 调用脚本
│   │   ├── db.py                  # SQL Server 连接与建库
│   │   ├── repository.py          # 数据仓储层
│   │   ├── user_db.py             # 用户中心与租户数据
│   │   ├── runtime_ai.py          # 运行时 OpenAI 兼容 API
│   │   ├── tenant.py              # user_id / user_key 租户上下文
│   │   ├── maintenance.py         # 时效数据与回收站维护
│   │   └── config.py              # 环境变量与路径
│   ├── ml/                        # 交易风控特征工程与训练脚本
│   ├── models/                    # LightGBM 模型、元数据、规则 JSON
│   ├── database/schema.sql        # 表结构 + 科普种子数据
│   ├── database/user_schema.sql   # 用户中心库表结构
│   ├── data/                      # 上传文件、关键词与分省案例
│   ├── seed_demo.py               # 演示数据初始化
│   ├── requirements.txt
│   └── run.py                     # 开发启动入口
├── docs/                          # 需求文档、改造指令、截图、测试素材
├── scripts/                       # 快捷方式创建、发布打包、文档生成
├── database/                      # 本机 SQL Server 数据文件与备份（不提交）
├── bootstrap.py                   # 首次安装初始化（建库/种子/访问密钥）
├── install.bat / start.bat        # 安装 / 启动
├── start_console.bat / verify.bat # 调试启动 / 健康检查
├── license_server/app.py          # Flask 授权/数据库接口（可选，默认 5050）
├── start_license.bat              # 启动 Flask 授权服务
├── .env.example                   # 环境变量示例
├── run.bat / setup.bat            # 兼容旧入口
├── README.md
└── README_安装说明.md
```

---

## 四、快速启动

> 发布包分两款：**Guardian-AI_Server**（本机部署/管理员，运行 install.bat）和 **Guardian-AI_Client**（普通用户，运行 Client-Setup.bat，只连中心服务器）。详见 [README_安装说明.md](README_安装说明.md) 和 [README_客户端安装说明.md](README_客户端安装说明.md)。

### 1. 安装依赖

```bash
python -m pip install -r backend/requirements.txt
```

Windows 也可以直接双击 `setup.bat`。

### 2. 配置（可选）

```bash
copy .env.example .env
```

不配置 `.env` 也能启动：默认连接本机 LocalDB，自动创建 `AntiFraudGuard` 数据库、
表结构和科普种子数据。

如果本机没有 LocalDB，可在 `.env` 中改为正式 SQL Server：

```ini
DB_SERVER=localhost
DB_NAME=AntiFraudGuard
DB_TRUSTED=no
DB_USER=sa
DB_PASSWORD=你的密码
```

### 3. 启动

```bash
python backend/run.py
```

或双击 `run.bat`。浏览器打开：

<http://127.0.0.1:8000/>

> 也可以使用 `uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000` 启动。
> 单人聊天测试：打开 `http://127.0.0.1:8000/chat-test.html`。
> 本地后台：`python backend/desktop/guardian_tray.py` 或双击 `run_tray.bat`。
> 直接双击 HTML 文件也能查看页面，但 API 会回退到 `http://127.0.0.1:8000`，仍需启动后端。

### 4. 初始化演示数据（可选）

```bash
python backend/seed_demo.py
# 强制清空旧记录后重建
python backend/seed_demo.py --force
```

---

## 五、AI 模型配置

### 1. DeepSeek V4.1 Flash（默认优先）

官方模型名 `deepseek-flash`，原生支持**文本 + 图像**理解，接口为 OpenAI 兼容的
`https://api.deepseek.com/chat/completions`。

在 <https://platform.deepseek.com/> 创建 API Key 后写入 `.env`：

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_VISION_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT=90
```

> 官方 API Key 需要 `sk-` 前缀；如果只拿到 32 位密钥，项目会自动补全前缀。

### 2. Qwen（语音 ASR 与备用视觉）

在 <https://bailian.console.aliyun.com/> 开通百炼并创建 API Key：

```ini
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxx
QWEN_TEXT_MODEL=qwen-plus
QWEN_VL_MODEL=qwen-vl-max
QWEN_AUDIO_MODEL=qwen3-asr-flash
```

### 3. 启用后的行为

| 模态 | 优先方案 | 兜底方案 |
| --- | --- | --- |
| 文本 | DeepSeek V4.1 Flash + 本地规则融合 | Qwen 文本 → 本地规则 |
| 图片 | DeepSeek V4.1 视觉理解 | Qwen-VL → Windows OCR → 本地规则 |
| 语音 | Qwen-ASR 转写 | 手动补充转写文本 |

说明：

- DeepSeek V4.1 Flash 当前只支持文本 + 图像，不支持音频；语音仍走 Qwen-ASR。
- 两个模型的 Key 都未配置时，页面显示“规则引擎 v1”；图片 OCR 成功时显示“OCR + 规则”。
- 配置 DeepSeek 后，页面右上角显示“DeepSeek V4.1”。
- AI 结果只作为语义增强与补充证据，最终评分仍保存完整维度与规则证据，方便答辩解释。

---

## 六、Guardian-AI 速度与缓存策略

为避免每次检测都等待大模型，Guardian-AI 采用分层过滤：

1. **关键词秒判**：265 条关键词规则用 Aho-Corasick 自动机一次扫描；明显高风险/明显低风险直接返回，不调用 AI；
2. **短 TTL 缓存**：相同文本 10 分钟内直接返回内存中的结果；
3. **案例缓存**：完全相同的文本可复用 7 天内 AI 复核结果；相同图片按 SHA-256 复用视觉结果；
4. **全链路并行**：文本分析、图片视觉、图片 OCR、语音 ASR 使用 asyncio 并行，总耗时取最慢一路；多图再统一做跨图联合研判。
5. **本地模型 INT8**：若后续接入本地 ONNX 语义模型，可用 backend/ml/quantize_onnx_int8.py 做动态 INT8 量化；当前快速路径是 AC 自动机 + 规则，不需要量化。

只有模糊文本才交给 DeepSeek 精判；首次全新内容仍走完整 AI，重复/相似内容走缓存加速。

## 七、评分真源

风险分只由后端 analyzer 的五维评分产生：话术操控 20 / 资金诱导 30 / 信息窃取 25 / 渠道异常 15 / 身份伪装 10。

Guardian-AI 的 30/25/20/15/10 仅作为可解释分量展示，不再覆盖 risk_score；前端不参与任何关键词、评分或推断。

风险等级：0-19 低、20-49 中、50-89 高、90-100 极高。

规则引擎同时处理：科普语境降权、PII 打码与原文偏移、链接风险、多模态融合。

## 八、交易风控模型（附加）

Kaggle Indian Financial Fraud Dataset 是 4 张表、25 万条合成交易、约 5.39% 欺诈的表格数据，不含聊天话术。

- 模型：Guardian-AI-Transaction（LightGBM 二分类），输出交易欺诈概率；
- 规则：从 Fraud_Reason 与数据分布提炼 7 条规则，写入 transaction_rules；
- 指标：AUC-ROC 0.9814，AUC-PR 0.8667，阈值 0.8878，F1 0.7654；
- 注意：不用于微调 DeepSeek LLM；话术识别仍走 text_cases。

训练：python backend/ml/train_transaction_model.py --data-dir backend/data/indian_fraud

接口：POST /api/transaction/risk、GET /api/transaction/model-info、GET /api/transaction/rules。

## 九、主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务与数据库健康检查 |
| GET | `/api/config` | 前端读取 AI Provider 启用状态与上传限制 |
| POST | `/api/analyze/text` | 文本检测，`save=false` 仅预览不落库 |
| POST | `/api/analyze` | 多模态检测（multipart：`text` / `note` / `save` / `files`） |
| GET | `/api/history` | 历史记录分页、关键词/等级/来源筛选 |
| GET | `/api/history/{id}` | 记录详情（含文件、举报材料） |
| DELETE | `/api/history/{id}` | 删除记录 |
| POST | `/api/history/{id}/feedback` | 标记误报 |
| GET | `/api/history/{id}/export` | 导出证据 JSON |
| GET | `/api/history/{id}/report.txt` | 下载处置报告 TXT |
| POST | `/api/reports` | 生成举报材料 |
| GET | `/api/reports/{id}/download` | 下载举报材料 |
| GET | `/api/stats` | 检测统计 |
| GET | `/api/logs` | 运行日志分页与筛选 |
| POST | `/api/transaction/risk` | 交易欺诈概率 + 规则命中 + 风险等级 |
| GET | `/api/transaction/model-info` | 交易模型指标与可用状态 |
| GET | `/api/transaction/rules` | 交易风控规则列表 |
| WS | `/ws/chat/{room}` | 双人模拟聊天转发（内存，不写库） |
| GET | `/api/logs/stats` | 日志级别统计 |
| GET | `/api/knowledge` | 科普内容 |
| GET | `/api/guardian/provinces` | 分省案例省份统计 |
| GET | `/api/guardian/cases` | 按省份/类别读取案例示例 |

交互式 API 文档：<http://127.0.0.1:8000/docs>

---

## 十、数据库

数据库：`AntiFraudGuard`

| 表 | 用途 |
| --- | --- |
| `staging_contents` | 当前用户暂存：文本、图片、语音原始内容与 OCR/转写结果 |
| `text_cases` | 文本案例库：种子 + 自动收录 + 语音转写文本，支持精确/相似匹配 |
| `image_cases` | 图片案例库：图片 SHA-256、OCR 文本、视觉研判结果与命中次数 |
| `analyses` | 每次检测的综合结果、五维评分 JSON、误报标记、举报次数 |
| `images` | 图片/语音文件元数据、OCR 文本、缩略图、SHA-256 |
| `reports` | 生成的举报材料与举报渠道 |
| `logs` | 检测、举报、导出、反馈、删除、系统事件 |
| `knowledge` | 反诈科普种子内容 |
| `guardian_keywords` | 265 条 Guardian-AI 关键词规则 |
| `guardian_cases` | 411 条分省青少年反诈案例 |

`backend/database/schema.sql` 可重复执行；首次启动会自动建库建表、写入科普种子与 7 条内置反诈案例。
后续未命中的文本会自动写入 `text_cases`（入库前对 PII 打码），图片写入 `image_cases`，语音转写后写入 `text_cases`；当前用户的原始内容同时写入 `staging_contents`。

---

## 十一、演示建议

1. 打开首页，默认示例文本会立即得到 70% 左右的高风险结论；
2. 指出五个评分维度、命中的证据原文、风险等级；
3. 上传一张包含“验证码 / 屏幕共享 / 转账”的聊天截图，展示 DeepSeek V4.1 视觉理解与跨模态融合；
4. 粘贴包含手机号、身份证、银行卡、验证码的文本，展示 PII 打码与“一键脱敏”；
5. 点击“一键举报”，生成举报编号与结构化材料，展示闭环；
6. 打开“历史记录”查看 SQL Server 落库结果，打开“运行日志”展示审计链路；
7. 最后用“反诈问答”和“知识宣传”收尾，体现科普与青年教育价值。

---

## 十二、模拟聊天与本地托盘后台

### 单人聊天测试页

chat-test.html 是独立页面：聊天窗口居中，按“对方 / 你”显示秒级时间，内置正常聊天、游戏皮肤、刷单返利、冒充公检法等场景。

### 本地托盘后台（替代浏览器插件）

浏览器插件已整体删除，不再向所有网页注入脚本。改为用户主动启动的 Windows 托盘程序：

python backend/desktop/guardian_tray.py

或双击 run_tray.bat。

- 首次启动弹授权说明，用户勾选要监测的微信/QQ 窗口；
- 只有被勾选窗口处于前台时才读取可见文本；
- 不读取输入框、密码框、Cookie、历史消息；
- UIA 读取失败时才做低频截图 OCR，不落盘；
- 原始文本不写盘，只把结果写入本地告警队列；
- 风险 ≥70% 发 Windows 系统通知，数秒淡出、不抢焦点；
- 托盘可见，可暂停/继续/选择窗口/退出，不开机自启。

### 安全与外部模型

- API 绑定 127.0.0.1，非本机请求默认只使用基础库/本地规则；
- API 默认要求本地令牌（页面 Cookie 或 X-Guardian-Token）；
- 只有配置了本机指纹且请求来自回环地址时，才允许调用 DeepSeek；
- 外部模型总开关与机器指纹在 .env 配置，不写入代码；
- 本地令牌自动生成到 backend/data/.local_api_token，不提交 Git。

## 十三、安全与限制

- 所有 PII 在接口返回前已打码，原始值不通过 API 返回；一键脱敏后原文本会立即替换。
- 举报材料不会自动提交给官方平台，只生成可复制的结构化文本，避免误报与越权。
- 规则引擎是**辅助判断**，不能替代警方或法律意见；高风险结论应提示用户拨打 96110 / 110。
- Windows OCR 依赖本机已安装的中文 OCR 语言包；非 Windows 环境自动跳过，只做文件与元数据校验。
- DeepSeek / Qwen 调用失败会自动降级到本地规则或 OCR，不影响检测主流程。
- 上传文件保存在 `backend/data/`，不提交到 Git；生产部署应接入对象存储、鉴权与访问审计。

---

## 十四、代码规范

- 前端 2 空格缩进，CSS 使用 BEM 命名，颜色/圆角/字体统一收敛到 `:root` 变量；
- 后端按 `config → db/repository → analyzer/qwen/ocr → main` 分层，路由不直接写 SQL；
- 分析结果统一为 JSON，保留维度、证据、建议与引擎信息，方便前端渲染与答辩讲解；
- 提交信息建议使用 `feat:` / `fix:` / `style:` / `docs:` 前缀。

## 十五、团队协作

- 仓库默认分支：`main`；
- 建议每人使用独立分支，例如 `feature/analysis-engine`；
- 合并前发起 Pull Request，至少 1 人 Review；
- 协作者权限在 GitHub **Settings → Collaborators** 中邀请。