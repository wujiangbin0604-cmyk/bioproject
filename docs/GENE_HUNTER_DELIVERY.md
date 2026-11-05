# Gene Hunter 交付说明

交付日期：2026-11-04。路由：`/games/gene-hunter`。入口：左侧「学习与游戏 → 基因猎手：寻找关键特征」，全局搜索也能找到游戏。

## 文件清单

以下路径均相对项目根目录。

| 状态 | 文件 | 职责 |
| --- | --- | --- |
| 修改 | `frontend/src/App.tsx` | 独立懒加载路由 |
| 修改 | `frontend/src/layouts/AppShell.tsx` | 桌面/移动导航、选中状态与全局搜索 |
| 修改 | `frontend/src/components/ui/Icon.tsx` | 游戏、奖杯、计时器、连击、播放、礼物图标 |
| 新增 | `frontend/src/mock/geneHunterLevels.ts` | 五关确定性合成数据与异步 provider 示例 |
| 新增 | `frontend/src/games/gene-hunter/GeneHunterPage.tsx` | 页面组装、完整挑战总结、教学弹窗 |
| 新增 | `frontend/src/games/gene-hunter/GameHeader.tsx` | Hero 与现有 DNA 装饰复用 |
| 新增 | `frontend/src/games/gene-hunter/GameStatsBar.tsx` | 等级、关卡、计时、分数、目标 |
| 新增 | `frontend/src/games/gene-hunter/GeneHeatmapBoard.tsx` | CSS Grid 热图与关卡操作 |
| 新增 | `frontend/src/games/gene-hunter/GeneRow.tsx` | 行选择、色阶、单元格 tooltip、固定基因名 |
| 新增 | `frontend/src/games/gene-hunter/ScorePopup.tsx` | 点击位置浮分与粒子 |
| 新增 | `frontend/src/games/gene-hunter/ComboBadge.tsx` | 连击与当前倍率 |
| 新增 | `frontend/src/games/gene-hunter/MissionCard.tsx` | 本关任务与命中进度 |
| 新增 | `frontend/src/games/gene-hunter/RoundResultCard.tsx` | 即时反馈、结算星级、Top5 命中/遗漏对比 |
| 新增 | `frontend/src/games/gene-hunter/LeaderboardCard.tsx` | 显式标注的示例周榜、个人完整挑战最佳 |
| 新增 | `frontend/src/games/gene-hunter/GameGuideSection.tsx` | 四步玩法教学 |
| 新增 | `frontend/src/games/gene-hunter/GrowthCard.tsx` | 星数、Lv1–Lv4 与解锁进度 |
| 新增 | `frontend/src/games/gene-hunter/useGeneHunterGame.ts` | React 状态、计时与本地进度存储 |
| 新增 | `frontend/src/games/gene-hunter/gameEngine.ts` | 可独立测试的计分与关卡状态机 |
| 新增 | `frontend/src/games/gene-hunter/types.ts` | 类型及未来数据 provider 接口 |
| 新增 | `frontend/src/games/gene-hunter/gene-hunter.less` | 隔离样式、断点、动画、reduced motion |
| 新增 | `frontend/tests/gene-hunter.test.mjs` | 12 项游戏逻辑单元测试 |
| 新增 | `frontend/tests/gene_hunter_browser.py` | 实际浏览器流程、计时、导航、移动端验收 |
| 新增 | `docs/GENE_HUNTER_DELIVERY.md` | 本文件 |
| 新增 | `reports/gene-hunter/browser-acceptance.json` | 浏览器验收结果 |
| 新增 | `reports/gene-hunter/*.png` | 桌面初始/游戏/结算/通关、平板及手机截图 |

不增加 npm 依赖。使用现有 React、Arco、路由、图标和 DNA 组件；热图与动效分别使用 CSS Grid 和 CSS 动画。

## 玩法与数据

共五关，每关 12 个基因、两组各 8 个样本、5 个高价值特征。限时依次为 60 / 55 / 50 / 45 / 40 秒。后续关卡加入反向表达信号与组内波动，提示玩家同时观察组间差异和组内一致性。

进入关卡后可先观察，点击开始才计时。点击任意基因名或色块选择整行。时间结束自动结算，也可以主动提交。本关排名仅在结算后展示。下一关会清空本关选择、连击、反馈与分数，保留累计得分。第五关结束展示总分、命中数和每关星级，支持重新挑战。

全部表达值、类别和判别分数均为合成教学示例；真实基因符号不表示相应患者观察或生物学结论。预设判别分数不是实测 AUC，也不是游戏总分。排行榜为静态示例，页面已明确标注。

## 热图与计分

表达值在 -2 到 +2 之间，浅蓝 → 近白 → 淡紫。悬浮格子可查看基因、样本编号和标准化表达值。整行可聚焦并用 Enter/Space 选择；移动端热图独立横向滚动，基因名固定在左侧。

| 选择 | 基础得分 | 连击行为 |
| --- | ---: | --- |
| 教学判别分数 ≥ 0.80 | 800 | 高价值连击 +1 |
| 0.50 ≤ 分数 < 0.80 | 300 | 连击重置为 0 |
| 分数 < 0.50 | 0 | 连击重置为 0 |
| 重复选择 | 0 | 状态保持 |

第 2 / 3 / 4 次及以上连续高价值命中，分别采用 ×1.2 / ×1.5 / ×2.0。五次高价值连续命中依次为 800、960、1200、1600、1600，总计 6160 分。

每关命中 0 / 1–2 / 3–4 / 5 个高价值基因获得 0 / 1 / 2 / 3 星。每关只保存最佳星数，共 15 星，重复挑战不会叠加刷星。总最佳星数达到 3 / 9 / 15 时升至 Lv2 / Lv3 / Lv4。

个人最佳分数只收录完成全部五关并查看挑战总结的完整挑战。数据保存在当前浏览器的 `genescope-gene-hunter-v1`；存储不可用时仍可在内存中游戏。离开页面不保存进行中的回合。

所有计分操作都通过纯状态机检查当前阶段、基因是否存在、是否重复、是否已到绝对截止时间。后台标签页恢复后会依据截止时间立即结算，不依赖定时器回调次数累减。即使 UI 尚未刷新，截止时间之后的点击也不能得分。

## 动效

- 行悬浮、边框、选中高亮：180ms。
- 关卡切入、结果展开：280ms。
- Combo 回弹：300ms。
- 得分浮层及 8 枚轻量粒子：350ms；浮层从选择位置上浮。
- 最后 10 秒采用柔和计时描边脉冲；社区卡片有轻微悬浮反馈。
- 同时遵循系统 `prefers-reduced-motion` 和现有全站动效设置。减少动态效果时关闭粒子、浮分和动画，保留静态高亮与文字反馈。
- 热图行采用 `memo`，选择回调保持稳定，计时刷新不会重建所有格子。

## 验证

在 `frontend` 下运行：

```powershell
npm run typecheck
npm test
npm run build
npm run preview -- --port 5179
python -u tests/gene_hunter_browser.py --url http://127.0.0.1:5179
```

浏览器脚本复用项目已有 `backend/.vendor` 中的 Python Playwright，默认使用本机 Edge；可通过 `--browser` 指定其他 Chromium 可执行文件。`--inspect` 可用于首屏检查。

- TypeScript 类型检查通过。
- 前端生产构建通过，游戏 JS 独立懒加载，压缩前约 26.2 kB / gzip 9.4 kB。
- 全部 22 项单元测试通过，其中新增游戏测试 12 项。
- 实际浏览器验收覆盖直接路由与刷新、初始禁用、tooltip、点击高亮、重复点击、高/中/低计分、Combo、绝对时间到期、结算后禁用、五关切换、总结、重玩、刷新后的个人记录、新手弹窗、导航与搜索。
- 桌面 1440、平板 1024、手机 390 宽度检查；键盘选择、减少动态效果、移动端固定基因名与横向滚动检查。
- 验收中主动令平台 API 返回 503，确认游戏无需后端计算仍可完成。浏览器报告中的页面脚本错误为 0。
- 构建存在既有主包/ECharts 大于 500 kB 的体积提示，不影响构建；游戏未引入 ECharts 或新增动画依赖。

## 后续扩展

1. 通过 `GeneHunterLevelProvider.loadLevels(signal)` 接入服务端数据。后端应提供数据集版本、排名方法、来源与许可，明确训练集内特征选择，替换合成数据标注。
2. 将示例周榜替换为服务端排行榜，并将计分验证迁移到服务端；当前浏览器分数适用于本地学习，不能作为可信竞技结果。
3. 增加噪声/样本规模/基因相关性关卡，以及不同特征排名方法的对比教学。
4. 增加可选音效与更详细的算法揭晓说明。
