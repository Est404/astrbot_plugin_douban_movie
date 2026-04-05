# astrbot_plugin_douban_movie — 开发需求文档

## 一、项目概述

AstrBot 豆瓣电影推荐插件。用户绑定豆瓣数字ID后，插件通过服务端配置的Cookie访问豆瓣API，获取用户观影统计数据并生成画像，再结合画像与用户输入的关键词在豆瓣搜索并推荐电影。

**数据源**：完全依赖豆瓣，不引入 TMDb 等第三方源。
**存储策略**：明文 SQLite 存储，不做复杂加密，优先性能与可维护性。
**认证方式**：服务端统一配置一个有效的豆瓣Cookie，用户端仅需提供豆瓣数字ID，无需OAuth。

---

## 二、核心功能模块

### 1. 用户绑定（豆瓣数字ID）

**指令**：`/movie bind <豆瓣数字ID或主页链接>`

- 用户发送自己的豆瓣数字ID（如 `159896279`）或主页链接（如 `https://www.douban.com/people/159896279/`），插件自动提取数字ID。
- 绑定流程：
  1. 用户发送 `/movie bind 159896279`（或直接发送主页链接）
  2. 插件使用服务端Cookie访问该用户的 `collection_stats` API，验证可访问性。
  3. 提取用户昵称、观影数量等基础信息作为绑定确认。
  4. 将 `astrbot_user_id ↔ douban_uid` 写入本地数据库。
- 一个 AstrBot 用户只能绑定一个豆瓣账号，重复绑定覆盖旧数据。

**指令**：`/movie unbind`
- 清除当前用户的绑定信息及本地缓存的画像数据。

**指令**：`/movie status`
- 查看当前绑定状态、上次画像生成时间。

### 2. 观影数据获取与用户画像生成

**指令**：`/movie profile`

- 使用服务端Cookie访问豆瓣 Rexxar API 获取用户观影统计：
  - API地址：`https://m.douban.com/rexxar/api/v2/user/{uid}/collection_stats`
  - 请求头需携带Cookie和对应的Referer/UA。
- 返回的数据包含：
  - 标记总数（想看/在看/看过）
  - 观影时长统计
  - 类型偏好（剧情、科幻、动作等，含数量与占比）
  - 地区偏好（含数量与占比）
  - 年代偏好（含数量与占比）
  - 年度标记分布
  - 最近标记的条目
  - 偏爱导演与演员
- 不需要逐条同步用户的完整片单。仅使用 `collection_stats` 这一个API即可获取画像所需的全部统计数据。
- 画像生成使用 LLM 辅助，调用管理员配置的模型（见配置项），将原始统计数据转化为自然语言的用户画像文本。
- **人格化提示词**：在调用LLM生成画像和推荐理由时，必须将当前对话的人格设定（即AstrBot系统提示词中定义的角色人格，例如"佩丽卡"的人设、语气、说话风格等）注入到LLM的system prompt中。这样生成的内容才会带有对话角色的个性化色彩——用户感受到的是"佩丽卡在帮我分析观影画像"，而非一个冰冷的工具在输出数据。
- 画像以文本格式输出，美观简洁，适合聊天窗口阅读。
- 画像数据缓存到本地数据库，避免重复请求API。

**画像输出示例风格**：

```
🎬 Est 的观影画像

📊 观影量：917 部标记（看过 805 / 想看 101 / 在看 11）
⏱ 累计观影：约 1,832 小时

🎭 类型偏好：剧情 (62%) | 科幻 (38%) | 动作 (35%) | ...
🌍 地区偏好：美国 (40%) | 日本 (22%) | 中国大陆 (18%) | ...
📅 年代偏好：2010s (45%) | 2020s (35%) | 2000s (15%) | ...

🎯 评分习惯：偏严格型，均分 3.6
⭐ 偏爱导演：克里斯托弗·诺兰、丹尼斯·维伦纽瓦、...
🌟 偏爱演员：莱昂纳多·迪卡普里奥、...

📝 一句话：一位偏爱剧情与科幻的重度影迷，对欧美电影有明确倾向，同时对日本动画保持关注。
```

### 3. 电影推荐

**指令**：`/movie rec [关键词/描述]`

- 推荐逻辑：
  1. 获取用户的画像数据（类型偏好、地区偏好、年代偏好等）。
  2. 结合用户输入的文本（如"科幻片"、"轻松喜剧"、"想哭"、"诺兰"等），将画像关键词与用户输入合并为搜索条件。
  3. 使用豆瓣搜索接口按关键词搜索电影，按豆瓣评分排序。
  4. **排除该用户历史上所有标记为"已看过"的电影ID**（从 `user_seen_movies` 表中查询，见数据存储设计）。
  5. 在评分达标（≥ 配置的最低评分）且未看过的结果中，取前 N 部（N 可配置）作为候选池，从中随机抽取指定数量的电影推荐给用户。
  6. 不使用 Top 250 榜单。
- 每部推荐电影附带：标题、豆瓣评分、年份、一句话推荐理由。
- 推荐理由使用 LLM 生成，结合用户画像和电影信息。**同样需要注入人格提示词**，使推荐理由带有对话角色的语气风格。
- **人格化提示词**：同画像生成，LLM的system prompt中需包含当前对话角色的人格设定。

**用户反馈机制**：

- 推荐结果下方附带提示：「回复"这些都看过了"重新推荐」
- 用户回复「这些都看过了」后：
  1. 将本次推荐展示的电影ID全部写入 `user_seen_movies` 表，与该用户的 `astrbot_uid` 持久绑定。
  2. 从候选池中排除这些已展示的ID，重新随机抽取。
  3. 如果候选池耗尽，提示用户更换关键词或放宽条件。
- **持久化设计**：`user_seen_movies` 表是用户级的，不是会话级的。用户任何时候标记"看过了"的电影，在后续所有推荐请求中（无论隔多久、换什么关键词）都会被排除。这样避免了跨会话、跨天重复推荐同一部电影的问题。

**搜索接口参考**：

- 搜索地址：`https://search.douban.com/movie/subject_search?search_text={keyword}`
- 或使用移动端API（更轻量）：`https://m.douban.com/search/?query={keyword}&type=movie`

---

## 三、配置项设计

以下配置项在 AstrBot 管理面板中展示，管理员可直接修改：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 豆瓣Cookie | string | "" | 服务端使用的豆瓣登录Cookie，失效后需手动更新 |
| 每次推荐返回的影片数量 | int | 5 | 单次推荐返回几部电影 |
| 推荐候选池大小 | int | 20 | 搜索结果中取前N部作为候选池 |
| 推荐影片的最低豆瓣评分 | float | 7.0 | 低于此评分的影片不参与推荐 |
| 请求间隔下限（秒） | float | 1.0 | 爬取请求的最小间隔 |
| 请求间隔上限（秒） | float | 3.0 | 爬取请求的最大间隔 |
| 请求失败后的最大重试次数 | int | 3 | 单次请求失败后的最大重试 |
| 生成用户画像使用的LLM模型 | string | "" | 从系统已配置的模型提供商中选择，用于画像分析 |
| 生成推荐时使用的LLM模型 | string | "" | 从系统已配置的模型提供商中选择，用于推荐理由生成 |

> **LLM模型配置说明**：后两项应在插件初始化时读取 AstrBot 系统已注册的模型提供商列表，以下拉选择的形式呈现给用户，而非让用户手动填写模型名称。

> **人格提示词注入说明**：在调用LLM生成画像文本和推荐理由时，需将 AstrBot 当前活跃的人格设定（system prompt中的角色定义）作为LLM请求的system prompt的一部分传入。具体实现方式：从AstrBot框架获取当前会话的人格配置文本，拼接到业务提示词之前。这确保了生成内容的语气风格与对话角色一致，用户感知到的是角色在为其服务。

---

## 四、数据存储设计

使用 SQLite（文件路径：插件目录下 `data/douban_movie.db`）。

### 表结构

```sql
-- 用户绑定表
CREATE TABLE user_bind (
    astrbot_uid  TEXT PRIMARY KEY,
    douban_uid   TEXT NOT NULL,          -- 豆瓣数字ID
    nickname     TEXT,                   -- 豆瓣昵称
    bind_time    DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_profile DATETIME               -- 上次画像生成时间
);

-- 用户画像缓存表
CREATE TABLE user_profile (
    astrbot_uid      TEXT PRIMARY KEY,
    profile_text     TEXT,               -- LLM生成的画像文本
    raw_stats        TEXT,               -- collection_stats原始JSON
    genre_prefs      TEXT,               -- 类型偏好JSON
    region_prefs     TEXT,               -- 地区偏好JSON
    decade_prefs     TEXT,               -- 年代偏好JSON
    total_marked     INTEGER,            -- 标记总数
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 用户已看过电影表（持久化，用户级绑定）
-- 当用户反馈"这些都看过了"时，将推荐的电影ID写入此表
-- 后续所有推荐请求均排除此表中的电影
CREATE TABLE user_seen_movies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    astrbot_uid   TEXT NOT NULL,         -- 绑定到用户
    douban_movie_id TEXT NOT NULL,       -- 豆瓣电影ID
    title         TEXT,                  -- 电影标题（方便管理查看）
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(astrbot_uid, douban_movie_id) -- 同一用户同一电影不重复记录
);

-- 推荐会话表（用于支持单次推荐流程中的候选池管理）
CREATE TABLE rec_session (
    session_id    TEXT PRIMARY KEY,      -- 会话ID
    astrbot_uid   TEXT NOT NULL,
    keyword       TEXT,                  -- 本次搜索关键词
    candidate_ids TEXT,                  -- 候选池电影ID列表（JSON数组，已排除user_seen_movies）
    shown_ids     TEXT,                  -- 本次推荐流程中已展示过的电影ID列表（JSON数组）
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 五、技术约束与规范

1. **开发框架**：遵循 AstrBot 插件 Star 规范（`astrbot.api.star.Star` 基类），入口文件为 `main.py`。
2. **网络请求**：使用 `aiohttp` 或 `httpx`（异步），伪装移动端 UA 和必要的请求头。
3. **反爬处理**：请求间隔随机化（使用配置项的上下限），遇到 403/429 自动退避重试。
4. **Cookie管理**：Cookie失效时（API返回401或重定向登录页），向用户提示"管理员需要更新豆瓣Cookie"。
5. **错误处理**：所有指令必须有 try/except 兜底，异常时向用户返回友好提示（不暴露堆栈）。
6. **依赖管理**：第三方库写入 `requirements.txt`。
7. **日志**：使用 `astrbot.api.logger`，关键操作（绑定/画像/推荐）记录 INFO 级别日志。
8. **人格注入**：所有涉及LLM调用的场景（画像生成、推荐理由），必须注入当前对话角色的人格设定到system prompt，确保输出风格与对话角色一致。

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
│   ├── douban_client.py    # 豆瓣API请求封装（collection_stats、搜索等）
│   ├── profile.py          # 画像生成逻辑
│   └── recommender.py      # 推荐搜索与随机抽取逻辑
└── data/                   # 运行时数据库文件（gitignore）
    └── douban_movie.db
```

---

## 七、关键API参考

> 以下 API 需要携带服务端Cookie才能正常访问。

| 用途 | URL/说明 |
| --- | --- |
| 用户观影统计 | `https://m.douban.com/rexxar/api/v2/user/{uid}/collection_stats` — 核心数据源，返回完整观影画像数据 |
| 豆瓣搜索（PC） | `https://search.douban.com/movie/subject_search?search_text={keyword}` — 按关键词搜索电影，需解析HTML |
| 豆瓣搜索（移动端） | `https://m.douban.com/search/?query={keyword}&type=movie` — 更轻量，反爬压力小 |
| 移动端电影详情 | `https://m.douban.com/movie/subject/{movie_id}/` — 获取评分、简介等 |
| Rexxar API头部 | 请求 Rexxar API 时需设置 `Referer: https://m.douban.com/` 及移动端UA |

**备注**：

- 开发者测试用的豆瓣主页（Est）：`https://www.douban.com/people/E-st2000/`，数字ID为 `159896279`

---

## 八、开发优先级

| 阶段 | 功能 | 状态 |
| --- | --- | --- |
| P0 | 用户绑定 / 解绑 / 状态查询（数字ID） | 🟢 待开发 |
| P0 | 观影数据获取（collection_stats API） | 🟢 待开发 |
| P1 | 用户画像生成（LLM辅助 + 人格提示词注入） | 🟢 待开发 |
| P1 | 电影推荐（搜索 + 排除已看过 + 随机抽取 + 人格提示词注入） | 🟢 待开发 |
| P1 | "这些都看过了"→ 持久化记录 + 重新随机 | 🟢 待开发 |
| P2 | Cookie失效检测与提示 | 🟢 待开发 |
| P2 | 画像数据缓存与过期刷新 | 🟢 待开发 |
