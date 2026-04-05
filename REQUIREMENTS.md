# astrbot_plugin_douban_movie — 开发需求文档

## 一、项目概述

AstrBot 豆瓣电影推荐插件。用户绑定豆瓣账号后，插件自动同步其豆瓣片单，生成观影画像，并基于画像提供个性化电影推荐。

**数据源**：完全依赖豆瓣，不引入 TMDb 等第三方源。  
**存储策略**：明文 SQLite 存储，不做复杂加密，优先性能与可维护性。

---

## 二、核心功能模块

### 1. 用户绑定（豆瓣 Cookie 授权）

**指令**：`/movie bind`

- 用户通过私信或群聊发送该指令后，插件返回引导提示，要求用户提供豆瓣 `bid` Cookie（或登录态凭据）。
- 插件验证凭据有效性（访问豆瓣个人主页，HTTP 200 + 正常解析即视为有效）。
- 验证通过后，将 `astrbot_user_id ↔ 豆瓣 uid + cookie` 写入本地数据库。
- 一个 AstrBot 用户只能绑定一个豆瓣账号，重复绑定覆盖旧数据。

**指令**：`/movie unbind`

- 清除当前用户的绑定信息及本地缓存的片单数据。

**指令**：`/movie status`

- 查看当前绑定状态、上次同步时间、已同步影片数量。

### 2. 阅片数据同步

**指令**：`/movie sync`

- 使用已存储的 Cookie，爬取用户豆瓣「想看」「在看」「看过」三个片单。
- 每个条目至少保存：`豆瓣电影ID、标题、评分（用户打分）、标签/类型、收藏状态（wish/do/collect）、标记时间`。
- 同步策略：
  - 首次同步：全量拉取。
  - 后续同步：增量更新（只拉取上次同步之后新增的标记）。
  - 单次同步设置超时上限（建议 60s），超时则保存已获取部分并提示用户。
- 同步完成后输出摘要：「已同步 X 部影片（想看 A / 在看 B / 看过 C）」。

### 3. 用户画像生成

**指令**：`/movie profile`

- 基于已同步的「看过」片单，自动生成用户观影画像。
- 画像维度：
  - **类型偏好**：统计各类型（剧情/喜剧/科幻/恐怖等）的数量与平均评分，取 Top 5。
  - **地区偏好**：统计制片国家/地区的分布，取 Top 3。
  - **年代偏好**：统计观影集中的年代区间（如 2010s、2020s）。
  - **评分习惯**：平均打分、打分分布（严厉型 / 宽容型 / 随机型）。
  - **观影量级**：总看过数量、本月/本年新增。
- 画像以文本格式输出，美观简洁，适合聊天窗口阅读。

### 4. 电影推荐

**指令**：`/movie recommend` 或 `/movie rec`

- 基于用户画像，从豆瓣「Top 250」或用户未看过的相关高分影片中筛选推荐。
- 推荐逻辑（按优先级）：
  1. 用户偏好类型中的高分影片（评分 ≥ 8.0）。
  2. 用户偏好地区/年代交叉匹配。
  3. 排除用户已标记「看过」或「不想看」的影片。
- 单次推荐 3~5 部，每部附带：标题、豆瓣评分、一句话推荐理由。
- 推荐理由基于画像数据生成，例如：「因为你喜欢科幻类且高分倾向明显，推荐……」

**指令**：`/movie rec <类型>`

- 支持按指定类型筛选推荐，如 `/movie rec 科幻`。

---

## 三、数据存储设计

使用 SQLite（文件路径：插件目录下 `data/douban_movie.db`）。

### 表结构

```sql
-- 用户绑定表
CREATE TABLE user_bind (
    astrbot_uid  TEXT PRIMARY KEY,
    douban_uid   TEXT NOT NULL,
    cookie       TEXT NOT NULL,
    bind_time    DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_sync    DATETIME
);

-- 片单缓存表
CREATE TABLE movie_collection (
    douban_movie_id  TEXT,
    astrbot_uid      TEXT,
    title            TEXT,
    user_rating      REAL,
    genres           TEXT,       -- 逗号分隔的类型标签
    regions          TEXT,       -- 逗号分隔的制片地区
    year             INTEGER,
    status           TEXT,       -- wish / do / collect
    marked_at        DATETIME,
    fetched_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (douban_movie_id, astrbot_uid)
);
```

---

## 四、技术约束与规范

1. **开发框架**：遵循 AstrBot 插件 Star 规范（`astrbot.api.star.Star` 基类），入口文件为 `main.py`。
2. **网络请求**：使用 `aiohttp` 或 `httpx`（异步），避免阻塞事件循环。必须携带用户 Cookie 伪装浏览器 UA。
3. **反爬处理**：请求间隔随机化（1~3s），遇到 403/429 自动退避重试，最多 3 次。
4. **错误处理**：所有指令必须有 try/except 兜底，异常时向用户返回友好提示（不暴露堆栈）。
5. **依赖管理**：第三方库写入 `requirements.txt`。
6. **日志**：使用 `astrbot.api.logger`，关键操作（绑定/同步/推荐）记录 INFO 级别日志。

---

## 五、文件结构（预期）

```
astrbot_plugin_douban_movie/
├── main.py                 # 插件入口，注册指令
├── metadata.yaml           # 插件元数据
├── requirements.txt        # 依赖
├── REQUIREMENTS.md         # 本文档
├── db/
│   └── database.py         # SQLite 封装（初始化、CRUD）
├── service/
│   ├── douban_client.py    # 豆瓣页面抓取与解析
│   ├── profile.py          # 画像生成逻辑
│   └── recommender.py      # 推荐筛选逻辑
└── data/                   # 运行时数据库文件（gitignore）
    └── douban_movie.db
```

---

## 六、开发优先级

| 阶段 | 功能 | 状态 |
|------|------|------|
| P0 | 用户绑定 / 解绑 / 状态查询 | 🔲 待开发 |
| P0 | 片单同步（全量） | 🔲 待开发 |
| P1 | 用户画像生成 | 🔲 待开发 |
| P1 | 电影推荐（基础版） | 🔲 待开发 |
| P2 | 增量同步优化 | 🔲 待开发 |
| P2 | 按类型筛选推荐 | 🔲 待开发 |

---

## 七、关键页面参考（开发时抓取 & 解析用）

> 以下 URL 供开发时参考页面结构、CSS 选择器、数据格式。实际请求时需携带用户 Cookie。

| 用途 | URL | 说明 |
|------|-----|------|
| 个人主页 | `https://www.douban.com/people/{douban_uid}/` | 获取用户昵称、观影数量概览 |
| 想看片单 | `https://movie.douban.com/people/{douban_uid}/wish` | 分页参数 `?start=0&sort=time&rating=all&filter=all&mode=grid` |
| 在看片单 | `https://movie.douban.com/people/{douban_uid}/do` | 同上分页参数 |
| 看过片单 | `https://movie.douban.com/people/{douban_uid}/collect` | 同上分页，每页 15 条（grid 模式）或 30 条（list 模式） |
| 电影详情 | `https://movie.douban.com/subject/{movie_id}/` | 标题、评分、类型、地区、年代、简介 |
| Top 250 | `https://movie.douban.com/top250` | 分页 `?start=0&filter=`，每页 25 条，共 10 页 |
| 豆瓣搜索 | `https://search.douban.com/movie/subject_search?search_text={keyword}` | 按关键词搜索电影，结果含 movie_id |
| 移动端详情 | `https://m.douban.com/movie/subject/{movie_id}/` | 页面更轻量，反爬压力小，备选方案 |

**备注**：
- 片单页每页 15 条（grid），可通过 `start` 参数翻页：`start=0, 15, 30, ...`
- 用户豆瓣 UID 在个人主页 URL 中可获取，Cookie 中 `dbcl2` 字段也包含 UID 信息
- 开发者自己的豆瓣主页（Est）：`https://www.douban.com/people/E-st2000/`，可作测试用例
