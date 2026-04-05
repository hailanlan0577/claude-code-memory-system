# 记忆系统技术文档

> **重要**：对记忆系统任何配置做变更前，必须先阅读本文档。变更后必须同步更新本文档。

---

## 一、架构总览

> **2026-04-01 迁移**：从「双机共享」改为「双机独立」（Plan D + D2）。MacBook Pro 本地 Docker 运行 Qdrant + Neo4j，本地运行 Graphiti MCP。SSH 隧道仅保留 26333 端口用于按需搜索 Mac Mini OpenClaw 记忆。

```
MacBook Pro (Claude Code) — 独立记忆栈
│
├── Docker 容器（~/memory-docker/docker-compose.yml）
│   ├── Qdrant（localhost:6333）
│   │   └── collection: unified_memories_v3（text-embedding-v4，1024维，2204 points）
│   └── Neo4j 5（localhost:7474 / 7687）
│       └── password: YOUR_NEO4J_PASSWORD
│
├── Graphiti MCP Server（本地进程，launchd: com.graphiti.tunnel）
│   ├── 路径: ~/graphiti-local/mcp_server/
│   ├── 端口: 18001（HTTP transport）
│   └── 连接本地 Docker Neo4j（bolt://localhost:7687）
│
├── MCP 工具层（~/.claude.json）
│   ├── mcp__qdrant-memory-v3__*   ← 向量语义记忆（读/写）[stdio, 本机 Python]
│   │   ├── hybrid_search 内部调用 Graphiti（Streamable HTTP → localhost:18001/mcp）
│   │   └── search_openclaw_memory → SSH 隧道 localhost:26333（按需远程搜索）
│   └── mcp__graphiti__*           ← 知识图谱记忆（读/写）[HTTP → localhost:18001/mcp]
│
└── SSH 隧道（launchd: com.qdrant.ssh-tunnel）
    └── localhost:26333 → macmini:6333（仅供 search_openclaw_memory 使用）

Mac Mini (OpenClaw) — 独立记忆栈，不受 MacBook Pro 影响
│
├── Qdrant（port 6333，2540 points）
├── Neo4j + Graphiti MCP Server（port 8001）
└── OpenClaw Gateway（launchd: ai.openclaw.gateway）
```

---

## 二、各组件详情

### 2.1 Qdrant V3（向量语义记忆）

| 属性 | 值 |
|------|-----|
| 主机 | MacBook Pro 本地 Docker（localhost:6333） |
| Collection | `unified_memories_v3` |
| Embedding | 阿里云 text-embedding-v4，1024维 |
| MCP 工具前缀 | `mcp__qdrant-memory-v3__` |
| 访问方式 | 本地直连（不再需要 SSH 隧道） |
| Docker 数据卷 | `~/memory-docker/qdrant-data/` |

**主要工具**：
- `store_memory` — 存储（相似度 >0.92 自动去重）
- `search_memory` — 语义搜索
- `keyword_search` — 精确关键词搜索
- `hybrid_search` — 融合搜索（Qdrant + Graphiti 并行，见 2.5）
- `delete_memory` / `update_memory`

### 2.2 Graphiti（知识图谱记忆）

| 属性 | 值 |
|------|-----|
| 主机 | MacBook Pro 本地（localhost:18001） |
| Transport | **HTTP**（⚠️ 不能用 SSE，已废弃） |
| 配置文件 | `~/graphiti-local/mcp_server/.env`，`SERVER__TRANSPORT=http` |
| Neo4j | 本地 Docker（bolt://localhost:7687，neo4j/YOUR_NEO4J_PASSWORD） |
| group_id | `claude_code` |
| MCP 工具前缀 | `mcp__graphiti__` |
| 访问方式 | 本地直连 HTTP（不再需要 SSH 隧道） |
| 进程管理 | launchd: `com.graphiti.tunnel`（脚本: `~/bin/graphiti-tunnel.sh`） |

**启动方式**（launchd 自动管理）：
```bash
# 手动重启
launchctl kickstart -k gui/$(id -u)/com.graphiti.tunnel
# 查看日志
tail -f /tmp/graphiti-tunnel.log
```

**主要工具**：
- `add_memory` — 写入知识图谱
- `search_nodes` — 搜索实体节点
- `search_memory_facts` — 搜索关系事实

### 2.3 OpenClaw（飞书 AI 网关）

| 属性 | 值 |
|------|-----|
| 进程管理 | launchd，service: `ai.openclaw.gateway` |
| 二进制 | `/opt/homebrew/lib/node_modules/openclaw/dist/index.js` |
| 配置 | `~/.openclaw/openclaw.json` |
| 日志 | `~/.openclaw/logs/gateway.log` |

**重启命令**（在 Mac Mini 上）：
```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

**Hook 工作流**：
- `before_agent_start`：Qdrant recall（10条）+ Graphiti recall
- `agent_end`：Qdrant autoCapture + Graphiti autoCapture

### 2.5 hybrid_search 内部架构

`hybrid_search` 是 qdrant-memory-v3 MCP 服务器内的融合搜索工具，**内部**并行调用 Qdrant 和 Graphiti 两个系统。

**源码位置**：`/Users/YOUR_USERNAME/mcp-qdrant-memory/server_v3.py`

**调用链路**：
```
Claude Code 调用 hybrid_search（stdio → qdrant-memory-v3 MCP）
│
├── 线程1: search_qdrant()
│   └── 阿里云 text-embedding-v4 → Qdrant query_points
│
└── 线程2: search_graphiti_batch()
    └── call_graphiti_tools_batch()  ← 关键函数
        ├── POST /mcp → initialize（获取 Mcp-Session-Id）
        ├── POST /mcp → notifications/initialized
        ├── POST /mcp → tools/call: search_nodes
        └── POST /mcp → tools/call: search_memory_facts
```

**Graphiti 内部连接**：
| 属性 | 值 |
|------|-----|
| 协议 | **Streamable HTTP**（⚠️ 不是 SSE，见已知坑 #8） |
| URL | `http://localhost:18001/mcp`（本地 Graphiti MCP，不再经 SSH 隧道） |
| 会话管理 | `Mcp-Session-Id` header |
| 超时 | 单次请求 20 秒，线程 join 18 秒 |
| group_ids | `["claude_code"]`（仅搜本地 group，OpenClaw 记忆通过 search_openclaw_memory 独立搜索） |

**辅助函数**：
- `_post_mcp(client, payload, session_id)` — 发送 JSON-RPC 请求，自动处理 SSE/JSON 两种响应格式
- `_parse_sse_body(text)` — 从 SSE 格式响应体提取 JSON-RPC 消息
- `parse_graphiti_text(result)` — 将 Graphiti 返回的节点/事实格式化为可读文本

> **注意**：hybrid_search 内部对 Graphiti 的调用是独立的 HTTP 客户端连接，与 Claude Code 直接调用 `mcp__graphiti__*` 工具走的是**不同的通道**。前者是 server_v3.py 内部 httpx 直连，后者是 Claude Code 通过 `~/.claude.json` 注册的 MCP 服务。两者都必须使用 HTTP transport。

---

### 2.4 Claude Code MCP 配置

**⚠️ 重要：Claude Code 读取 MCP 配置的位置是 `~/.claude.json`，不是 `~/.claude/mcp.json`。**

通过 `claude mcp add` 命令注册的服务写入 `~/.claude.json`，Claude Code 启动时只从这里加载 MCP 工具。`~/.claude/mcp.json` 文件不会被 Claude Code 读取。

**Graphiti 注册命令**：
```bash
claude mcp add graphiti --transport http http://localhost:18001/mcp
```

注册后在 `~/.claude.json` 中的配置：
```json
{
  "projects": {
    "/Users/YOUR_USERNAME": {
      "mcpServers": {
        "graphiti": {
          "type": "http",
          "url": "http://localhost:18001/mcp"
        }
      }
    }
  }
}
```

> **2026-04-01 迁移后**：Graphiti 直接在本地运行（port 18001），不再经 SSH 隧道。`com.graphiti.tunnel` launchd 服务现在启动的是本地 Graphiti MCP 进程（`~/bin/graphiti-tunnel.sh`）。SSH 隧道仅保留 `com.qdrant.ssh-tunnel` 用于 `localhost:26333 → macmini:6333`（OpenClaw 远程搜索）。

---

## 三、双写规则（Claude Code 侧）

每次有实质性回复后，**必须同时**执行两步写入：

### 第一步：写入 Qdrant V3
```
mcp__qdrant-memory-v3__store_memory(
  content="[问] ...\n[答] ...\n[上下文] ...",
  category="conversation",  // 或 debug/decision/solution/feedback
  tags="日期,项目名,技术关键词"
)
```

### 第二步：写入 Graphiti
```
mcp__graphiti__add_memory(
  name="[YYYY-MM-DD] 主题摘要",
  episode_body="与 Qdrant content 相同",
  group_id="claude_code"
)
```

### 分类强制规则（每轮自检）

| 条件 | 额外存储 category |
|------|-----------------|
| 找到 bug 根因或修复方案 | `debug` |
| 用户纠正了我的行为/信息 | `feedback` |
| 做出架构/技术选型决策 | `decision` |
| 完成配置变更/功能实现 | `solution` |

### 不记录的情况
- 存储操作本身（防递归）
- 打招呼、闲聊、纯确认性回复
- 多轮工具调用中的中间过渡回复

---

## 四、记忆系统用途边界

| 用途 | 适合的系统 |
|------|-----------|
| Claude Code 会话记录 | ✅ Qdrant V3 + Graphiti |
| OpenClaw 飞书对话记录 | ✅ Qdrant V3 + Graphiti（OpenClaw 插件写） |
| 实体关系/历史演变查询 | ✅ Graphiti（图谱推理） |
| 精确库存查询 | ❌ 不适合向量记忆（会幻觉），用飞书 Bitable |

---

## 五、已知坑 & 修复历史

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 2026-03-26 | Graphiti `/mcp` 端点返回 404 | 使用了已废弃的 `--transport sse` | 改为 `--transport http`，更新 `.env` |
| 2026-03-26 | Claude Code 无法写入 Graphiti | mcp.json 未配置 Graphiti | 加入 SSH stdio 连接（需重启生效） |
| 2026-03-26 | Graphiti MCP 工具未加载（`mcp__graphiti__` 不在工具列表） | mcp.json 配的 `--transport stdio`，但进程实际跑 `--transport http --port 8001`，transport 不匹配导致启动时连接失败 | 改为 `streamableHttp` 直连 `http://macmini:8001/mcp` |
| 2026-03-26 | OpenClaw gateway 重启失败，`node: command not found` | launchctl 启动的进程 PATH 缺少 `/opt/homebrew/bin` | 重启命令加前缀 `env PATH=/opt/homebrew/bin:$PATH openclaw-gateway`，或在 launchd plist 加 `EnvironmentVariables PATH` |
| 2026-03-26 | Qdrant 中文语义搜索回忆率低 | 使用 all-MiniLM-L6-v2（384维），中文语义理解差，跨词汇搜索失败 | 升级到阿里云 text-embedding-v4（1024维），中文语义大幅提升 |
| 2026-03-26 | Qdrant 写入静默失败（不报错但数据没进去） | JS 客户端写入时 vector 维度与 collection 创建维度不一致 | 排查时检查 collection 配置确认 vector size，与实际 embedding 维度对比 |
| 2026-03-26 | Graphiti MCP 工具始终不出现（`mcp__graphiti__` 缺失） | mcp.json 写了 `http://macmini:8001/mcp`，但 `macmini` 主机名只走 SSH/cloudflared 隧道，普通 HTTP 无法解析，连接直接超时 | 本机已有 launchd 服务 `com.graphiti.tunnel` 将 `localhost:18001` → `macmini:8001`，改 mcp.json 为 `http://localhost:18001/mcp` 即可 |
| 2026-03-26 | Graphiti MCP 工具仍然不出现，服务正常但工具未注册 | **Claude Code 不读 `~/.claude/mcp.json`**，只读 `~/.claude.json`。Graphiti 配置写错了文件 | 用 `claude mcp add graphiti --transport http http://localhost:18001/mcp` 注册到 `~/.claude.json`，重启 Claude Code 生效 |
| 2026-03-26 | `hybrid_search` 中 Graphiti 始终返回"无结果或超时" | `server_v3.py` 的 `call_graphiti_tools_batch` 用 SSE 协议（`GET /sse`）连接 Graphiti，但 Graphiti 服务器运行的是 `--transport http`，SSE 端点不存在 | 重写 `call_graphiti_tools_batch` 为 Streamable HTTP 协议（`POST /mcp` + `Mcp-Session-Id`），移除 SSE 监听线程和 queue 依赖 |
| 2026-03-26 | OpenClaw Qdrant V3 autoCapture 静默跳过所有飞书对话 | `agent_end` 钩子中 `userText` 包含 `<your-memories>` 和 `<graphiti-knowledge>` 回忆注入块（占 93% 内容），导致所有对话 embedding 高度相似，超过 DEDUP_THRESHOLD（0.92）被误判为重复 | 在 `~/.openclaw/extensions/openclaw-memory-qdrant-v3/index.js` autoCapture 构造 `combined` 前，用 `stripInjectedTags()` 剥离 `<your-memories>` 和 `<graphiti-knowledge>` 标签及其内容，使 embedding 只反映实际用户对话。修复后 dedup 分数从 ~0.95 降至 ~0.77 |
| 2026-03-30 | Claude Code 侧 6 个 API Key 明文存储在 `~/.claude.json` | MCP 服务的 `env` 字段直接写入密钥值 | 密钥迁移到 `~/.zshenv`，MCP 子进程通过环境变量继承获取，`~/.claude.json` 的 env 字段清空 |
| 2026-03-30 | 全局 `mcpServers.graphiti` 用废弃的 SSE 协议 | 早期配置残留 `"type": "sse"` | 改为 `"type": "http"`，URL 改为 `/mcp` |
| 2026-03-30 | `get_embedding()` 无超时和重试 | httpx 默认 30s 超时，无重试逻辑 | 改为 10s 超时 + 指数退避重试（最多 2 次，1s→2s），失败抛 RuntimeError |
| 2026-03-30 | 全局和项目级 GitHub MCP 重复（不同 token） | 分别通过不同方式添加 | 删除全局重复项，保留项目级 `github-mcp-server` |
| 2026-03-30 | 4 个冗余 MCP 服务占资源 | fetch/memory/puppeteer/sqlite 已被其他服务替代或指向不存在的文件 | 全部删除，MCP 从 17 个降到 13 个 |
| 2026-04-01 | 记忆系统迁移：双机共享→双机独立（Plan D + D2） | SSH 隧道不稳定（Neo4j 崩溃、VPN 断连等）是反复痛点 | MacBook Pro 本地 Docker 运行 Qdrant + Neo4j，本地运行 Graphiti MCP，SSH 隧道仅保留 26333 端口做 OpenClaw 远程搜索。数据迁移 2200 条 claude_code 记忆到本地 |

---

## 六、存档与恢复

两侧均有独立的存档/恢复机制，出问题时可一键回滚。

### 6.1 Claude Code 侧

| 项目 | 值 |
|------|-----|
| MCP 服务代码 | `/Users/YOUR_USERNAME/mcp-qdrant-memory`（git 仓库） |
| Docker 配置 | `~/memory-docker/docker-compose.yml` |
| Qdrant 数据 | `~/memory-docker/qdrant-data/` |
| Neo4j 数据 | `~/memory-docker/neo4j-data/` |
| Graphiti MCP | `~/graphiti-local/mcp_server/` |
| 诊断脚本 | `~/mcp-qdrant-memory/healthcheck.sh`（15项检查） |
| 迁移前备份 | `~/memory-system-backup/macbookpro-pre-migration-20260401/` |

```bash
# Docker 容器管理
cd ~/memory-docker && docker compose up -d    # 启动
cd ~/memory-docker && docker compose down      # 停止

# Graphiti MCP 管理（launchd）
launchctl kickstart -k gui/$(id -u)/com.graphiti.tunnel  # 重启

# SSH 隧道管理（launchd）
launchctl kickstart -k gui/$(id -u)/com.qdrant.ssh-tunnel  # 重启
```

### 6.2 Mac Mini OpenClaw 侧（快照备份）

| 项目 | 值 |
|------|-----|
| 脚本路径 | `~/openclaw-snapshots/save_restore.sh` |
| 快照目录 | `~/openclaw-snapshots/` |
| 备份内容 | qdrant-v3 插件、graphiti 插件、openclaw.json |

```bash
# 在 Mac Mini 上操作（或 ssh macmini）
~/openclaw-snapshots/save_restore.sh list      # 列出快照
~/openclaw-snapshots/save_restore.sh check     # 7项健康检查
~/openclaw-snapshots/save_restore.sh save "说明"    # 创建快照
~/openclaw-snapshots/save_restore.sh restore <名称>  # 恢复（自动先备份当前状态）
```

健康检查项：Gateway 进程、Qdrant 连通、Collection 状态、Graphiti MCP、stripInjectedTags 补丁、飞书 WebSocket、阿里云 Embedding API。

### 6.3 OpenClaw Qdrant V3 插件关键补丁

文件：`~/.openclaw/extensions/openclaw-memory-qdrant-v3/index.js`（Mac Mini）

**autoCapture `stripInjectedTags` 补丁**（约第1226行）：

autoRecall 会在 `before_agent_start` 将 `<your-memories>` 和 `<graphiti-knowledge>` 标签注入 userText。这些注入块跨对话几乎相同（占 userText 93%），导致 embedding 相似度始终 >0.92，触发 `DEDUP_THRESHOLD` 误判为重复。

补丁在构造 `combined` 文本前剥离这些标签：
```javascript
const stripInjectedTags = (t) => t
  .replace(/<your-memories>[\s\S]*?<\/your-memories>/g, '')
  .replace(/<graphiti-knowledge>[\s\S]*?<\/graphiti-knowledge>/g, '')
  .replace(/\s+/g, ' ').trim();
const cleanUserText = stripInjectedTags(userText);
const cleanAssistantText = stripInjectedTags(assistantText);
```

> **注意**：此补丁未进 git，仅存在于 Mac Mini 本地文件和快照备份中。恢复时务必使用包含此补丁的快照（`20260326_213908_e2e-full-pipeline-verified` 或更新）。

---

## 七、变更流程

1. **变更前**：阅读本文档，确认影响范围
2. **变更时**：最小化改动，验证连通性
3. **变更后**：
   - 更新本文档对应章节
   - 存一条 `decision` 或 `solution` 记忆到 Qdrant + Graphiti
   - 如影响 OpenClaw，重启 gateway 并查看日志确认

> **禁止**：未经验证直接修改 mcp.json、openclaw.json、Graphiti .env 后不更新本文档。
