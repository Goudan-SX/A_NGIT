# Guardian-AI 浏览器悬浮窗 v1.3.0

## 安装

1. 启动 Guardian-AI 后端：python backend/run.py，访问 http://127.0.0.1:8000/
2. Chrome / Edge 打开扩展管理页：
   - Chrome: chrome://extensions
   - Edge: edge://extensions
3. 打开“开发者模式”，选择“加载已解压的扩展程序”，选择本目录 extension。
4. 打开聊天网页，右上角会出现 Guardian-AI 悬浮球。
5. 修改扩展代码后，到 edge://extensions 点扩展卡片上的“重新加载”。

## 显示规则

- 未进入聊天页面：黑圈白底，中心大写 G。
- 进入聊天页面但还没有消息：保持 G。
- 检测到消息后才开始分析：
  - 风险 < 30：绿色环绕
  - 30–49：黄色
  - 50–69：橙色偏粉
  - ≥70：红色闪烁
- 悬浮窗显示当前风险百分比，单击打开 Guardian-AI 程序网页。

## 邮箱页面

已适配 QQ 邮箱、163/126、Gmail、Outlook 等页面，优先读取邮件正文；QQ 邮箱正文在 iframe 中时会尝试读取同源 iframe。

## 聊天图片检测

扩展会读取聊天消息中的图片，调用本地 `/api/analyze` 做多模态分析；跨域图片读取失败时自动退回文本检测。

## 隐私

- 只读取聊天页面当前可见的消息文本。
- 不读取密码框、输入框、Cookie、账号信息。
- 检测请求使用 save=false，不写入 SQL Server。
- 扩展调用本地 127.0.0.1:8000，不上传其他页面内容。

## 说明

不同聊天网站的 DOM 结构不同，content.js 使用通用消息选择器；微信网页版、常见 IM 页面优先。若某个站点识别不到消息，可在 collectMessages 的选择器列表中补充该站点的消息节点。