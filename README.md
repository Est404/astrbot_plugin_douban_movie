# astrbot_plugin_douban_movie

AstrBot 豆瓣电影推荐插件。用户绑定豆瓣数字ID后，插件通过服务端配置的Cookie访问豆瓣API，获取用户观影统计数据并生成画像，再结合画像与用户输入的关键词在豆瓣搜索并推荐电影。

## 项目状态

**🚧 开发暂停中**

| 阶段 | 功能                                                      | 状态      |
| ---- | --------------------------------------------------------- | --------- |
| P0   | 用户绑定 / 解绑 / 状态查询（数字ID）                      | ✅ 已完成 |
| P0   | 观影数据获取（collection_stats API）                      | ✅ 已完成 |
| P1   | 用户画像生成（LLM辅助 + 人格提示词注入）                  | ✅ 已完成 |
| P1   | 电影推荐（搜索 + 排除已看过 + 随机抽取 + 人格提示词注入） | ⏸️ 暂停   |
| P1   | "这些都看过了" → 持久化记录 + 重新随机                    | ⏸️ 暂停   |
| P2   | Cookie失效检测与提示                                      | ✅ 已完成 |
| P2   | 画像数据缓存与过期刷新                                    | ✅ 已完成 |

### 为什么暂停了？

推荐功能的实现严重依赖豆瓣搜索 API，但实际调试中发现以下问题：

- **搜索质量差**：豆瓣搜索接口对标签、类型等维度过滤能力很弱，无法按 tag 精确检索，候选池质量难以保证。
- **排序不合理**：API 返回的排序逻辑不够透明，按评分排序效果也不理想。
- **天花板明显**：数据源本身的素质决定了一个推荐系统的上限，在 API 层面再怎么包装，底层出来的东西质量有限。

综合评估，继续在豆瓣搜索 API 之上构建推荐功能的投入产出比不划算，项目暂时搁置。如果未来出现更好的电影数据源（如支持标签检索、排序更合理的 API），可以随时在此基础上继续推进。

---

## 一、项目概述

**数据源**：完全依赖豆瓣，不引入 TMDb 等第三方源。  
**存储策略**：明文 SQLite 存储，不做复杂加密，优先性能与可维护性。  
**认证方式**：服务端统一配置一个有效的豆瓣Cookie，用户端仅需提供豆瓣数字ID，无需OAuth。

---

## 二、核心功能模块

### 1. 用户绑定（豆瓣数字ID）

**指令**：`/movie bind <豆瓣数字ID或主页链接>`

- 用户发送自己的豆瓣数字ID（如 `123456`）或主页链接，插件自动提取数字ID。
- 绑定流程：
  1. 用户发送 `/movie bind 123456`（或直接发送主页链接）
  2. 插件使用服务端Cookie访问该用户的 `collection_stats` API，验证可访问性。
  3. 提取用户昵称、观影数量等基础信息作为绑定确认。
  4. 将 `astrbot_user_id ↔ douban_uid` 写入本地数据库。
- 一个 AstrBot 用户只能绑定一个豆瓣账号，重复绑定覆盖旧数据。

**指令**：`/movie unbind` — 清除当前用户的绑定信息及本地缓存的画像数据。

**指令**：`/movie status` — 查看当前绑定状态、上次画像生成时间。

### 2. 观影数据获取与用户画像生成

**指令**：`/movie profile`

- 使用服务端Cookie访问豆瓣 Rexxar API 获取用户观影统计：
  - API地址：`https://m.douban.com/rexxar/api/v2/user/{uid}/collection_stats`
  - 请求头需携带Cookie和对应的Referer/UA（移动端）。
- **不需要逐条同步用户的完整片单**。仅使用 `collection_stats` 这一个API即可获取画像所需的全部统计数据。
- 画像生成使用 LLM 辅助，调用管理员配置的模型（见配置项），将原始统计数据转化为自然语言的用户画像文本。
- **人格化提示词**：在调用LLM生成画像时，必须将当前对话的人格设定（即AstrBot系统提示词中定义的角色人格，如"佩丽卡"的人设、语气、说话风格等）注入到LLM的system prompt中。这样生成的内容才会带有对话角色的个性化色彩——用户感受到的是"角色在帮我分析观影画像"，而非一个冰冷的工具在输出数据。
- 画像以文本格式输出，美观简洁，适合聊天窗口阅读。
- 画像数据缓存到本地数据库，避免重复请求API。

#### 2.1 `collection_stats` API 返回数据完整字段映射

> **以下是该API实际返回的JSON结构，画像生成的每一步都必须严格基于这些字段。**

**顶层统计字段：**

| JSON字段              | 类型  | 画像用途                   | 示例值    |
| --------------------- | ----- | -------------------------- | --------- |
| `total_collections`   | int   | 标记总数（看过+想看+在看） | 917       |
| `total_comment`       | int   | 短评数                     | 724       |
| `total_review`        | int   | 长评数                     | 13        |
| `total_spent`         | float | 累计观影时长（单位：小时） | 2288.1    |
| `total_cenima`        | int   | 影院观影次数               | 202       |
| `weekly_avg`          | float | 周均观影数量               | 1.98      |
| `incr_from_last_week` | float | 相比上周的增长率           | 0.0000031 |

**用户信息字段：**

| JSON路径        | 类型   | 画像用途             | 示例值    |
| --------------- | ------ | -------------------- | --------- |
| `user.name`     | string | 用户昵称，画像标题用 | "name"    |
| `user.uid`      | string | 豆瓣短ID             | "1234"    |
| `user.id`       | string | 豆瓣数字ID           | "1234567" |
| `user.loc.name` | string | 所在城市             | "太阳系"  |

**类型偏好（genres）：**

| JSON路径 | 结构                                    | 说明                        |
| -------- | --------------------------------------- | --------------------------- |
| `genres` | `[{"name": "剧情", "value": 601}, ...]` | 数组，按数量降序，Top10类型 |

画像输出时计算每个类型的占比（value / total_collections），取前5-6个展示。

**地区偏好（countries）：**

| JSON路径    | 结构                                    | 说明             |
| ----------- | --------------------------------------- | ---------------- |
| `countries` | `[{"name": "美国", "value": 491}, ...]` | 数组，按数量降序 |

画像输出时计算占比，取前5个展示。

**年代偏好（years）：**

| JSON路径 | 结构                                                                         | 说明         |
| -------- | ---------------------------------------------------------------------------- | ------------ |
| `years`  | `[{"name": "2020-2025", "value": 60}, {"name": "2010s", "value": 396}, ...]` | 影片年代分布 |

**年度标记分布（collect_years）：**

| JSON路径        | 结构                                                                   | 说明                                                   |
| --------------- | ---------------------------------------------------------------------- | ------------------------------------------------------ |
| `collect_years` | `[{"name": "2018", "value": 20}, {"name": "2019", "value": 333}, ...]` | 用户每年标记了多少部，可用于判断"入坑年份"、"高峰期"等 |

**最爱导演（directors）：**

| JSON路径    | 结构                                                 | 说明    |
| ----------- | ---------------------------------------------------- | ------- |
| `directors` | 数组，每个元素含 `name`、`id`、`avatar`、`known_for` | 取前3名 |

`known_for` 中每个代表作品的结构：

```json
{
  "id": "3541415",
  "title": "盗梦空间",
  "year": "2010",
  "rating": { "value": 9.4, "count": 2318463 },
  "genres": ["剧情", "科幻", "悬疑"],
  "directors": [{ "name": "克里斯托弗·诺兰" }],
  "card_subtitle": "2010 / 美国 英国 / 剧情 科幻 悬疑 冒险 / ..."
}
```

**最爱演员（actors）：**

| JSON路径 | 结构                                                    | 说明    |
| -------- | ------------------------------------------------------- | ------- |
| `actors` | 数组，结构与 `directors` 相同（含 `name`、`known_for`） | 取前3名 |

**高参演人次人员（participants）：**

| JSON路径       | 结构                                        | 说明    |
| -------------- | ------------------------------------------- | ------- |
| `participants` | 数组，导演+演员混合排名，含 `name`、`roles` | 取前5名 |

`roles` 字段示例：`["制片人", "演员", "导演", "编剧", "副导演"]`

**最近标记（recent_subjects）：**

| JSON路径          | 结构          | 说明               |
| ----------------- | ------------- | ------------------ |
| `recent_subjects` | 数组，最多9条 | 用于"最近在看"展示 |

每条结构：

```json
{
  "id": "36846801",
  "title": "辐射 第二季",
  "type": "tv",
  "subtype": "tv",
  "year": "2025",
  "rating": { "value": 8.2, "count": 19713, "star_count": 4.0 },
  "genres": ["剧情", "动作", "科幻"],
  "card_subtitle": "2025 / 美国 / 剧情 动作 科幻 战争 冒险 / ...",
  "directors": [{ "name": "弗雷德里克·E·O·托亚" }],
  "actors": [{ "name": "艾拉·珀内尔" }],
  "cover_url": "https://...",
  "url": "https://movie.douban.com/subject/36846801/"
}
```

**近月统计字段（当月有数据时非空）：**

| JSON路径                | 结构 | 说明         |
| ----------------------- | ---- | ------------ |
| `recent_month_genre`    | 数组 | 近月类型分布 |
| `recent_month_country`  | 数组 | 近月地区分布 |
| `recent_month_director` | 数组 | 近月导演分布 |
| `recent_month_actor`    | 数组 | 近月演员分布 |
| `recent_month_year`     | 数组 | 近月年代分布 |

**可忽略字段：**

| JSON字段           | 说明                             |
| ------------------ | -------------------------------- |
| `viewer`           | 当前查看者信息，通常为空对象     |
| `recent_collected` | 最近标记数，通常为0              |
| `mark_more`        | 豆瓣URI，无用                    |
| `color_scheme`     | 海报颜色方案（UI用，画像不需要） |

#### 2.2 画像生成流程（伪代码）

```
1. 调用 collection_stats API 获取原始JSON
2. 从JSON中提取并组装画像数据结构：
   profile_data = {
       "nickname":        data["user"]["name"],
       "total_marked":    data["total_collections"],
       "total_hours":     data["total_spent"],
       "total_cinema":    data["total_cenima"],
       "total_comments":  data["total_comment"],
       "total_reviews":   data["total_review"],
       "weekly_avg":      data["weekly_avg"],
       "genre_top5":      data["genres"][:5],
       "country_top5":    data["countries"][:5],
       "decades":         data["years"],
       "collect_years":   data["collect_years"],
       "top_directors":   [{"name": d["name"], "known_for": [m["title"] for m in d["known_for"][:2]]} for d in data["directors"][:3]],
       "top_actors":      [{"name": a["name"], "known_for": [m["title"] for m in a["known_for"][:2]]} for a in data["actors"][:3]],
       "top_participants":[{"name": p["name"], "roles": p["roles"][:2]} for p in data["participants"][:5]],
       "recent_watched": [{"title": s["title"], "year": s["year"], "type": s["type"], "rating": s["rating"]["value"]} for s in data["recent_subjects"][:5]],
   }
3. 计算占比：
   for genre in genre_top5:
       genre["percent"] = round(genre["value"] / total_marked * 100)
   同理处理 countries, years
4. 将 profile_data 序列化为可读文本，拼入LLM提示词
5. 调用LLM（注入了人格prompt），生成最终画像文本
6. 缓存：将 raw_stats（原始JSON）和 profile_text（LLM生成的画像）存入 user_profile 表
```

#### 2.3 LLM 画像生成提示词模板

```
你是一位观影分析师，正在为用户 {nickname} 生成观影画像。
请根据以下数据，用简洁生动的语言生成一份观影画像报告。

要求：
- 使用第二人称"你"来称呼用户
- 不要简单罗列数据，要有洞悉和总结
- 最后用一句话概括这位用户的观影品味

用户数据：
{profile_data 序列化后的文本}

输出格式：
🎬 {nickname} 的观影画像

📊 观影量：{total} 部标记
⏱ 累计观影：约 {hours} 小时

🎭 类型偏好：{genre1} (XX%) | {genre2} (XX%) | ...
🌍 地区偏好：{country1} (XX%) | {country2} (XX%) | ...
📅 年代偏好：{decade1} (XX%) | {decade2} (XX%) | ...

🎯 最爱导演：{director1}、{director2}、...
⭐ 最爱演员：{actor1}、{actor2}、...

📌 最近在看：{recent1} ({year}) ⭐{rating} | {recent2} ...

📝 一句话：{基于数据的个性化总结}
```

**画像输出示例：**

```
🎬 Est 的观影画像

📊 观影量：917 部标记
⏱ 累计观影：约 2,288 小时 | 🏢 影院打卡 202 次

🎭 类型偏好：剧情 (66%) | 科幻 (21%) | 爱情 (17%) | 动作 (17%) | 惊悚 (17%)
🌍 地区偏好：美国 (54%) | 英国 (19%) | 日本 (18%) | 法国 (14%) | 德国 (8%)
📅 年代偏好：2010s (43%) | 2000s (23%) | 2020-2025 (7%)

🎯 最爱导演：克里斯托弗·诺兰、史蒂文·斯皮尔伯格、...
⭐ 最爱演员：莱昂纳多·迪卡普里奥、布拉德·皮特、...

📌 最近在看：辐射 第二季 (2025) ⭐8.2 | 极度空间 (1988) ⭐7.4 | 首尔之春 (2023) ⭐8.8

📝 一句话：一位偏爱剧情与科幻的重度影迷，对欧美电影有明显倾向，同时保持对日本动画的关注。2019年是观影高峰期，看片量是一年333部，堪称疯狂。
```

### 3. 电影推荐（暂停开发）

**指令**：`/movie rec [关键词/描述]`

> 此功能因上述原因暂停开发，以下为原始设计方案。

- 推荐逻辑：
  1. 获取用户的画像数据（类型偏好、地区偏好、年代偏好等）。
  2. 结合用户输入的文本（如"科幻片"、"轻松喜剧"、"想哭"、"诺兰"等），将画像关键词与用户输入合并为搜索条件。
  3. 使用豆瓣搜索接口按关键词搜索电影，按豆瓣评分排序。
  4. **排除该用户历史上所有标记为"已看过"的电影ID**（从 `user_seen_movies` 表中查询，见数据存储设计）。
  5. 在评分达标（≥ 配置的最低评分）且未看过的结果中，取前 N 部（N 可配置）作为候选池，从中随机抽取指定数量的电影推荐给用户。
  6. 不使用 Top 250 榜单。
- 每部推荐电影附带：标题、豆瓣评分、年份、一句话推荐理由。
- 推荐理由使用 LLM 生成，结合用户画像和电影信息。**同样需要注入人格提示词**，使推荐理由带有对话角色的语言风格。
- **人格化提示词**：同画像生成，LLM的system prompt中需包含当前对话角色的人格设定。

**用户反馈机制**：

- 推荐结果下方附带提示：「回复"这些都看过了"重新推荐」
- 用户回复"这些都看过了"后：
  1. 将本次推荐展示的电影ID全部写入 `user_seen_movies` 表，与该用户的 `astrbot_uid` 持久绑定。
  2. 从候选池中排除这些已展示的ID，重新随机抽取。
  3. 如果候选池耗尽，提示用户更换关键词或放宽条件。
- **持久化设计**：`user_seen_movies` 表是用户级的，不是会话级的。用户任何时候标记"看过了"的电影，在后续所有推荐请求中（无论隔多久、换什么关键词）都会被排除。这避免了跨会话、跨天重复推荐同一部电影的问题。

**搜索接口参考**：

- PC搜索：`https://search.douban.com/movie/subject_search?search_text={keyword}`（需解析HTML）
- 移动端搜索：`https://m.douban.com/search/?query={keyword}&type=movie`（更轻量，反爬压力小）

---

## 三、配置项设计

以下配置项在 AstrBot 管理面板中展示，管理员可直接修改：

| 配置项                    | 类型   | 默认值 | 说明                                             |
| ------------------------- | ------ | ------ | ------------------------------------------------ |
| 豆瓣Cookie                | string | ""     | 服务端使用的豆瓣登录Cookie，失效后需手动更新     |
| 每次推荐返回的影片数量    | int    | 5      | 单次推荐返回几部电影                             |
| 推荐候选池大小            | int    | 20     | 搜索结果中取前N部作为候选池                      |
| 推荐影片的最低豆瓣评分    | float  | 7.0    | 低于此评分的影片不参与推荐                       |
| 请求间隔下限（秒）        | float  | 1.0    | 爬取请求的最小间隔                               |
| 请求间隔上限（秒）        | float  | 3.0    | 爬取请求的最大间隔                               |
| 请求失败后的最大重试次数  | int    | 3      | 单次请求失败后的最大重试                         |
| 生成用户画像使用的LLM模型 | string | ""     | 从系统已配置的模型提供商中选择，用于画像分析     |
| 生成推荐时使用的LLM模型   | string | ""     | 从系统已配置的模型提供商中选择，用于推荐理由生成 |

> **LLM模型配置说明**：后两项应在插件初始化时读取 AstrBot 系统已注册的模型提供商列表，以下拉选择的形式呈现给用户，而非让用户手动填写模型名称。

> **人格提示词注入说明**：在调用LLM生成画像文本和推荐理由时，需将 AstrBot 当前活跃的人格设定（system prompt 中的角色定义）作为LLM请求的system prompt的一部分传入。具体实现方式：从AstrBot框架获取当前会话的人格配置文本，拼接到业务提示词之前。这确保了生成内容的语言风格与对话角色一致，用户感知到的是角色在为其服务。

---

## 四、数据存储设计

使用 SQLite（文件路径：插件目录下 `data/douban_movie.db`），明文存储。

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
7. **日志**：使用 `astrbot.api.logger`，关键操作记录 INFO 级别日志。
8. **人格注入**：所有涉及LLM调用的场景（画像生成、推荐理由生成），必须注入当前对话角色的人格设定到system prompt，确保输出风格与对话角色一致。

---

## 六、文件结构

```
astrbot_plugin_douban_movie/
├── main.py                 # 插件入口，注册指令
├── metadata.yaml           # 插件元数据
├── requirements.txt        # 依赖
├── README.md              # 本文档
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

| 用途               | URL/说明                                                                                              |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| 用户观影统计       | `https://m.douban.com/rexxar/api/v2/user/{uid}/collection_stats` — 核心数据源，返回完整观影画像数据   |
| 豆瓣搜索（PC）     | `https://search.douban.com/movie/subject_search?search_text={keyword}` — 按关键词搜索电影，需解析HTML |
| 豆瓣搜索（移动端） | `https://m.douban.com/search/?query={keyword}&type=movie` — 更轻量，反爬压力小                        |
| 移动端电影详情     | `https://m.douban.com/movie/subject/{movie_id}/` — 获取评分、简介等                                   |
| Rexxar API头部     | 请求时需设置 `Referer: https://m.douban.com/` 及移动端UA                                              |
