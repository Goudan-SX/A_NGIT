# A_NGIT · 反诈卫士

> 赛题 11：反诈卫士——面向青年的 AI 诈骗识别与个人信息保护助手  
> 细分方向：网络安全

本项目是一个面向青年用户的 AI 反诈网页原型：对聊天文本、聊天图片进行多模态风险检测，
实时给出诈骗风险评分，并展示高危词汇、高风险图片，后续将接入举报与反诈科普能力。

当前版本为纯静态页面（HTML + CSS），暂未加入 JavaScript 交互逻辑。

## 技术栈

- HTML5：语义化页面结构
- CSS3：独立样式表、设计变量、Grid / Flex 布局、响应式适配
- 开发工具：Visual Studio Code
- 推荐插件：Live Server、Prettier、HTML CSS Support、CSS Peek、Auto Rename Tag、
  Color Highlight、Error Lens（仓库已提供 `.vscode/settings.json`）

## 目录结构

```text
A_NGIT/
├── HTML+CSS/
│   ├── html/
│   │   └── index.html        # 页面结构
│   └── css/
│       └── style.css         # 页面样式（独立 CSS 文件）
├── .vscode/
│   └── settings.json         # 团队统一的编辑器配置
├── .editorconfig             # 代码风格约定
├── .gitignore
└── README.md
```

## 本地预览

1. 使用 VS Code 打开仓库根目录 `A_NGIT`。
2. 安装 Live Server 插件后，右键 `HTML+CSS/html/index.html`，选择 **Open with Live Server**。
3. 浏览器访问 `http://127.0.0.1:5500/HTML+CSS/html/index.html`。

也可以直接双击 `HTML+CSS/html/index.html` 在浏览器中打开。

## 页面说明

- 顶部导航：个人用户 / 历史记录 / 日志。
- 左侧输入区：
  - 聊天文本输入 / 接收区，后续用于实时接收并展示聊天文字；
  - 图片区域，用于展示聊天截图、二维码、转账凭证等图片内容。
- 右侧分析区：
  - 综合诈骗风险百分比（当前为静态示例 87%）；
  - 百分比下方展示高危词汇与高风险图片；
  - 底部预留大块「后续操作区」，用于后续接入举报、科普、证据导出等功能。

## 代码规范

- 使用 2 个空格缩进，UTF-8 编码，LF 换行；
- CSS 使用 BEM 风格命名（如 `.risk-media__item`），按模块分节并添加注释；
- 颜色、圆角、字体等统一收敛到 `:root` 设计变量；
- 样式全部写在独立 CSS 文件中，HTML 中不写行内样式；
- 保存时由 Prettier 自动格式化，建议提交前检查页面在 1440px 与 390px 宽度下的表现。

## 团队协作

- 仓库默认分支：`main`；
- 每位队友使用独立分支开发，例如 `feature/analysis-panel`；
- 提交信息建议使用 `feat: ` / `fix: ` / `style: ` / `docs: ` 前缀；
- 合并前发起 Pull Request，至少 1 人 Review 后合入 `main`；
- 如需队友直接推送代码，请在 GitHub 仓库 **Settings → Collaborators** 中邀请对应账号。

## 后续计划

- [ ] 接入 JavaScript：文本实时输入、图片上传预览；
- [ ] 风险评分模型与检测流程可视化；
- [ ] 接入高危词汇库、图片 OCR 结果；
- [ ] 一键举报、反诈科普推送、证据导出；
- [ ] 对接比赛演示所需的 8—10 页 PPT 与讲解脚本。
