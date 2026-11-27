# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = str(ROOT / "docs" / "A_NGIT_需求文档.docx")

doc = Document()
doc.core_properties.title = "A_NGIT 反诈卫士 需求文档"
doc.core_properties.subject = "根据对话整理的完整需求"
doc.core_properties.author = "Guardian-AI"

# page + base font
section = doc.sections[0]
section.top_margin = Cm(2.2)
section.bottom_margin = Cm(2.2)
section.left_margin = Cm(2.4)
section.right_margin = Cm(2.4)

normal = doc.styles["Normal"]
normal.font.name = "Microsoft YaHei"
normal.font.size = Pt(10.5)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
normal.paragraph_format.line_spacing = 1.35
normal.paragraph_format.space_after = Pt(4)

for name, size, color in [("Heading 1", 15, "1F4E79"), ("Heading 2", 12, "2E75B6")]:
    style = doc.styles[name]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = RGBColor.from_string(color)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    style.paragraph_format.space_before = Pt(12)
    style.paragraph_format.space_after = Pt(6)

def para(text="", bold=False, size=10.5, color=None, align=None, space_after=4):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    return p

def bullet(text, level=0):
    style = "List Bullet" if level == 0 else "List Bullet 2"
    p = doc.add_paragraph(text, style=style)
    for run in p.runs:
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        run.font.size = Pt(10.5)
    p.paragraph_format.space_after = Pt(2)
    return p

def code(text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(6)
    return p

def table(headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.name = "Microsoft YaHei"
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
                r.font.size = Pt(9.5)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
            for p in cells[i].paragraphs:
                for r in p.runs:
                    r.font.name = "Microsoft YaHei"
                    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
                    r.font.size = Pt(9.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

# Cover
para("Guardian-AI", bold=True, size=12, color="2E75B6", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
para("A_NGIT 反诈卫士", bold=True, size=26, color="1F4E79", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
para("完整需求文档", bold=True, size=20, color="1F4E79", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
para("根据本次对话整理 · 2026-11-28", size=10, color="7F7F7F", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
para(f"目标目录：{ROOT}", size=9, color="7F7F7F", align=WD_ALIGN_PARAGRAPH.CENTER)
doc.add_page_break()

# 1
doc.add_heading("一、项目与交付方式", level=1)
bullet("项目目标：面向青年的 AI 诈骗识别与个人信息保护助手，覆盖文本、图片、语音与本地聊天监测。")
bullet("技术栈：HTML + 原生 CSS + 原生 JavaScript；Python + FastAPI + SQL Server LocalDB。")
bullet("前端文件分类：HTML+CSS/html、HTML+CSS/css、HTML+CSS/js；后端：backend/app、backend/database。")
bullet("视觉风格：白底、蓝色、圆润、页面居中规整；字体微软雅黑，正文约 14px；不擅自改变现有设计风格。")
bullet("必须严格按用户提供的《A_NGIT 改造指令》执行，不自行增加无关需求；文件/行号不一致时先停止并报告。")
bullet("每次修改完成后整理改动、提交并推送到 GitHub，保持远端 main 最新。")
bullet("最终交付按四部分说明：按节改动、API/数据库契约变化、启动与回归步骤、未解决事项。")
bullet("不新建额外的总结 Markdown 文件；只维护现有 README。")
bullet("配置类任务直接代为操作并验证，不只给步骤；完成后给出当前状态、测试入口和排错方法。")
bullet("优先零成本/免费方案，不额外付费；可先保留 API 接口，后续再接。")

# 2
doc.add_heading("二、已确认的三个决策", level=1)
for title, text in [
    ("决策 1A", "整体删除 extension/ 浏览器插件，改为 Python 本地托盘后台服务；不再使用悬浮球、浏览器注入或全站内容脚本。"),
    ("决策 2", "不修改数据库已有数据、不重建数据库、不清空历史数据；新逻辑必须兼容旧数据。"),
    ("决策 3A", "允许脱敏后调用外部大模型；必须识别机器身份：本机回环 + 机器指纹匹配才使用 DeepSeek；非本机/未授权使用基础库、本地规则或免费模型；Key 放 .env，不提交 Git。"),
]:
    p = doc.add_paragraph()
    r = p.add_run(title + "：")
    r.bold = True
    r.font.name = "Microsoft YaHei"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    p.add_run(text)

# 3
doc.add_heading("三、P0 安全基线", level=1)
bullet("后端默认绑定 127.0.0.1，不默认暴露局域网。")
bullet("CORS 使用精确白名单，不使用通配符。")
bullet("所有 /api/* 默认要求本地令牌：页面使用 HttpOnly Cookie，托盘/脚本使用 X-Guardian-Token；/api/health 可公开；无令牌返回 401。")
bullet("上传图片只认扩展名白名单，移除仅凭 content_type 放行。")
bullet("删除 /uploads、/thumbnails 静态挂载，改为受控媒体接口：缩略图 inline、原图 attachment、nosniff、必须鉴权。")
bullet("PII 位置必须基于原文偏移（raw_start/raw_end）；历史读取、案例入库、暂存库都按原文偏移脱敏。")
bullet("旧数据不改写，只保证接口读取时打码；新写入的暂存 raw_text 必须先脱敏。")
bullet("依赖补齐 pandas；不重建数据库、不改变已有表数据。")

# 4
doc.add_heading("四、评分与关键词频率", level=1)
bullet("风险分唯一真源为后端 analyzer，前端不参与评分、关键词匹配或推断。")
bullet("guardian.compute 只输出五维可解释分量，不再覆盖 risk_score；删除多模态降分回滚补丁，不恢复。")
bullet("关键词库复用现有 guardian_keywords.json，不新建重复词库。")
para("五维评分：", bold=True)
table(["维度", "上限"], [["话术操控", "20"], ["资金诱导", "30"], ["信息窃取", "25"], ["渠道异常", "15"], ["身份伪装", "10"]])
para("关键词频率加分：", bold=True)
table(["命中次数", "加分"], [["3–5 次", "+8"], ["6–9 次", "+18"], ["10–14 次", "+30"], ["≥15 次", "+35"]])
bullet("加分后总分封顶 100；结果返回 keyword_frequency、keyword_frequency_boost；前端显示重复次数与加成。")
para("风险等级：", bold=True)
table(["分数", "等级"], [["0–19", "低风险"], ["20–49", "中风险"], ["50–89", "高风险"], ["90–100", "极高风险"]])

# 5
doc.add_heading("五、告警规则", level=1)
bullet("分数 ≥70：托盘通知 + 桌面白色告警浮层；淡入、闪烁一次、5 秒后自动关闭。")
bullet("分数 ≥90：直接红色告警浮层常驻，不要求第二次命中。")
bullet("红色浮层持续到：被监测窗口离开前台超过 12 秒、窗口关闭、程序退出。")
bullet("告警浮层不能抢焦点、不能打断用户操作。")
bullet("程序端告警必须优先于 Web 端；Web 端允许延迟但不得超过 20 秒。")

# 6
doc.add_heading("六、程序启动与退出", level=1)
bullet("桌面启动程序：D:\\zhuomian\\Guardian-AI 反诈卫士.lnk。")
bullet("双击后请求管理员权限，由用户确认 UAC；授权后默认接受实时监测。")
bullet("托盘只允许一个实例，不能出现两个 G 图标。")
bullet("程序已打开时，双击快捷方式不再请求 UAC、不再启动第二个托盘，直接打开 Web 前端。")
bullet("Web 地址：http://127.0.0.1:8000/。")
bullet("用户退出程序后，所有相关后台进程全部退出：托盘、后端 uvicorn、告警浮层子进程、测试残留进程。")
bullet("不支持开机自启。")
bullet("启动器、托盘、OCR 调用不得弹出 PowerShell/控制台窗口。")
bullet("托盘 UIA 轮询约 1.5 秒；控件树深度 4；最多 60 个节点；单次遍历 0.4 秒截止。")

# 7
doc.add_heading("七、自动监测与检测流程", level=1)
bullet("打开程序后自动监测，不需要用户手动点“检测”。")
bullet("只监测当前前台聊天窗口，不后台偷读其他窗口。")
bullet("只读取当前聊天主区域，不读取左侧会话列表、搜索栏、顶部工具栏、底部输入框、发送按钮、密码框。")
para("统一流程：", bold=True)
code("截图\n→ AI 识别聊天范围（联系人区 + 消息主区域）\n→ 分区 OCR\n→ 过滤左侧会话栏/搜索栏/输入框/告警浮层\n→ 识别对方 ID\n→ 只保留对方消息\n→ 数据库/本地规则初步判断\n→ 立即通知程序端\n→ 后台 AI 对全部数据二次审查\n→ 再同步 Web")
bullet("先对比数据库/案例库给出初步诈骗可能性，再强制 AI 对全部数据二次审查，不因本地高置信跳过 AI。")
bullet("托盘专用接口：POST /api/monitor/analyze。")
bullet("初步结果先返回程序端，程序告警后再更新 Web；AI 复审结果由托盘主动回拉补弹告警。")

# 8
doc.add_heading("八、聊天对象 ID 与消息方向", level=1)
bullet("对方 ID 取聊天区头部的对方名称/ID，不能取窗口标题。")
bullet("QQ 窗口标题里的昵称是当前登录用户，不是对方。")
bullet("示例：窗口标题“旧故里草木深”是当前用户；聊天头部“~”是对方 ID。")
bullet("必须过滤把当前用户昵称误识别为对方 ID 的情况：完全相同、互相包含、相似度 ≥75%、简繁差异（旧/舊）。")
bullet("过滤通用名称：QQ/TIM/微信/WeChat/搜索/发送/未知用户。")
bullet("QQ 当前对方名称即使是“~”也要支持。")
bullet("消息方向：左侧头像/气泡为对方输出，右侧为当前用户输出；只检测对方消息，自己的“好的”等不参与。")
bullet("OCR 必须返回文字行包围盒，按聊天区中线过滤左右侧。")
bullet("不能因为窗口微变、窗口大小变化、QQ 布局不同而定位失效。")

# 9
doc.add_heading("九、微信、QQ 与后续软件适配", level=1)
bullet("微信和 QQ 使用完全相同的处理方式。")
bullet("以后任何需要专门适配的聊天软件，都使用同一套：AI 识别范围 → 联系人 ID → 区域 OCR → 左右侧过滤 → 数据库预判 → AI 复审 → 本机告警 → Web 同步。")
bullet("不再针对每个软件单独写固定坐标。")
bullet("AI 布局接口：POST /api/monitor/layout；联系人接口：POST /api/monitor/contact。")
bullet("布局结果包含 contact、contact_text、chat、confidence；按窗口标题 + 宽高缓存 5 分钟；置信度低于 0.35 回退固定比例；窗口尺寸变化后重新识别。")
bullet("联系人识别失败时不用窗口标题兜底，宁可跳过，不生成错误用户。")

# 10
doc.add_heading("十、对话用户与临时数据库", level=1)
bullet("新建专属临时对话数据库，不写入现有业务表。")
bullet("以对方 ID 为数据 ID，每个 ID 数据隔离、独立检测。")
bullet("只保存该 ID 相关的当前聊天数据；只保存可能含诈骗信息的数据，风险低于 40 不保存。")
bullet("文本格式：时间 ： 对方ID：聊天数据。")
bullet("长文本截断：单条最多 500 字，总文本最多 3000 字，优先保留最新消息。")
bullet("重复内容相似度 ≥90% 时，以最新数据为准。")
bullet("默认保存 1 天，到期自动清理；网页端可手动删除记录。")
bullet("网页导航新增“对话用户”，支持下拉选择、卡片载入、删除。")
bullet("显示对方 ID、风险分、等级、摘要、更新时间、过期时间；高风险 ID 前加 ⚠，橙色/红色标记。")
bullet("不同用户之间不得混淆数据。")

# 11
doc.add_heading("十一、Web 前端", level=1)
bullet("保留原白底、蓝色、圆润、居中风格，不改变视觉设计。")
bullet("导航：AI 管家、每日一反诈、反诈问答、知识宣传、图片采集、对话用户。")
bullet("首页默认不显示诈骗示例文本，输入框为空；“载入示例”只在用户主动点击时加载。")
bullet("风险结果区分：客观命中 hits 实线红色；主观推断 inferences 虚线紫色；显示置信度和“推断，非事实”。")
bullet("原文对照支持：完整原文、敏感表达高亮、标记与卡片双向定位、类型筛选、隐藏标记。")
bullet("前端不得包含关键词匹配、评分、推断逻辑，只渲染后端结构化结果。")
bullet("后端不可用时只显示错误态，不得用硬编码 86 分等假数据兜底。")
bullet("API 请求超时 30 秒；托盘结果自动同步 Web，Web 延迟不超过 20 秒。")

# 12
doc.add_heading("十二、数据库与接口", level=1)
bullet("现有 SQL Server LocalDB 数据库不修改、不重建。")
bullet("新增临时对话库使用独立 SQLite：backend/data/conversations.db。")
para("关键接口：", bold=True)
code("POST   /api/monitor/analyze      # 托盘初步检测\nPOST   /api/monitor/publish      # 程序告警后同步 Web\nGET    /api/monitor/latest       # Web 轮询最新结果\nPOST   /api/monitor/layout       # AI 识别聊天范围\nPOST   /api/monitor/contact      # AI 识别对方名称\nGET    /api/conversations        # 对话用户列表\nGET    /api/conversations/{id}   # 单用户数据\nDELETE /api/conversations/{id}   # 删除记录\nPOST   /api/analyze/preview      # Web 本地快速预判\nPOST   /api/analyze/text         # Web 完整检测")
bullet("受控媒体：GET /api/media/thumbnail/{filename}、GET /api/media/original/{filename}。")
bullet("已有数据不改，接口读取历史文本时脱敏。")

# 13
doc.add_heading("十三、性能与稳定性", level=1)
bullet("托盘检测必须快速返回，不能等 DeepSeek 一分钟；初步检测几十毫秒到 1 秒内完成，随后后台 AI 复审。")
bullet("托盘请求优先，Web 可以延后。")
bullet("关键词规则、案例库、缓存优先；托盘轮询 1.5 秒，前端轮询 2.5 秒。")
bullet("失败不能静默吞异常导致“一直检测但不显示”；循环异常至少写日志。")
bullet("运行中不能反复弹 PowerShell/控制台；不能残留测试进程、旧托盘进程、旧后端进程。")
bullet("不能出现重复托盘图标；任务管理器强杀无法执行清理逻辑，正常退出必须完整清理。")

# 14
doc.add_heading("十四、验收标准", level=1)
for i, text in enumerate([
    "桌面双击可启动，UAC 授权一次。",
    "程序已运行时再次双击只打开 Web 页面。",
    "托盘只有一个图标。",
    "微信、QQ 自动监测，无需手动检测。",
    "QQ 对方 ID 正确显示为聊天头部 ID，例如 ~。",
    "当前用户昵称不会被当成对方 ID。",
    "只检测左侧对方消息，右侧自己的消息排除。",
    "数据库/本地预判先出结果，AI 再复审。",
    "程序端先告警，Web 端 20 秒内更新。",
    "≥70 白色浮层 + 通知；≥90 红色常驻。",
    "对话用户按 ID 隔离，支持选择、载入、删除、1 天过期。",
    "退出程序后托盘、后端、浮层全部退出。",
    "OCR、托盘、启动器不弹 PowerShell 窗口。",
    "修改完成后提交并推送 GitHub。",
], 1):
    p = doc.add_paragraph(style="List Number")
    p.add_run(text)
    for r in p.runs:
        r.font.name = "Microsoft YaHei"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        r.font.size = Pt(10.5)

# 15
doc.add_heading("十五、当前仍需继续完善的事项", level=1)
for text in [
    "托盘快速结果尚未持久化到完整历史。",
    "可选的后台 AI 精修复核链路仍需继续稳定。",
    "DeepSeek/Qwen 的同步 HTTP 尚未整体改为 httpx.AsyncClient。",
    "同步 DB/PIL 调用尚未全部包 asyncio.to_thread。",
    "数据库连接池尚未完成。",
    "模糊匹配的 n-gram 候选尚未补齐。",
    "托盘 UIA 事件回调尚未实现，目前仍是轮询兜底。",
    "原文标记重叠时尚未做多层叠加样式。",
    "非本机免费 AI provider 尚未补齐。",
    "对话历史目前只保留每个 ID 的最新快照，没有完整消息时间线。",
]:
    bullet(text)

doc.save(OUT)
print(OUT)
