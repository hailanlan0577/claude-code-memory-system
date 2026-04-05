# Claude Code Memory System

**中文** | [English](./README_EN.md)

**给 Claude Code 装上永久记忆。**

三合一记忆系统：Qdrant 向量语义搜索 + Graphiti 知识图谱推理 + Obsidian 笔记自动同步。跨会话记忆持久化，对话不再从零开始。

---

## 实际工作中的作用

没有记忆系统时，你和 Claude Code 的每次对话都是一张白纸。装上记忆系统后，Claude 变成了一个"记得所有事"的长期搭档。以下是真实工作中的典型场景：

### 场景 1：跨会话调试——"上次那个 Bug 怎么修的？"

**没有记忆**：

> 你：Qdrant 连接超时了，报 408 错误
>
> Claude：请检查网络连接、端口是否开放、防火墙设置...（给你一堆通用建议）

**有记忆**：

> 你：Qdrant 连接超时了，报 408 错误
>
> Claude：（自动搜索到 3 月 31 日的 debug 记忆）上次你遇到过同样的问题，根因是 httpx 默认走了系统代理连本地 Qdrant。修复方法是在代码开头加 `os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")`。要我直接帮你加上吗？

**差别**：从"猜"变成"记得"。debug 类记忆被标记为 high importance，搜索时加权 1.3x，确保能被优先召回。

### 场景 2：架构决策追溯——"当时为什么这么选？"

开发到一半，你或者团队成员质疑某个技术选型：

> 你：我们的 embedding 为什么用阿里云的，不用 OpenAI 的？

**没有记忆**：Claude 只能从技术角度泛泛分析两者优劣。

**有记忆**：

> Claude：（搜到 3 月 26 日的 decision 记忆）你在 3 月 26 日做了这个决策。原因是：
> 1. all-MiniLM-L6-v2 中文语义理解差，跨词汇搜索失败
> 2. OpenAI embedding 需要翻墙，延迟不稳定
> 3. text-embedding-v4 支持 8192 Token（原来只有 512），中文表现大幅提升
>
> 当时还对比了 BGE-M3，最终因为阿里云 API 更稳定而选了 text-embedding-v4。

**差别**：不只是"用了什么"，还记得"为什么"和"否决了什么"。三个月后回头看，不用翻聊天记录。

### 场景 3：项目上下文无缝切换——"这个项目之前做到哪了？"

你同时维护多个项目，切换项目时最痛苦的是重建上下文：

> 你：继续做那个中国象棋项目

**没有记忆**：Claude 只知道目录里有什么文件，不知道你的进度、踩过的坑、下一步计划。

**有记忆**：

> Claude：（搜到 project 和 solution 类记忆）上次你完成了棋子移动逻辑和将军判定，但"马腿"规则还有 Bug——马在被蹩腿时仍然可以跳。你当时的思路是在 `canMove()` 里加一个 `isBlocked()` 检查。另外吃子动画还没做，你说过想用 Framer Motion。要从哪个继续？

**差别**：不是从零开始读代码，而是直接接上你上次的思路。

### 场景 4：重复问题自动过滤——"这个我之前问过吗？"

开发过程中经常会反复踩同一个坑：

> 你：Claude Code MCP 工具没加载出来，graphiti 的工具列表是空的

**没有记忆**：Claude 让你检查配置文件、重启服务...你试了一圈发现都不对。

**有记忆**：

> Claude：（搜到 3 月 26 日的 debug 记忆，这个坑踩过 3 次）这个问题你之前遇到过。根因是 **Claude Code 只读 `~/.claude.json`，不读 `~/.claude/mcp.json`**。你需要用 `claude mcp add graphiti --transport http http://localhost:18001/mcp` 注册到正确的配置文件。上次修好后还发现 transport 必须是 http 不能是 sse，也要注意。

**差别**：同一个坑不踩第二次。debug 记忆记录了现象、根因、修复方法，直接给出完整解决方案。

### 场景 5：知识图谱关联发现——"这些事情之间有什么关系？"

Qdrant 向量搜索能找到"相似的内容"，但 Graphiti 能发现"隐藏的关联"：

> 你：最近哪些模块改动过？它们之间有关联吗？

**只有 Qdrant**：列出最近的修改记录，但看不出模块间的依赖关系。

**有 Graphiti**：

> Claude：（hybrid_search 同时查询 Qdrant + Graphiti）最近改动了 3 个模块：
> - `server_v3.py` 的 `hybrid_search` 函数
> - `session-to-obsidian.py` 的 Qdrant 写入逻辑
> - LaunchAgent 的环境变量配置
>
> Graphiti 图谱显示它们有关联：`hybrid_search` 内部依赖 Graphiti MCP（HTTP 协议），而 LaunchAgent 负责启动 Graphiti 进程。上次 LaunchAgent 改了 Python 路径导致 Graphiti 没启动，hybrid_search 就全部超时了。这三个改动很可能是同一条链路上的问题。

**差别**：从"列清单"变成"讲故事"，理解模块间的因果关系。

### 场景 6：Obsidian 低成本召回——"那份设计文档里怎么写的？"

Claude 之前帮你写了一份 5000 字的设计文档，存在 Obsidian 里：

> 你：之前那个 AI 买手评分系统的设计方案，评分维度有哪些？

**没有向量化**：通过 Obsidian MCP 读取原文，消耗 8000+ Token，还要等几秒加载。

**有向量化（Obsidian 同步到 Qdrant）**：

> Claude：（search_memory 命中 Obsidian 同步的向量，消耗 ~300 Token）评分维度包括：
> 1. 品相评估分（成色、划痕、氧化程度）
> 2. 价格合理性分（对比历史成交价）
> 3. 市场热度分（品牌 × 款式 × 颜色的流通速度）
> 4. 利润空间分（预估售价 - 进价 - 养护成本）

**差别**：同样的信息，Token 消耗从 8000 降到 300，快了 10 倍以上。一天问 20 次，省下来的 Token 很可观。

### 场景 7：长期趋势分析——"这几个月的规律是什么？"

记忆积累到一定量后，可以做回顾性分析：

> 你：总结一下我最近三个月用 Claude Code 主要做了什么

> Claude：（search_memory + keyword_search 按日期范围搜索）
> - **1 月**：主要在做中国象棋 React 项目，完成了棋盘渲染和基本走子规则
> - **2 月**：转向二手奢侈品库存管理 App，用 Flutter + Supabase，完成了商品录入和拍照功能
> - **3 月**：大量时间花在记忆系统搭建上——从 Pinecone 迁移到 Qdrant，集成 Graphiti，embedding 从小模型升级到 text-embedding-v4，解决了十几个连通性 Bug
> - **贯穿三个月**：Obsidian 笔记体系逐步建立，会话自动归档流程从手动变成全自动
>
> 技术偏好变化：从 JavaScript 转向 Python 后端 + Flutter 前端的组合。

**差别**：你自己可能都忘了三个月前在做什么，但记忆系统帮你保留了完整的工作轨迹。

### 场景 8：新项目冷启动——"帮我搭建一个新项目"

> 你：帮我搭建一个 Next.js 项目

**没有记忆**：Claude 给你一个标准模板。

**有记忆**：

> Claude：（搜到 preference 类记忆）根据你之前的偏好：
> - 你习惯用 TypeScript strict 模式
> - 状态管理偏好 Zustand 而不是 Redux
> - 样式方案之前选了 Tailwind CSS
> - 你讨厌默认的 ESLint 配置太松，上次手动加了 `@typescript-eslint/strict`
> - 测试框架用 Vitest
>
> 我直接按这些偏好初始化，行吗？

**差别**：Claude 变成了了解你编程习惯的搭档，不需要每次重复说"我要 TypeScript"、"我用 Tailwind"。

---

## 有记忆 vs 没记忆

| | 没有记忆系统 | 只有 Qdrant 向量记忆 | Qdrant + Graphiti + Obsidian |
|---|---|---|---|
| **跨会话** | 关窗口全忘，每次从零开始 | 每轮对话自动存入向量数据库，永久保留 | 同左 |
| **搜索能力** | 只有 `MEMORY.md`（手写 200 行笔记） | 语义搜索，搜"包的管理"能找到"包务模块" | 同左 + 精确关键词搜索 |
| **知识推理** | 无法回答"谁负责这个模块" | **做不到** — 只能按相似度找文本，不理解实体关系 | Graphiti 自动提取实体并建立关系 |
| **笔记整合** | Obsidian 笔记和 Claude 割裂 | 手动复制粘贴 | 每 5 分钟自动同步 Obsidian → 向量库 |
| **搜索策略** | `grep` | 语义搜索（一种方式） | 语义 + 关键词 + 图谱融合搜索 |

**一句话总结：Qdrant 让你"找到"，Graphiti 让你"理解"，Obsidian 让你"沉淀"。**

---

## 核心机制

### 1. 自动记忆：会话结束时自动归档到向量库

Claude Code 本身没有跨会话记忆——关掉终端，一切归零。这套系统通过 **Hook 自动归档** 解决这个问题：

```
会话 A（你和 Claude 的一次完整对话）
  │
  ├── 你关掉窗口 / 开启新会话
  │
  └── SessionEnd Hook 自动触发：
      └── session-to-obsidian.py 读取会话 A 的完整对话记录
          │
          ├── ① 写入 Obsidian — 完整 Markdown 归档（结构化笔记）
          ├── ② 写入 Qdrant  — 每轮 Q&A 向量化存储（语义可搜）
          └── ③ 写入 Graphiti — 会话摘要提取实体和关系（图谱推理）

会话 B（新窗口）
  │
  ├── SessionStart Hook 自动触发：
  │   └── 扫描未归档的历史会话，补推失败项（3 次重试 + pending 暂存）
  │
  └── 你提问时，Claude 自动 search_memory
      → 召回会话 A 及更早的相关记忆，融入回答
```

**整个过程完全自动**。你只需要正常使用 Claude Code，关窗口的那一刻，上一个会话的所有内容就被归档到三个系统中。下次开新窗口，历史记忆自动可用。

**可靠性设计**：三个目标（Obsidian / Qdrant / Graphiti）独立互不阻塞，任何一个失败不影响其他两个。失败项暂存到 pending 目录，下次新会话启动时自动重试。

这意味着：
- 上周调试的 Bug，这周问"上次那个 Redis 连接超时怎么解决的"，Claude 直接给你答案
- 三个月前的架构决策，问"当时为什么选了 PostgreSQL 而不是 MongoDB"，理由自动浮现
- 每轮 Q&A 按 category 分类存储（debug/decision/solution/feedback...），重要记忆加权，闲聊降权

### 2. Obsidian 回流：笔记变成低成本记忆

上面说了，每次关窗口会话内容会自动写入 Obsidian。除此之外，Claude Code 在工作过程中也会往 Obsidian 写入各种文档——设计方案、复盘报告、架构图、TODO 清单等。

这些文档沉淀在 Obsidian vault 里，是很好的知识库。但问题是，**Claude Code 要读取它们代价很高**：

| 读取方式 | Token 消耗 | 速度 |
|---|---|---|
| 通过 Obsidian MCP 读原文 | **数千~数万 Token**（取决于文档长度） | 慢（全文加载到上下文） |
| 通过 Qdrant 向量搜索 | **几百 Token**（只返回相关片段） | 快（毫秒级语义匹配） |

**这就是 Obsidian 同步脚本的核心价值**——把 Obsidian 里的文档向量化后存入 Qdrant，让 Claude Code 用极低的 Token 成本就能召回这些知识：

```
完整的记忆闭环：

Claude Code 会话
  │
  ├── 关窗口 → SessionEnd Hook
  │   ├── 完整对话写入 Obsidian（Markdown 归档）
  │   ├── 每轮 Q&A 写入 Qdrant（向量记忆）
  │   └── 会话摘要写入 Graphiti（知识图谱）
  │
  ├── 工作中 → Claude 主动写入 Obsidian
  │   └── 设计文档、复盘报告、方案对比等
  │
  └── obsidian-sync-qdrant.py（每 5 分钟自动运行）
      ├── 通过 Obsidian REST API 扫描所有 .md 文件
      ├── content hash 变更检测（只处理新增/修改的）
      ├── 长文档自动分块
      ├── text-embedding-v4 向量化 → 写入 Qdrant
      └── 实体提取 → 写入 Graphiti
          │
          └── 效果：下次新会话提问时
              └── search_memory 就能搜到 Obsidian 里的所有内容
                  → 不需要打开文件、不需要读全文
                  → 只返回语义相关的片段
                  → Token 消耗降低 90%+
```

**关键理解**：Obsidian 在这套系统中是信息的**沉淀层**，不是信息的源头。信息的源头是 Claude Code 的对话。会话归档和工作文档都汇入 Obsidian，同步脚本再把它们回流到向量库，形成一个**写入 → 沉淀 → 低成本召回**的闭环。相比每次都去 Obsidian 读原文，向量搜索节省了 90% 以上的 Token。

---

## 架构

```
Claude Code
│
├── MCP: qdrant-memory-v3 (stdio)          ← 向量语义记忆
│   ├── store_memory      存储（自动去重）
│   ├── search_memory     语义搜索（加权 + 时间衰减 + 去重）
│   ├── keyword_search    精确关键词搜索
│   ├── hybrid_search     融合搜索（Qdrant + Graphiti 并行）
│   ├── delete_memory     精确/模糊删除
│   ├── update_memory     原地更新
│   ├── compact_conversations  按天压缩旧对话
│   └── memory_stats      统计信息
│
├── MCP: graphiti (HTTP)                   ← 知识图谱
│   ├── add_memory         写入（自动提取实体和关系）
│   ├── search_nodes       搜索实体节点
│   └── search_memory_facts 搜索关系事实
│
└── 双写规则：每次回复 → 同时写入 Qdrant + Graphiti
│
│   ┌─────────────────────────────────────────────┐
│   │  hybrid_search 内部：                        │
│   │  线程 1: Qdrant 向量搜索                      │
│   │  线程 2: Graphiti Streamable HTTP 图谱搜索     │
│   │  → 结果合并去重统一返回                        │
│   └─────────────────────────────────────────────┘
│
├── Docker
│   ├── Qdrant     (localhost:6333)   向量数据库
│   └── Neo4j 5    (localhost:7687)   图数据库（Graphiti 后端）
│
└── Obsidian 自动同步（LaunchAgent, 每 5 分钟）
    └── obsidian-sync-qdrant.py
        ├── Obsidian REST API 读取笔记
        ├── text-embedding-v4 生成向量
        ├── 写入 Qdrant（增量，content hash 变更检测）
        └── 写入 Graphiti（实体提取）
```

### Qdrant vs Graphiti 各自的角色

| | Qdrant 向量数据库 | Graphiti 知识图谱 |
|---|---|---|
| **存什么** | 完整文本的向量编码 | 从文本中提取的实体、关系、事实 |
| **怎么搜** | 向量余弦相似度（语义搜索） | 图遍历（实体关系查询） |
| **擅长** | "找类似的内容"（模糊匹配） | "找关联的事物"（精确推理） |
| **举例** | 搜"退货" → 找到所有退货相关对话 | 搜"张哥" → 发现他是供货方，供了什么货 |
| **弱点** | 不理解实体关系 | 不擅长语义模糊匹配 |
| **底层** | Qdrant (port 6333) | Neo4j (port 7687) |

**`hybrid_search` 把两者并行查询、统一返回**，弥补各自弱点。

---

## 目录结构

```
├── mcp-qdrant-memory/             # 核心：Qdrant MCP 服务端
│   ├── server_v3.py               #   主服务（9 个 MCP 工具）
│   ├── compact_v3.py              #   记忆压缩工具（按天合并旧对话）
│   ├── healthcheck.sh             #   15 项一键诊断脚本
│   ├── requirements.txt           #   Python 依赖
│   ├── migrate_to_v3.py           #   从 v2 迁移数据
│   ├── backfill_importance.py     #   补填 importance 字段
│   ├── capacity_alert.py          #   容量告警
│   └── openclaw-plugin-v3/        #   OpenClaw 飞书网关插件
│
├── graphiti-local/                # Graphiti MCP 本地服务
│   ├── mcp_server/                #   MCP Server 源码
│   │   ├── src/graphiti_mcp_server.py  #   主入口
│   │   ├── config/                #   配置模板
│   │   ├── pyproject.toml         #   依赖定义
│   │   └── tests/                 #   测试
│   └── patches/                   #   中文优化补丁（去重/提取 prompt）
│
├── memory-docker/                 # Docker 编排
│   ├── docker-compose.yml         #   Qdrant + Neo4j 一键启动
│   ├── migrate_qdrant.py          #   Qdrant 数据迁移
│   └── migrate_graphiti.py        #   Graphiti 数据迁移
│
├── claude-config/                 # Claude Code 配置参考
│   ├── docs/memory-system.md      #   完整架构文档（已知坑 & 修复历史）
│   └── scripts/                   #   Obsidian 同步脚本
│       └── obsidian-sync-qdrant.py  # Obsidian → Qdrant + Graphiti
│
├── launchagents/                  # macOS LaunchAgent 模板
│   ├── com.claude.obsidian-sync-qdrant.plist  # Obsidian 同步守护
│   ├── com.graphiti.tunnel.plist              # Graphiti 服务进程
│   └── com.qdrant.ssh-tunnel.plist            # SSH 隧道（多机场景）
│
└── bin/                           # 启动脚本
    ├── graphiti-tunnel.sh         #   Graphiti MCP 进程启动
    └── qdrant-tunnel.sh           #   Qdrant SSH 隧道
```

---

## 快速开始

### 前置要求

| 依赖 | 用途 | 安装 |
|------|------|------|
| Docker Desktop | 运行 Qdrant + Neo4j | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Python 3.11+ | 运行 MCP Server | `brew install python@3.11` |
| Claude Code CLI | AI 编程助手 | [claude.ai/code](https://claude.ai/code) |
| 阿里云 DashScope API Key | text-embedding-v4 向量化 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) |
| Obsidian + Local REST API 插件 | （可选）笔记同步 | [obsidian.md](https://obsidian.md/) |

> **关于 Embedding 模型**：本项目默认使用阿里云 text-embedding-v4（1024 维，8192 Token，中文表现优异）。你可以替换为 OpenAI text-embedding-3-small 或其他兼容 REST API 的 embedding 服务，只需修改 `server_v3.py` 中的 `get_embedding()` 函数。

### 第 1 步：启动 Docker 容器

```bash
git clone https://github.com/hailanlan0577/claude-code-memory-system.git
cd claude-code-memory-system/memory-docker

# 修改 Neo4j 密码（编辑 docker-compose.yml 中的 NEO4J_AUTH）
docker compose up -d
```

启动后验证：

```bash
# Qdrant 应返回 {"title":"qdrant - vectorass engine",...}
curl http://localhost:6333

# Neo4j 浏览器打开 http://localhost:7474
```

### 第 2 步：配置环境变量

在 `~/.zshenv`（或 `~/.bashrc`）中添加：

```bash
# 必须：阿里云 Embedding API
export DASHSCOPE_API_KEY=your_dashscope_api_key

# 可选：Obsidian REST API（仅同步功能需要）
export OBSIDIAN_API_KEY=your_obsidian_api_key
```

重新加载：`source ~/.zshenv`

### 第 3 步：安装 Qdrant MCP Server

```bash
cd mcp-qdrant-memory
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

注册到 Claude Code：

```bash
claude mcp add qdrant-memory-v3 \
  -e DASHSCOPE_API_KEY \
  -- /path/to/mcp-qdrant-memory/venv/bin/python \
  /path/to/mcp-qdrant-memory/server_v3.py
```

### 第 4 步：安装 Graphiti MCP Server

```bash
cd graphiti-local/mcp_server
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
```

配置 `.env` 文件：

```bash
cp .env.example .env
# 编辑 .env，填入 Neo4j 密码和 OpenAI/其他 LLM API Key
# Graphiti 需要 LLM 来提取实体和关系
```

应用中文优化补丁（可选，提升中文实体提取质量）：

```bash
cd ../patches
bash apply-patches.sh
```

启动 Graphiti 服务：

```bash
cd ../mcp_server
venv/bin/python src/graphiti_mcp_server.py --transport http --port 18001
```

注册到 Claude Code：

```bash
claude mcp add graphiti --transport http http://localhost:18001/mcp
```

### 第 5 步：验证安装

```bash
# 健康检查（15 项诊断）
bash mcp-qdrant-memory/healthcheck.sh
```

重启 Claude Code，在对话中测试：

```
> 记住：我喜欢用 Python 写后端，前端用 React

# Claude 应自动调用 store_memory 存储这条偏好
# 后续对话中搜索相关记忆时会自动召回
```

### 第 6 步：配置双写规则（推荐）

在你的项目 `CLAUDE.md` 中添加以下规则，让 Claude 每次实质性回复后自动同时写入两个系统：

```markdown
## 自动对话记录

每次回复用户后，同时执行：

### 写入 Qdrant
调用 `mcp__qdrant-memory-v3__store_memory`：
- content: "[问] 问题摘要\n[答] 回答摘要\n[上下文] 项目/技术栈"
- category: conversation（或 debug/decision/solution/feedback）
- tags: "日期,项目名,技术关键词"

### 写入 Graphiti
调用 `mcp__graphiti__add_memory`：
- name: "[YYYY-MM-DD] 主题摘要"
- episode_body: 与 Qdrant content 相同
- group_id: "claude_code"
```

完整的双写规则模板和分类自检流程请参考 `claude-config/docs/memory-system.md` 第三节。

### 第 7 步：Obsidian 自动同步（可选）

如果你使用 Obsidian 做笔记，可以配置自动同步，将笔记内容持续同步到 Qdrant + Graphiti：

1. 安装 Obsidian 插件 [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api)，生成 API Key
2. 复制同步脚本：

```bash
mkdir -p ~/.claude/scripts/hooks
cp claude-config/scripts/obsidian-sync-qdrant.py ~/.claude/scripts/hooks/
```

3. 配置 LaunchAgent 守护进程（macOS）：

```bash
# 编辑 plist，修改脚本路径和 API Key
cp launchagents/com.claude.obsidian-sync-qdrant.plist ~/Library/LaunchAgents/
# 修改后加载
launchctl load ~/Library/LaunchAgents/com.claude.obsidian-sync-qdrant.plist
```

同步脚本每 5 分钟通过 Obsidian REST API 读取笔记，增量同步（基于 content hash 变更检测），自动分块长文档。

---

## 搜索工具详解

### 9 个 MCP 工具一览

| 工具 | 用途 | 特点 |
|------|------|------|
| `store_memory` | 存储记忆 | 自动去重（相似度 >0.92 跳过），自动 importance 分级 |
| `search_memory` | 语义搜索 | 向量相似度 + importance 加权 + 时间衰减 + 结果去重 |
| `keyword_search` | 关键词搜索 | 精确匹配 content 和 tags，支持日期搜索 |
| `hybrid_search` | 融合搜索 | **并行查询 Qdrant 向量 + Graphiti 图谱，统一返回** |
| `delete_memory` | 删除记忆 | 支持精确内容删除和语义模糊删除 |
| `update_memory` | 更新记忆 | 原地更新，保留原始 ID 和创建时间 |
| `list_memories` | 浏览记忆 | 按分类列出所有记忆 |
| `compact_conversations` | 压缩对话 | 按天合并旧 conversation 记忆为摘要 |
| `memory_stats` | 统计信息 | 各分类计数，60 秒 TTL 缓存 |

### 搜索策略指南

| 你想做什么 | 用哪个工具 | 为什么 |
|---|---|---|
| 模糊搜索（"退货相关的问题"） | `search_memory` | 向量语义理解，不需要精确词匹配 |
| 精确搜索（"PR200156"、"2026-03-19"） | `keyword_search` | 文本精确匹配，不会遗漏 |
| 实体关系（"张哥和我们什么关系"） | `hybrid_search` | Graphiti 图谱推理实体关系 |
| 跨项目关联（"哪些项目用了 Redis"） | `hybrid_search` | Graphiti 关系遍历 |
| 什么都搜不到 | 两个都试 | 向量和关键词互补 |

### importance 权重机制

记忆按 category 自动分级，搜索时加权排序：

| importance | 权重 | 对应的 category |
|---|---|---|
| **high** (★) | 1.3x | project, architecture, solution, preference, debug, feedback, decision, summary |
| **medium** (☆) | 1.0x | fact, general, conversation |
| **low** (·) | 0.7x | other |

搜索结果还会叠加**时间衰减**：近 7 天 1.2x 加权，7-30 天 1.0x，1-3 月 0.9x，3-12 月 0.8x，1 年以上 0.7x。

### hybrid_search 内部工作原理

```
调用 hybrid_search(query="张哥的供货记录")
│
├── 线程 1: Qdrant 向量搜索
│   └── text-embedding-v4 → cosine similarity → top N
│
└── 线程 2: Graphiti 图谱搜索（Streamable HTTP）
    ├── POST /mcp → initialize（获取 Mcp-Session-Id）
    ├── POST /mcp → tools/call: search_nodes
    └── POST /mcp → tools/call: search_memory_facts
│
└── 合并结果 → 去重 → 加权排序 → 返回
```

---

## 记忆分类体系

| category | 什么时候用 | 示例 |
|---|---|---|
| `conversation` | 日常对话记录（自动双写） | "[问] 如何配置 Redis [答] 推荐使用 docker..." |
| `project` | 项目关键信息 | "luxury-bag-inventory 使用 Flutter + Supabase" |
| `architecture` | 架构决策 | "记忆系统从双机共享改为双机独立" |
| `decision` | 技术选型 | "选择 text-embedding-v4 而非 OpenAI embedding" |
| `solution` | 问题解决方案 | "Neo4j dump 要先停库，改用 APOC stream 导出" |
| `debug` | Bug 调试经验 | "Graphiti 404 根因：用了废弃的 SSE transport" |
| `feedback` | 用户纠正行为 | "不要在测试中 mock 数据库" |
| `preference` | 用户偏好 | "用户偏好 Python 后端 + React 前端" |
| `summary` | 压缩后的摘要 | compact_conversations 生成 |
| `general` | 通用信息 | 不属于以上任何分类 |

---

## 进阶配置

### 替换 Embedding 模型

修改 `server_v3.py` 中的 `get_embedding()` 函数。例如切换为 OpenAI：

```python
EMBEDDING_API_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_DIM = 1536  # 或 1024/512

def get_embedding(text: str, text_type: str = "document") -> list[float]:
    resp = _http_client.post(
        EMBEDDING_API_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", ...},
        json={"model": EMBEDDING_MODEL, "input": text, "dimensions": VECTOR_DIM},
    )
    return resp.json()["data"][0]["embedding"]
```

> **注意**：更换 embedding 模型后需要重建 Qdrant collection 并重新导入数据（维度变化）。

### 多机部署

`bin/qdrant-tunnel.sh` 提供了通过 SSH 隧道跨机器访问 Qdrant 的方案：

```bash
# MacBook Pro → Mac Mini 的 Qdrant
ssh -fNL 26333:localhost:6333 macmini

# server_v3.py 中 search_openclaw_memory 即通过此隧道访问远端记忆
```

适合在多台机器间共享记忆、或将数据库部署在服务器上的场景。

### 守护进程（macOS LaunchAgent）

`launchagents/` 目录提供了三个守护进程模板：

| 文件 | 功能 | 频率 |
|------|------|------|
| `com.graphiti.tunnel.plist` | Graphiti MCP 进程保活 | KeepAlive |
| `com.qdrant.ssh-tunnel.plist` | SSH 隧道保活 | KeepAlive |
| `com.claude.obsidian-sync-qdrant.plist` | Obsidian 同步 | 每 5 分钟 |

修改路径和 API Key 后：

```bash
cp launchagents/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.graphiti.tunnel.plist
```

Linux 用户可参考 plist 配置改写为 systemd service。

---

## 健康检查

```bash
bash mcp-qdrant-memory/healthcheck.sh        # 诊断
bash mcp-qdrant-memory/healthcheck.sh --fix   # 自动修复
```

检查 15 项：

1. Qdrant 容器连通性
2. Neo4j / Graphiti 连通性
3. Graphiti MCP Server（HTTP transport）
4. Claude Code MCP 注册状态
5. `server_v3.py` 代码完整性（Streamable HTTP vs 废弃 SSE）
6. Qdrant 数据可读性
7. Graphiti `search_nodes` 端到端测试
8. 记忆总量和 conversation 占比（>60% 建议 compact）
9. DashScope Embedding API 可用性
10. 备份新鲜度
11. 技术文档完整性

---

## 已知坑 & 避坑指南

这些是我们踩过的坑，帮你避免重复犯错：

| 坑 | 根因 | 正确做法 |
|---|---|---|
| Graphiti MCP 工具不出现 | Claude Code 只读 `~/.claude.json`，不读 `~/.claude/mcp.json` | 用 `claude mcp add` 命令注册 |
| Graphiti 返回 404 | 使用了废弃的 `--transport sse` | 必须用 `--transport http` |
| `hybrid_search` 中 Graphiti 始终超时 | 代码用 SSE 协议（`GET /sse`）连 HTTP 服务 | 使用 Streamable HTTP（`POST /mcp` + `Mcp-Session-Id`） |
| Neo4j dump 要先停库 | `neo4j-admin database dump` 不支持在线导出 | 用 `CALL apoc.export.json.all(null, {stream:true})` |
| 中文语义搜索差 | 小模型（all-MiniLM-L6-v2）中文理解弱 | 换大模型级 embedding（text-embedding-v4） |
| MCP 配置中密钥明文 | `~/.claude.json` 的 `env` 字段直接写密钥 | 密钥放 `~/.zshenv`，MCP 子进程通过环境变量继承 |

完整的故障处理历史和修复方案见 `claude-config/docs/memory-system.md` 第五节。

---

## 备份与恢复

### 备份

```bash
# Qdrant 快照
curl -X POST "http://localhost:6333/collections/unified_memories_v3/snapshots"
# 下载快照
curl -o qdrant-backup.snapshot \
  "http://localhost:6333/collections/unified_memories_v3/snapshots/<snapshot_name>"

# Neo4j 导出（在线）
docker exec neo4j-memory cypher-shell -u neo4j -p YOUR_PASSWORD \
  "CALL apoc.export.json.all(null, {stream:true, useTypes:true}) YIELD data RETURN data" \
  > neo4j-backup.json
```

### 恢复

```bash
# Qdrant 恢复
curl -X POST "http://localhost:6333/collections/unified_memories_v3/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@qdrant-backup.snapshot"

# Neo4j 恢复（需要 APOC 插件）
cat neo4j-backup.json | docker exec -i neo4j-memory \
  cypher-shell -u neo4j -p YOUR_PASSWORD \
  "CALL apoc.import.json(null, {stream:true})"
```

---

## 谁适合用这套系统

这套系统不限于编程场景。任何需要"跨会话记忆 + 实体关系 + 知识沉淀"的角色都能受益：

| 角色 | Qdrant 帮你做什么 | Graphiti 额外做什么 |
|---|---|---|
| **开发者** | 搜索历史调试经验、架构决策 | 模块依赖关系图谱 |
| **产品经理** | 搜索用户反馈、需求讨论 | 需求-功能-用户关联分析 |
| **销售 / 客户经理** | 搜索客户沟通记录 | 客户画像 + 关系网络 |
| **研究员 / 分析师** | 语义搜索文献笔记 | 人物-机构-事件关联发现 |
| **自由职业者** | 跨客户上下文切换 | 跨客户模式发现 |
| **团队 Leader** | 搜索团队讨论和决策 | 人→项目→资源组织图谱 |

---

## 技术栈

| 组件 | 技术 | 版本 |
|---|---|---|
| 向量数据库 | [Qdrant](https://qdrant.tech/) | latest |
| 图数据库 | [Neo4j](https://neo4j.com/) | 5.x |
| 知识图谱 | [Graphiti](https://github.com/getzep/graphiti) | latest |
| MCP 框架 | [FastMCP](https://github.com/jlowin/fastmcp) | via `mcp` package |
| Embedding | [阿里云 text-embedding-v4](https://help.aliyun.com/zh/model-studio/text-embedding) | 1024 维 |
| 笔记系统 | [Obsidian](https://obsidian.md/) + Local REST API | 可选 |
| 容器编排 | Docker Compose | - |
| 进程管理 | macOS launchd | - |

---

## License

MIT
