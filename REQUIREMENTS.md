# astrbot_plugin_douban_movie — 开发需求文档

## 一、项目概述

AstrBot 豆瓣电影推荐插件。用户绑定豆瓣主页ID后，插件自动同步其豆瓣片单，生成观影画像，并基于画像提供个性化电影推荐。

**数据源**：完全依赖豆瓣，不引入 TMDb 等第三方源。  
**存储策略**：明文 SQLite 存储，不做复杂加密，优先性能与可维护性。

---

## 二、核心功能模块

### 1. 用户绑定（豆瓣主页ID）

**指令**：`/movie bind <豆瓣主页ID>`

- 用户直接提供豆瓣主页ID（如 `E-st2000`），插件通过公开主页抓取数据，不需要 OAuth 或 Cookie 授权。
- 绑定流程：
  1. 用户发送 `/movie bind E-st2000`
  2. 插件访问该用户的豆瓣公开主页，验证主页可访问（HTTP 200 + 正常解析）。
  3. 提取用户昵称、观影数量等基础信息作为绑定确认。
  4. 将 `astrbot_user_id ↔ douban_uid` 写入本地数据库。
- 一个 AstrBot 用户只能绑定一个豆瓣账号，重复绑定覆盖旧数据。

**指令**：`/movie unbind`

- 清除当前用户的绑定信息及本地缓存的片单数据。

**指令**：`/movie status`

- 查看当前绑定状态、上次同步时间、已同步影片数量。

### 2. 阅片数据同步

**指令**：`/movie sync`

- 访问用户豆瓣公开主页的「想看」「在看」「看过」三个片单页面进行抓取。
- 每个条目至少保存：`豆瓣电影ID、标题、评分（用户打分）、标签/类型、收藏状态（wish/do/collect）、标记时间`。
- 同步策略：
  - 首次同步：全量拉取。
  - 后续同步：增量更新（只拉取上次同步之后新增的标记）。
  - 单次同步设置超时上限（可配置），超时则保存已获取部分并提示用户。
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
- 画像生成使用 LLM 辅助，调用管理员配置的模型（见配置项）。
- 画像以文本格式输出，美观简洁，适合聊天窗口阅读。

### 4. 电影推荐

**指令**：`/movie recommend` 或 `/movie rec`

- 基于用户画像，从豆瓣「Top 250」或用户未看过的高分影片中筛选推荐。
- 推荐逻辑（按优先级）：
  1. 用户偏好类型中的高分影片（评分 ≥ 可配置最低评分）。
  2. 用户偏好地区/年代交叉匹配。
  3. 排除用户已标记「看过」或「不想看」的影片。
- 单次推荐数量可配置，每部附带：标题、豆瓣评分、一句话推荐理由。
- 推荐理由使用 LLM 生成，调用管理员配置的模型（见配置项）。

**指令**：`/movie rec <类型>`

- 支持按指定类型筛选推荐，如 `/movie rec 科幻`。

---

## 三、配置项设计

以下配置项在 AstrBot 管理面板中展示，用户可直接修改：

| 配置项                           | 类型   | 默认值 | 说明                                             |
| -------------------------------- | ------ | ------ | ------------------------------------------------ |
| 片单同步超时时间                 | int    | 60     | 单次同步的最大耗时（秒）                         |
| 每次推荐返回的影片数量           | int    | 5      | 单次推荐返回几部影片                             |
| 推荐影片的最低豆瓣评分           | float  | 8.0    | 低于此评分的影片不参与推荐                       |
| 请求间隔下限（秒）               | float  | 1.0    | 爬取请求的最小间隔                               |
| 请求间隔上限（秒）               | float  | 3.0    | 爬取请求的最大间隔                               |
| 请求失败后的最大重试次数         | int    | 3      | 单次请求失败后的最大重试                         |
| 单次同步后补充影片详情的最大数量 | int    | 20     | 同步片单后补充详情的上限                         |
| 生成用户画像使用的LLM模型        | string | ""     | 从系统已配置的模型提供商中选择，用于画像分析     |
| 生成推荐时使用的LLM模型          | string | ""     | 从系统已配置的模型提供商中选择，用于推荐理由生成 |

> **LLM模型配置说明**：后两项应在插件初始化时读取 AstrBot 系统已注册的模型提供商列表，以下拉选择的形式呈现给用户，而非让用户手动填写模型名称。

---

## 四、数据存储设计

使用 SQLite（文件路径：插件目录下 `data/douban_movie.db`）。

### 表结构

```sql
-- 用户绑定表
CREATE TABLE user_bind (
    astrbot_uid  TEXT PRIMARY KEY,
    douban_uid   TEXT NOT NULL,
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

## 五、技术约束与规范

1. **开发框架**：遵循 AstrBot 插件 Star 规范（`astrbot.api.star.Star` 基类），入口文件为 `main.py`。
2. **网络请求**：使用 `aiohttp` 或 `httpx`（异步），避免阻塞事件循环。伪装浏览器 UA。
3. **反爬处理**：请求间隔随机化（使用配置项的上下限），遇到 403/429 自动退避重试。
4. **错误处理**：所有指令必须有 try/except 兜底，异常时向用户返回友好提示（不暴露堆栈）。
5. **依赖管理**：第三方库写入 `requirements.txt`。
6. **日志**：使用 `astrbot.api.logger`，关键操作（绑定/同步/推荐）记录 INFO 级别日志。

---

## 六、文件结构（预期）

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

## 七、开发优先级

| 阶段 | 功能                       | 状态      |
| ---- | -------------------------- | --------- |
| P0   | 用户绑定 / 解绑 / 状态查询 | 🟢 待开发 |
| P0   | 片单同步（全量）           | 🟢 待开发 |
| P1   | 用户画像生成               | 🟢 待开发 |
| P1   | 电影推荐（基础版）         | 🟢 待开发 |
| P2   | 增量同步优化               | 🟢 待开发 |
| P2   | 按类型筛选推荐             | 🟢 待开发 |

---

## 八、关键页面参考（开发时抓取 & 解析用）

> 以下 URL 供开发时参考页面结构、CSS 选择器、数据格式。均为公开页面，无需登录即可访问。

| 用途       | URL                                                                    | 说明                                                          |
| ---------- | ---------------------------------------------------------------------- | ------------------------------------------------------------- |
| 个人主页   | `https://www.douban.com/people/{douban_uid}/`                          | 获取用户昵称、观影数量概览                                    |
| 想看片单   | `https://movie.douban.com/people/{douban_uid}/wish`                    | 分页参数 `?start=0&sort=time&rating=all&filter=all&mode=grid` |
| 在看片单   | `https://movie.douban.com/people/{douban_uid}/do`                      | 同上分页参数                                                  |
| 看过片单   | `https://movie.douban.com/people/{douban_uid}/collect`                 | 同上分页，每页 15 条（grid 模式）或 30 条（list 模式）        |
| 电影详情   | `https://movie.douban.com/subject/{movie_id}/`                         | 标题、评分、类型、地区、年代、简介                            |
| Top 250    | `https://movie.douban.com/top250`                                      | 分页 `?start=0&filter=`，每页 25 条，共 10 页                 |
| 豆瓣搜索   | `https://search.douban.com/movie/subject_search?search_text={keyword}` | 按关键词搜索电影，结果含 movie_id                             |
| 移动端详情 | `https://m.douban.com/movie/subject/{movie_id}/`                       | 页面更轻量，反爬压力小，备选方案                              |

**备注**：

- 片单页每页 15 条（grid），可通过 `start` 参数翻页：`start=0, 15, 30, ...`
- 用户豆瓣主页ID即个人主页URL中的路径部分，如 `E-st2000`
- 开发者自己的豆瓣主页（Est）：`https://www.douban.com/people/E-st2000/`，可作为测试用例
