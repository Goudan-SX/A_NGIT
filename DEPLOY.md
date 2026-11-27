# 反诈卫士 · 部署与 API 配置指南

## 一、环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端 + 托盘 |
| SQL Server | 2019+ / LocalDB | 案例库与历史记录 |
| ODBC Driver 17 | 17.x | SQL Server 连接驱动 |
| Windows 10/11 | x64 | 托盘依赖 uiautomation |

## 二、安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/Goudan-SX/A_NGIT.git
cd A_NGIT

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
copy .env.example .env
# 编辑 .env，填入 API 密钥（见第三节）

# 5. 启动
# 方式一：双击桌面快捷方式（需管理员权限）
# 方式二：python backend/run.py
```

## 三、API 密钥配置

编辑 `.env` 文件，按需填入以下密钥。**所有密钥均不上传 GitHub**（.env 已在 .gitignore 中）。

### 3.1 DeepSeek（必填）

反诈卫士的主要 AI 引擎，用于文本分析、视觉识别（聊天截图布局/联系人识别）、案例复审。

```
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_VISION_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT=90
```

**获取方式**：
1. 访问 https://platform.deepseek.com
2. 注册并登录
3. 进入「API Keys」页面，创建新 Key
4. 复制 `sk-` 开头的密钥填入 `DEEPSEEK_API_KEY`

### 3.2 Qwen / 通义千问（选填）

用于语音 ASR 转写和备用多模态识别。不配置时系统仍可运行（规则引擎 + DeepSeek）。

```
QWEN_API_KEY=sk-your-key-here
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VL_MODEL=qwen-vl-max
QWEN_AUDIO_MODEL=qwen3-asr-flash
QWEN_TIMEOUT=60
```

**获取方式**：
1. 访问 https://dashscope.aliyun.com
2. 开通「百炼」服务
3. 进入 API-KEY 管理，创建 Key

### 3.3 SQL Server（必填）

默认使用 Windows LocalDB，无需额外安装。如使用正式 SQL Server：

```
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_SERVER=your_server
DB_NAME=AntiFraudGuard
DB_TRUSTED=no
DB_USER=sa
DB_PASSWORD=your_password
DB_ENCRYPT=no
```

首次启动时自动建库建表并导入种子案例。

### 3.4 安全配置（选填，默认自动生成）

```
# 机器指纹：绑定令牌到当前设备，防止令牌被复制到其他机器使用
AUTHORIZED_MACHINE_ID=

# 本地 API 令牌：Web 前端访问后端 API 的凭证
# 留空则自动生成并写入 backend/data/.local_api_token
LOCAL_API_TOKEN=
```

## 四、启动方式

### 4.1 桌面快捷方式（推荐）

双击桌面「Guardian-AI 反诈卫士」快捷方式 → UAC 点「是」。

会同时启动：
- 后端 FastAPI（127.0.0.1:8000）
- 托盘守护进程（1.5s 轮询前台聊天窗口）
- 告警浮层（独立进程）

### 4.2 命令行

```bash
python backend/run.py
```

### 4.3 访问 Web 界面

启动后浏览器打开 http://127.0.0.1:8000

## 五、功能说明

| 功能 | 说明 |
|------|------|
| AI 管家 | 实时监测 QQ/微信聊天窗口，AI 识别诈骗话术 |
| 对话用户 | 按对方 ID 隔离的临时对话库（全量入库，1 天 TTL） |
| 反诈问答 | 从 411 条真实案例动态生成 5 道题 |
| 知识宣传 | 12 类诈骗类型科普 + 分省真实案例 |
| IP 省份选择 | 导航栏选择所在地，本地速览穿插同省案例 |
| 反诈科普 | 检测≥70% 时展示对应类型科普 + 真实案例 |
| 本地速览 | 30 条反诈小知识随机滚动（6 秒轮换） |

## 六、常见问题

### Q: 启动后 Web 页面打不开？
确认后端进程在运行（任务管理器查找 pythonw.exe），检查 8000 端口未被占用。

### Q: 托盘不检测聊天内容？
确保 QQ/微信窗口在前台。托盘只检测当前前台窗口。

### Q: OCR 出现乱字？
Windows OCR 可能将汉字拆成偏旁。系统已内置拆字修复（亻尔→你、扌巴→把等 30+ 组）。如遇新乱码，在 `backend/app/ocr.py` 的 `_SPLIT_CHAR_FIX` 字典中补充。

### Q: 如何切换 AI 模型？
修改 `.env` 中的 `DEEPSEEK_MODEL` / `QWEN_TEXT_MODEL`，重启后端生效。

### Q: 数据库迁移？
LocalDB 数据存储在用户目录。切换 SQL Server 时，首次启动自动建库建表并导入种子数据。

## 七、目录结构

```
A_NGIT/
├── backend/
│   ├── app/           # FastAPI 后端
│   │   ├── main.py        # 路由与业务逻辑
│   │   ├── analyzer.py    # 规则分析引擎
│   │   ├── guardian.py    # 关键词 + 分省案例
│   │   ├── case_library.py # 411条真实案例库
│   │   ├── ocr.py         # Windows OCR + 拆字修复
│   │   ├── security.py    # 本地令牌安全
│   │   └── conversation_store.py # 临时对话库
│   ├── desktop/       # 托盘 + 告警浮层
│   │   ├── guardian_tray.py   # 托盘守护
│   │   ├── alert_overlay.py   # 告警浮层
│   │   └── launcher.py        # 启动器
│   └── data/          # 运行时数据（不上传）
│       ├── case_library.csv  # 411条案例CSV
│       └── guardian_keywords.json
├── HTML+CSS/          # Web 前端
│   ├── html/
│   ├── css/
│   └── js/
├── .env.example       # 环境变量模板
├── .gitignore
└── DEPLOY.md          # 本文档
```
