# AI 日报 · 本地热点看板

一个每天自动抓取「剪辑后期 + 导演影视化 + 分镜视觉 + AI 创作技巧 + 教程学习 + 开源工具 + AI 短剧动态 + 风向洞察」的小页面，
生成后就是本地一个 `index.html`，双击即可看，不需要服务器、不需要账号、不装任何第三方库。

定位是**手艺和学习为主、资讯为辅**：八个栏目里六个是技巧/学习/方法论，行业新闻只占最后一个「风向 · 洞察」，
而且必须带观点或判断才进得来（纯发布、纯财报类的不收）。

## 随时打开的链接

公网地址（换网络也能开，比如在家、在外面用流量）：

```
https://xxxxx.trycloudflare.com/     ← 实际地址见页面最底部「公网地址」，或 data/tunnel-url.txt
```

由 Cloudflare 快速隧道（`tunnel.py` + `tools/cloudflared.exe`）提供，不需要注册账号。
隧道重启（例如电脑重启）后地址会变，脚本会自动把新地址写进 `data/tunnel-url.txt`，
页面底部的「公网地址」下次刷新也会跟着更新。

本机（桌面也有一个「AI日报」快捷方式）：

```
http://127.0.0.1:8765/
```

同一个 Wi-Fi 下的手机、平板、其他电脑：

```
http://WIN-ASKQJG0OQLE:8765/      也可以用 http://192.168.1.59:8765/
```

这个链接由 `serve.py` 提供，已经注册成登录自启的计划任务 `AI-Daily-Server`，
开机登录后自动在后台跑，不用管；页面每 30 分钟自动刷新一次，每天 09:00 抓完就是当天内容。
公网隧道同样是登录自启（任务 `AI-Daily-Tunnel`）。

注意：公网地址没有密码，拿到链接的人都能看（只暴露看板页面本身，`data/` 目录下的文件不通过 HTTP 提供）。
想固定地址或加访问控制，见文末「公网访问的进阶方案」。

```powershell
schtasks /Run    /TN "AI-Daily-Server"     # 现在启动（已经启动了）
schtasks /End    /TN "AI-Daily-Server"     # 停止
schtasks /Delete /TN "AI-Daily-Server" /F  # 不再自启
.\start-server.cmd                         # 手动前台启动，能看到日志
.\stop-server.cmd                          # 手动停止
schtasks /Run    /TN "AI-Daily-Tunnel"     # 启动公网隧道
.\start-tunnel.cmd / .\stop-tunnel.cmd     # 手动开关隧道
```

局域网链接只在本机开机、且在同一个网络时有效；如果路由器给这台机器换了 IP，
用主机名那条链接、或重新查一次 IP（`ipconfig`）即可。Windows 防火墙已经放行 8765 端口，
不需要的话可以删掉这条规则：`netsh advfirewall firewall delete rule name="AI-Daily Dashboard 8765"`。

## 公网访问的进阶方案

现在的快速隧道足够用，但地址会变、也没有密码。有两种更稳的做法：

1. **固定域名（Cloudflare 命名隧道）**：需要一个自己的域名托管到 Cloudflare。
   执行一次 `cloudflared tunnel login` 在浏览器里授权，然后
   `cloudflared tunnel create ai-daily` → 配置 DNS → 用 `cloudflared tunnel run ai-daily` 代替快速隧道，
   就能得到像 `https://daily.你的域名/` 这样的固定地址。
2. **只给自己用（Tailscale / ZeroTier 一类的组网）**：公司电脑和家里设备各装一次、登录同一个账号，
   之后在家里用组网分配的固定 IP/域名访问 `http://<组网IP>:8765/`，全程不暴露到公网，比公网 URL 安全。

两条路都需要你本人登录账号；需要的话我可以按你选的方案把命令和配置直接配好（登录那一步得你来点）。

## 怎么用

| 想干什么 | 怎么做 |
| --- | --- |
| 直接用链接看 | 打开 `http://127.0.0.1:8765/` 或桌面「AI日报」快捷方式 |
| 立刻抓一次 | 双击 `run.cmd`，或命令行 `py collect.py` |
| 抓完自动打开页面 | `py collect.py --open` |
| 不联网只重画页面 | `py collect.py --render` |
| 看页面 | 双击 `index.html` |
| 看上次抓取日志 | `data\last-run.log`、`data\run-history.log` |

页面支持：分类标签页、关键词搜索、「仅今日新增」、「只看收藏」（收藏存在浏览器 localStorage）、
点击条目自动标记已读、Skill 卡片一键复制调用命令。

### 中文阅读

- `中文可读` 按钮：只留中文原文或已经有中文导读的条目。
- `data/zh.json`：给英文条目的「一句话中文导读」，页面上显示成蓝色小条，说明这篇能学到什么。
  每天 09:20 的自动化任务会保留旧内容、给新条目补最多 30 条导读。
- 中文源：人人都是产品经理、数英、掘金、开源中国、界面新闻、少数派、InfoQ 中文、量子位、雷锋网、钛媒体、IT之家。
  中文的剪辑/导演/分镜垂直内容大多在 B 站、知乎、公众号里，这些站点目前抓不到（RSSHub 公共镜像也不通），
  所以这类内容主要靠英文源 + 中文导读补足。

## 目录结构

```
ai-daily\
  collect.py        采集器（Python 标准库，无第三方依赖）
  serve.py          本地看板服务（链接就是它提供的）
  start-server.cmd  启动看板服务
  stop-server.cmd   停止看板服务
  config.json       信息源、关键词、GitHub 查询词，想加源就改这里
  template.html     页面模板（样式和交互都在这）
  index.html        生成出来的看板（每次抓取覆盖）
  run.cmd           给计划任务/双击用的入口
  data\
    history.json    全量去重后的条目库（页面数据来源）
    latest.json     最近一次抓取结果的快照
    digest.json     今日精选摘要（可选，存在时优先展示）
    zh.json         非中文条目的中文导读，key 是条目 id
    archive\        按天归档的条目库
```

## 信息源

剪辑 / 后期：Medium 标签源（剪辑、剪辑技巧、后期、调色、视频制作、动态设计）、ProVideo Coalition、Frame.io Insider
导演 / 影视化：Medium 标签源（电影制作、摄影、编剧、影视制作）、Film Daft、Vashi Visuals、Film Courage、Filmmaker Magazine、Videomaker
分镜 / 视觉：Medium 标签源（分镜、故事板、概念设计、视觉开发）
AI 创作技巧：Medium 标签源（提示词、生成式 AI、AI 视频、AI 绘画）
教程 / 学习：Towards Data Science、KDnuggets、ML Mastery、DEV 教程、freeCodeCamp、Hugging Face、Simon Willison、Sebastian Raschka、One Useful Thing
中文干货：人人都是产品经理、数英 DIGITALING、少数派、InfoQ 中文、量子位、雷锋网
风向 / 洞察：Platformer、Stratechery、Interconnected、Latent Space、MIT Tech Review、TechCrunch AI
搜索补充：Hacker News 关键词搜索（AI 视频、提示词、Agent 工作流、Codex Skill）、Google 新闻英文检索（AI trends、prompt engineering、video editing tips、filmmaking、storyboard，均限定 14–30 天内）
开源榜单：GitHub Trending（AI/视频相关过滤）、GitHub 搜索（text-to-video、ai-video、codex skill、codex-skills）
本地 Skill：`~/.codex/skills` 与插件缓存里的所有 SKILL.md 自动扫描收录

已知不可用（被反爬拦截，暂时没接）：机器之心、36氪 RSS、Reddit、B 站、YouTube。

来源有四道闸门，避免堆器材、软文和旧闻：
`CRAFT_GATE`（标题/摘要必须真的谈到剪辑、后期、镜头、分镜等手艺话）、
`GEAR_NOISE`（发布会、器材评测直接丢）、
`PROMO_NOISE`（服务商推广稿、影评、榜单直接丢）、
`TREND_GATE`（风向栏目必须带分析/观点词，纯新闻不入榜）、
`NEWS_DOMAIN_WHITELIST`（Google 新闻只收白名单媒体，挡掉 SEO 站），
再加上 `TITLE_JUNK` 全源过滤盗版/推广标题。

## 分类规则

每条内容按标题+摘要命中关键词后归入：
`AI 创作技巧` / `剪辑 · 后期` / `导演 · 影视化` / `分镜 · 视觉` / `教程 · 学习` / `开源 · 工具` / `AI 短剧动态` / `风向 · 洞察`。
分类优先级是：分镜 → 短剧视频 → 剪辑 → 导演 → AI 创作技巧 → 教程学习 → 开源工具 → 风向；
垂直源（带 `default_category` 的源）在算不出更贴切分类时落到自己那个栏目。
泛科技源（IT之家、爱范儿等）只放行「标题里就带 AI 信号」的内容，避免手机数码新闻刷屏；
同一来源在单个分类里最多出现 10 条。

打分 = 来源权重 + 关键词命中数 + 时效衰减 + 仓库星标，
`今日精选` 会按类别配额挑选，优先剪辑、导演、AI 创作技巧、教程学习，风向和工具各留一条。

每个栏目的容量上限写在 `config.json` 的 `options.category_caps` 里（比如 `trend: 12`、`drama: 16`），
想彻底不看某类内容，把对应上限改成 0 即可。

改了 `config.json` 的关键词不用清库：每次运行都会用最新规则重算近 30 天的分类、标签和得分，
并且顺手把不再符合闸门的条目（比如只剩器材评测的）从库里清掉。

## 每天自动抓

已注册 Windows 计划任务 `AI-Daily-Collect`，每天 09:00 静默跑一次 `run.cmd`，
结果写进 `data\` 并覆盖 `index.html`，打开页面就是当天内容。

改时间或删任务：

```powershell
schtasks /Change /TN "AI-Daily-Collect" /ST 08:30
schtasks /Run    /TN "AI-Daily-Collect"      # 立即跑一次
schtasks /Delete /TN "AI-Daily-Collect" /F   # 不再自动抓
```

## 想加自己的源

编辑 `config.json` 的 `feeds`，加一条：

```json
{
  "id": "my_source", "name": "我的源",
  "url": "https://example.com/feed",
  "lang": "zh", "weight": 1.0, "ai_only": false,
  "max_items": 10, "recent_days": 14
}
```

`ai_only: true` 表示整站都是 AI 内容（不做标题过滤）；
否则只在标题命中 AI/短剧关键词时才收录。关键词表在同一个文件的 `keywords` 里，改完直接重跑。

## 今日精选摘要

`data/digest.json` 存在且是当天时，页面顶部就展示它；否则用脚本按类别配额的自动排序结果。
文件格式：

```json
{
  "date": "2026-09-16",
  "summary": "一句话概括今天…",
  "picks": [
    { "title": "标题", "url": "https://…", "why": "为什么值得看" }
  ]
}
```
