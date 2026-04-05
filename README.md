# Claude Code Memory System

为 Claude Code 构建的三合一永久记忆系统：**向量语义记忆 + 知识图谱 + 结构化笔记**。

## 架构

```
Claude Code
├── Qdrant V3（向量语义记忆）
│   ├── Embedding: 阿里云 text-embedding-v4，1024 维
│   ├── 自动去重（相似度 >0.92 跳过）
│   ├── 语义搜索 + 关键词搜索 + 融合搜索
│   └── MCP Server: server_v3.py（stdio 传输）
│
├── Graphiti + Neo4j（知识图谱记忆）
│   ├── 实体关系推理、历史演变追踪
│   ├── MCP Server: HTTP 传输（端口 18001）
│   └── 后端: Neo4j 5 + APOC 插件
│
├── Obsidian（结构化笔记）
│   ├── iCloud 同步
│   ├── 定时同步到 Qdrant + Graphiti（每 5 分钟）
│   └── REST API（端口 27124）
│
└── 双写规则
    └── 每次实质性回复 → 同时写入 Qdrant + Graphiti
```

## 目录结构

```
├── mcp-qdrant-memory/        # Qdrant MCP 服务端（核心）
│   ├── server_v3.py          # 主服务（store/search/hybrid_search 等）
│   ├── compact_v3.py         # 记忆压缩（按天合并旧对话）
│   ├── healthcheck.sh        # 15 项健康检查脚本
│   └── openclaw-plugin-v3/   # OpenClaw 飞书网关插件
│
├── graphiti-local/            # Graphiti MCP 本地服务
│   ├── mcp_server/           # MCP Server 源码
│   └── patches/              # 针对 graphiti_core 的中文优化补丁
│
├── memory-docker/             # Docker Compose 编排
│   └── docker-compose.yml    # Qdrant + Neo4j 容器
│
├── claude-config/             # Claude Code 配置参考
│   ├── docs/memory-system.md # 完整架构文档
│   └── scripts/              # Obsidian → Qdrant/Graphiti 同步脚本
│
├── launchagents/              # macOS LaunchAgent 守护进程模板
│   ├── com.claude.obsidian-sync-qdrant.plist
│   ├── com.graphiti.tunnel.plist
│   └── com.qdrant.ssh-tunnel.plist
│
└── bin/                       # 启动脚本
    ├── graphiti-tunnel.sh     # Graphiti MCP 进程启动
    └── qdrant-tunnel.sh       # Qdrant SSH 隧道（多机场景）
```

## 快速开始

### 前置要求

- macOS（LaunchAgent 为 macOS 专用，Linux 可改用 systemd）
- Docker Desktop
- Python 3.11+
- 阿里云 DashScope API Key（用于 text-embedding-v4）
- Obsidian + [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) 插件（可选）

### 1. 启动基础服务

```bash
# 克隆仓库
git clone https://github.com/hailanlan0577/claude-code-memory-system.git
cd claude-code-memory-system

# 启动 Qdrant + Neo4j
cd memory-docker
docker compose up -d
```

### 2. 配置环境变量

在 `~/.zshenv` 中添加：

```bash
export DASHSCOPE_API_KEY=your_dashscope_api_key
export OBSIDIAN_API_KEY=your_obsidian_api_key  # 可选，Obsidian 同步用
```

### 3. 安装 Qdrant MCP Server

```bash
cd mcp-qdrant-memory
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 注册到 Claude Code
claude mcp add qdrant-memory-v3 \
  -e DASHSCOPE_API_KEY \
  -- python3 /path/to/server_v3.py
```

### 4. 安装 Graphiti MCP Server

```bash
cd graphiti-local/mcp_server
python3.11 -m venv venv
source venv/bin/activate
pip install -e .

# 应用中文优化补丁
cd ../patches && bash apply-patches.sh

# 启动服务
python src/graphiti_mcp_server.py --transport http --port 18001

# 注册到 Claude Code
claude mcp add graphiti --transport http http://localhost:18001/mcp
```

### 5. 配置 Claude Code 双写规则

在你的项目 `CLAUDE.md` 中添加双写规则，让 Claude 每次回复后自动同时写入 Qdrant 和 Graphiti。参考 `claude-config/docs/memory-system.md` 第三节。

### 6.（可选）配置 Obsidian 同步

```bash
# 复制同步脚本
cp claude-config/scripts/obsidian-sync-qdrant.py ~/.claude/scripts/hooks/

# 配置 LaunchAgent（修改路径后）
cp launchagents/com.claude.obsidian-sync-qdrant.plist ~/Library/LaunchAgents/
# 编辑 plist 修改路径和 API Key
launchctl load ~/Library/LaunchAgents/com.claude.obsidian-sync-qdrant.plist
```

## 核心功能

### Qdrant MCP 工具

| 工具 | 功能 |
|------|------|
| `store_memory` | 存储记忆，自动去重 |
| `search_memory` | 语义搜索（向量 + 重要性加权 + 时间衰减） |
| `keyword_search` | 精确关键词搜索 |
| `hybrid_search` | 融合搜索（并行查询 Qdrant + Graphiti） |
| `delete_memory` | 精确/语义模糊删除 |
| `update_memory` | 原地更新记忆 |
| `compact_conversations` | 压缩旧对话，按天合并为摘要 |

### Graphiti 知识图谱

- `add_memory` — 写入知识图谱（自动提取实体和关系）
- `search_nodes` — 搜索实体节点
- `search_memory_facts` — 搜索关系事实

### 搜索策略

| 场景 | 推荐工具 |
|------|----------|
| 模糊/语义搜索 | `search_memory` |
| 精确关键词 | `keyword_search` |
| 实体关系/跨项目关联 | `hybrid_search` |
| 找不到时 | 两个都试试 |

## 健康检查

```bash
bash mcp-qdrant-memory/healthcheck.sh
```

检查 15 项：Docker 容器、Qdrant 连通、Collection 状态、Neo4j 连通、Graphiti MCP、Embedding API 等。

## 自定义

### 替换 Embedding 模型

在 `server_v3.py` 中修改 `get_embedding()` 函数。当前使用阿里云 text-embedding-v4（1024 维），你可以替换为：
- OpenAI text-embedding-3-small/large
- 其他兼容 REST API 的 embedding 服务

注意：更换 embedding 模型后需要重建 Qdrant collection 并重新导入数据。

### 多机部署

`bin/qdrant-tunnel.sh` 提供了通过 SSH 隧道跨机器访问 Qdrant 的方案，适合在多台机器间共享记忆。

## 许可

MIT
