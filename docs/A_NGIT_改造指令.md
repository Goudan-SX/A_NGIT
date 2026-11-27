# A_NGIT 改造指令

目标：按既有需求改造现仓库。每条给出「改什么 + 怎么改」，标注 `[推荐]` 的为建议选项。所有路径相对 `A_NGIT/`。

---

## 0. 需求锚点（改造必须满足）

1. 微信/QQ 等聊天页面风险检测；用户明确同意、不绕权限、不收无关数据。
2. Web 前端只展示，后端完成全部运算，前端实时呈现。
3. 无悬浮窗；后台程序运行；不干扰用户、不损设备安全。
4. 仅用户主动启动且使用社交软件时启用；其余时间低占用。
5. 风险 ≥70% 时屏幕右下角非强制提示，不打断正常使用。
6. 原文可对照展示 + 敏感表达高亮 + 汇总意图（原文片段/依据/等级/说明）。
7. 区分「客观命中」与「主观推断」，不把推断写成事实。

---

## 1. P0 阻断项（先改，否则合规不过）

| # | 文件位置 | 改什么 | 方案 A `[推荐]` | 方案 B |
|---|---|---|---|---|
| 1 | `backend/app/config.py:38` | `HOST=0.0.0.0` | 改为 `127.0.0.1` | 加环境变量 `APP_BIND_LOCAL=true` 默认本地，答辩需局域网时手动开 |
| 2 | `backend/app/main.py:99-105` | `allow_origins=["*"]` | 改为白名单 `["http://127.0.0.1:8000"]` | 删除 `CORSMiddleware`（同源部署无需跨域） |
| 3 | `backend/app/main.py` 全部 `/api/*` | 无鉴权 | 加 `Depends(verify_token)` 校验本地令牌，覆盖 history/logs/reports/analyze | 仅对 history/logs/reports 三类加，analyze 保持开放便于演示 |
| 4 | `backend/app/main.py:651,961` | `or content_type.startswith("image/")` | 删除该分支，只留扩展名白名单 | 保留但追加 Pillow `verify()` 魔数校验 |
| 5 | `backend/app/main.py:1238` | `/uploads` 静态挂载 | 改为受控下载端点，强制 `Content-Disposition: attachment` + `nosniff` | 保留挂载，加中间件给上传目录响应头打附件标记 |
| 6 | `backend/app/analyzer.py:477-482` | PII 偏移基于规范化文本 | 改为在原始文本上计算并返回 `raw_start/raw_end` | 打码在规范化文本上完成后整体替换原文本 |
| 7 | `backend/app/case_matcher.py:217-231` | `_sanitize_for_store` 用错偏移 | 改用第 6 步的原文偏移 | 直接存脱敏后的规范化文本，不存原文 |
| 8 | `backend/app/repository.py:155` | `get_analysis` 返回 `input_text` 明文 | 返回脱敏值 | 仅管理员令牌可见原文 |
| 9 | `backend/app/content_store.py:36` | `raw_text` 明文入库 | 存脱敏文本 | 设 `RETENTION_HOURS`，定期清理 |
| 10 | `backend/requirements.txt` | 缺 pandas | 追加 `pandas==<锁定版本>` | 删除 `backend/ml/` 交易风控模块（若答辩不用） |

---

## 2. 需求 3：去悬浮窗，改后台程序

| 方案 | 做法 | 取舍 |
|---|---|---|
| A `[推荐]` | 删除 `extension/`；新建 Python 托盘服务（pystray + uiautomation），复用 `/api/analyze/text`，托盘图标可见、可暂停/退出 | 完全符合需求；UIA 仅 Windows |
| B | 保留 `extension/` 作演示分支，另建托盘服务；README 标注两种形态二选一 | 双份维护；答辩演示灵活 |
| C | 保留悬浮球，改为默认关闭 + 用户手动开启 | 不满足「无悬浮窗」，不推荐 |

配套动作（三方案共用）：
- 删除 `extension/content.js:28-32,350-356` 的全站注入与 `setInterval(tick, 3500)`。
- `manifest.json:12,23` 的 `<all_urls>` 收窄为按需域名；删除未使用的 `storage` 权限。
- 删除 `content.js:270` 的 `fetch(src,{credentials:'include'})` 与 `133-137` 的整页文本兜底。

---

## 3. 需求 2+4：合规门控与低占用

按下列顺序在托盘服务中实现，缺一不可：

1. 默认关闭；首次启动弹授权说明；用户勾选要监测的窗口（微信/QQ）。
2. 前台焦点门控：仅当被勾选窗口处于前台时激活感知；否则挂起线程、释放 UIA 订阅。
3. 采集最小化：只读屏幕可见新增文本，hash 去重；不读历史、不读密码框/输入框/Cookie、不回溯。
4. 文本变化监听优先 UIA 事件回调；不支持时 500ms 轮询兜底；禁止 3.5s 全站常驻轮询。
5. 控件读不到时截图 + OCR 兜底，限定可见区域与频率，不落盘。
6. 结果只写本地队列（内存/SQLite），原始文本不出本机；调用外部大模型前脱敏并二次授权。
7. 状态可见：托盘「● 监测中」；可暂停/退出；不开机自启、不隐藏图标、不静默运行。

低占用策略：事件驱动优先、前台门控休眠、增量去重、规则先行缓存、OCR 限频、批量渲染。

---

## 4. 需求 5：70% 非强制告警

| 方案 | 做法 | 取舍 |
|---|---|---|
| A `[推荐]` | Windows 系统通知（系统托盘 toast），右下角、数秒自动淡出、不抢焦点、点击展开详情 | 最符合「非强制、不打断」；依赖系统通知权限 |
| B | tkinter 无焦点小窗，置右下、`topmost` 谨慎使用、不夺焦点、带「忽略」按钮 | 可控性强；实现复杂、跨平台差 |
| C | 仅 Web 面板角标变色 | 最保守；不满足「屏幕右下角」 |

通用约束：判定放后端服务层（前端不参与）；同一会话同类话术 N 分钟内不重复告警。

---

## 5. 需求 6+7：文本分析展示

后端（`backend/app/analyzer.py`、`main.py`）：
1. `signals` 每项增加 `start`/`end`/`source`（`rule|ai`）；AI 推断另加 `confidence` 与 `disclaimer="推断，非事实"`。
2. 新增返回两组结论：`hits[]`（客观命中）、`inferences[]`（主观推断），从数据结构层面隔离。
3. 偏移统一为「原始文本偏移」，与第 1 节第 6 项共用同一套映射。

前端（`HTML+CSS/html/index.html`、`js/app.js`）：
4. 新增原文展示区（只读 `pre` 或 `textarea`），完整保留待分析原文，可对照。
5. 新增 `renderHits()` / `renderInferences()`：按偏移切分区间生成高亮节点；区间重叠时叠加样式。
6. 客观区实线色块 + 确定性措辞；主观区虚线紫色 + 免责声明 + 置信度进度条。两区视觉语言必须不同。
7. 加双向定位（点标记滚卡片、点卡片滚原文）、类型筛选、「隐藏标记看原文」开关。
8. 删除 `app.js:336-375 renderFallback()` 的硬编码 86 分与伪造证据，改为明确错误态。
9. `api.js` 给 fetch 加 AbortController 超时（建议 30s），解除按钮永久禁用风险。

前端严禁新增任何关键词匹配、评分、推断逻辑。

---

## 6. P1 架构治理（展示改造后执行）

| # | 文件 | 动作 `[推荐]` | 备选 |
|---|---|---|---|
| 1 | `analyzer.py` / `guardian.py` / `main.py:875-929` | 统一为一套评分真源；`guardian.compute` 只产出 components，不再覆盖 `risk_score` | 保留三套但用配置指定唯一生效 |
| 2 | `main.py:998-1011` | 删除 guardian 降分回滚补丁 | 保留并加注释说明 |
| 3 | `backend/README.md`（仓库根 README 第七节） | 删除重复段落，统一评分维度表述 | 仅标注「历史版本」 |
| 4 | `case_matcher.py:169-214` | 精确 hash 走索引；模糊匹配加长度过滤 + n-gram 候选 | 引入全文索引或向量库 |
| 5 | `case_matcher.py:234-273` | 自动收录加阈值、上限、TTL | 关闭自动收录 |
| 6 | `deepseek.py` / `qwen.py` | 同步 `urllib` 改 `httpx.AsyncClient`，加超时/重试/退避 | 保留 urllib 但全部包 `to_thread` |
| 7 | `main.py:647-872` | 所有 DB/文件/PIL 同步调用包 `asyncio.to_thread` | 改为线程池任务队列 |
| 8 | `db.py:90-124` | 引入连接池（QueuePool 或 SQLAlchemy） | 保持现状，仅降连接频率 |
| 9 | `qwen.py:73-93,218-248` | 删除重复函数，统一用 `ai_common` | 保留但标记 deprecated |
| 10 | `transaction_risk.py:166,192` | 用 `pipeline.classes_` 校验正类列；启用 `threshold` | 维持现状 |

---

## 7. 执行顺序

1. 第 1 节 P0 全部（合规底线）
2. 第 6 节 1、2、3（评分统一，避免后续返工）
3. 第 5 节 后端 1-3 + 前端 4-9（展示契约）
4. 第 2、3、4 节（后台程序、门控、告警）
5. 第 6 节剩余项（性能与清理）

---

## 8. 待你决策

1. 悬浮窗：整体删除（方案 A）还是保留演示分支（方案 B）。
2. 历史明文数据：脱敏改写还是清空重建。
3. 外部大模型：实时路径是否允许脱敏后调用；不允许则改用本地轻量模型，准确率口径需相应调整。
