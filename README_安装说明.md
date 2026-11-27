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
4. 按需填写：
   - 服务端口（默认 8000）
   - root 初始密码（已预填随机值）
   - 是否使用国内 PyPI 镜像、是否创建快捷方式、是否安装后启动
5. 点击“开始安装”。安装器会自动：
   - 把程序文件复制到所选目录；
   - 创建 .venv 虚拟环境并联网下载 Python 依赖；
   - 生成/写入 .env 配置；
   - 在安装目录下的 database/mssql 初始化数据库；
   - 创建桌面和开始菜单的 Guardian-AI 快捷方式。
6. root 初始密码显示在安装日志末尾，请保存。若检测到已有数据库，root 密码保持不变。

## 三、启动与使用

- 双击桌面 Guardian-AI，或运行 start.bat。
- 首次启动会弹出 UAC，请选择“是”（桌面聊天监测需要管理员权限）。
- 浏览器打开 http://127.0.0.1:8000/
- 登录：账号 root，密码为安装时生成并显示的密码。
- 在 API 页填写任意 OpenAI 兼容接口（地址、Key、模型），自动同步并测试。
- 在个人信息中可查看用户 ID 与数据键（如 u1001:root）。

## 四、配置 AI

安装完成后打开网页，登录账号，在 **API** 页填写任意 OpenAI 兼容接口（地址、Key、模型），保存后自动同步并测试；配置按用户保存在本地数据库，下次登录自动恢复。

安装器不会收集 AI Key。高级用户也可以编辑项目根目录 .env，配置 DeepSeek/Qwen 作为默认兜底：

DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash

不配置也能使用本地规则引擎与 Windows OCR。

## 五、数据位置

- 数据库文件：database/mssql/（首次初始化自动创建）
- 数据库备份：database/backup/
- 临时对话 / 上传 / 缩略图 / 日志：backend/data/
- 用户数据按 u{user_id}:{username} 隔离；删除记录进入 30 天回收站。

> 移动整个项目目录后，SQL Server 中的数据库仍指向旧路径。请先备份，或在原位置继续使用；不要只移动文件夹。

## 六、验证与排错

运行 verify.bat 检查后端状态。

| 问题 | 处理 |
|---|---|
| 找不到 Python | 安装 Python 3.10-3.12 并勾选 Add to PATH |
| pip 安装慢/失败 | 使用国内镜像：.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple |
| 无法连接数据库 | 安装 SQL Server LocalDB 2019+ 与 ODBC Driver 17；运行 sqllocaldb info 检查 |
| 端口 8000 被占用 | 关闭占用程序，或修改 .env 的 APP_PORT |
| 页面打不开 | 查看 backend/data/backend.log，运行 start_console.bat 查看报错 |
| 托盘/监测无反应 | 确认 UAC 已允许；查看 backend/data/tray.log |

## 七、卸载

1. 退出托盘程序。
2. 删除桌面/开始菜单快捷方式。
3. 删除整个项目目录即可（数据库文件也在 database/mssql）。
4. 如需彻底清理，可在 SSMS 中删除 AntiFraudGuard 与 user 数据库。

## 八、安全提示

- .env 含密钥，不要上传或分享。
- root 密码只保存在本机数据库；请妥善保管。
- 本程序仅监听 127.0.0.1，不要将端口暴露到公网。
