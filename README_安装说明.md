# Guardian-AI 安装说明

Guardian-AI 是一个本地运行的 Web + FastAPI 后端反诈识别系统，支持文本、图片、语音分析，以及桌面聊天监测。

## 一、环境要求

| 组件 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11 64 位 |
| Python | 3.10 - 3.12（64 位，安装时勾选 Add to PATH） |
| 数据库 | SQL Server LocalDB 2019+ 或 SQL Server Express |
| 驱动 | ODBC Driver 17 for SQL Server |
| 磁盘 | 建议预留 2 GB（依赖 + 模型 + 数据库） |

> 安装目录不要选 C:\Program Files 等受保护目录；建议使用 D:\Guardian-AI 等可写目录。

## 二、安装

1. 解压安装包到任意临时目录（例如 Downloads）。
2. 双击 install.bat，打开安装窗口。
3. 选择安装目录：默认 D:\Guardian-AI，可点“浏览…”安装到其他盘或目录。
4. 按需填写服务端口（默认 8000），选择是否使用国内 PyPI 镜像、是否创建快捷方式、是否安装后启动。
5. 点击“开始安装”。安装器会自动：
   - 把程序文件复制到所选目录；
   - 创建 .venv 虚拟环境并联网下载 Python 依赖；
   - 生成/写入 .env 配置；
   - 在安装目录下的 database/mssql 初始化数据库；
   - 创建桌面和开始菜单的 Guardian-AI 快捷方式。
6. 安装完成后，统一访问密钥会写入项目根目录 **access_key.txt**（不在安装界面显示）；请把它发给需要使用软件的普通用户。若数据库已存在，沿用原有访问密钥。

## 三、其他用户客户端安装（只连服务器，不装数据库）

如果其他用户要使用你电脑上的中心数据库，不要让他们运行 install.bat（那会在他们本机建独立数据库）。请把安装包发给他们，让他们运行：

1. **Client-Setup.bat**
2. 选择安装目录（默认当前用户目录下的 Guardian-AI）
3. 填写管理员提供的公网服务器地址（例如 `https://xxx.ts.net` 或 Cloudflare 地址）
4. 点击“开始安装”，会创建桌面/开始菜单 Guardian-AI 快捷方式，以应用窗口打开网页。

客户端特点：

- 不需要安装 Python、SQL Server 或后端；
- 不保存本地数据库，所有账号、检测、上传数据都写入服务器数据库；
- 登录仍需邮箱 + 密码 + 统一访问密钥；
- 普通用户能看到服务器上的科普、案例、知识等非用户数据，但只能读写自己的用户数据；
- 服务器必须开机并保持 Tailscale Funnel / Cloudflare 隧道运行。

## 四、启动与使用

- 双击桌面 Guardian-AI，或运行 start.bat。
- 首次启动会弹出 UAC，请选择“是”（桌面聊天监测需要管理员权限）。
- 浏览器打开 http://127.0.0.1:8000/
- 普通用户：点击“登录 / 注册”，使用邮箱 + 密码 + **统一访问密钥**；邮箱不存在时会自动注册（最多 7 个普通用户）。
- 管理员账号由安装器自动初始化，不在安装界面或普通界面展示。
- 在 API 页填写任意 OpenAI 兼容接口（地址、Key、模型），自动同步并测试。
- 在个人信息中可查看用户 ID 与数据键（如 u1002:user@example.com）。

## 五、配置 AI

安装完成后打开网页，登录账号，在 **API** 页填写任意 OpenAI 兼容接口（地址、Key、模型），保存后自动同步并测试；配置按用户保存在本地数据库，下次登录自动恢复。

安装器不会收集 AI Key。高级用户也可以编辑项目根目录 .env，配置 DeepSeek/Qwen 作为默认兜底：

DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash

不配置也能使用本地规则引擎与 Windows OCR。

## 六、数据位置

- 数据库文件：database/mssql/（首次初始化自动创建）
- 数据库备份：database/backup/
- 临时对话 / 上传 / 缩略图 / 日志：backend/data/
- 用户数据按 u{user_id}:{username} 隔离；删除记录进入 30 天回收站。
- 普通用户最多 7 个，每个用户存储上限 1GB；管理员账号不占名额、不受普通配额限制。

> 移动整个项目目录后，SQL Server 中的数据库仍指向旧路径。请先备份，或在原位置继续使用；不要只移动文件夹。

## 七、验证与排错

运行 verify.bat 检查后端状态。

| 问题 | 处理 |
|---|---|
| 找不到 Python | 安装 Python 3.10-3.12 并勾选 Add to PATH |
| pip 安装慢/失败 | 使用国内镜像：.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple |
| 无法连接数据库 | 安装 SQL Server LocalDB 2019+ 与 ODBC Driver 17；运行 sqllocaldb info 检查 |
| 端口 8000 被占用 | 关闭占用程序，或修改 .env 的 APP_PORT |
| 页面打不开 | 查看 backend/data/backend.log，运行 start_console.bat 查看报错 |
| 托盘/监测无反应 | 确认 UAC 已允许；查看 backend/data/tray.log |
| 登录提示访问密钥错误 | 打开项目根目录 access_key.txt，使用其中 32 位统一密钥 |
| 普通用户无法注册 | 检查是否已达 7 个普通用户上限 |

## 八、卸载

1. 退出托盘程序。
2. 删除桌面/开始菜单快捷方式。
3. 删除整个项目目录即可（数据库文件也在 database/mssql）。
4. 如需彻底清理，可在 SSMS 中删除 AntiFraudGuard 与 user 数据库。

## 九、安全提示

- .env 与 access_key.txt 含敏感凭据，不要上传或分享。
- 访问密钥为全系统统一密钥，请只发给可信用户；可在服务器运行 scripts/generate_access_key.py 轮换。
- 后端只监听 127.0.0.1；公网访问通过 Tailscale Funnel / Cloudflare 隧道，不要直接开放 8000 或 SQL 1433 端口。
