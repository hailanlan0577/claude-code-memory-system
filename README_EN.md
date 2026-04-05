# Claude Code Memory System

[中文](./README.md) | **English**

**Give Claude Code a permanent memory.**

A 3-in-1 memory system: Qdrant vector semantic search + Graphiti knowledge graph reasoning + Obsidian note auto-sync. Persistent cross-session memory so conversations never start from scratch.

---

## Real-World Use Cases

Without a memory system, every conversation with Claude Code starts on a blank slate. With it, Claude becomes a long-term partner that "remembers everything." Here are typical scenarios from actual daily work:

### Scenario 1: Cross-Session Debugging — "How did we fix that bug last time?"

**Without memory**:

> You: Qdrant connection timed out, getting a 408 error
>
> Claude: Please check your network connection, whether the port is open, firewall settings... *(generic suggestions)*

**With memory**:

> You: Qdrant connection timed out, getting a 408 error
>
> Claude: *(auto-retrieves debug memory from March 31)* You've hit this exact issue before. The root cause was httpx defaulting to the system proxy when connecting to local Qdrant. The fix is adding `os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")` at the top of the code. Want me to add it for you?

**The difference**: From "guessing" to "remembering." Debug memories are tagged as high importance with 1.3x search weight, ensuring they surface first.

### Scenario 2: Architecture Decision Traceability — "Why did we choose this?"

Midway through development, you or a teammate questions a technical decision:

> You: Why are we using Alibaba Cloud's embedding instead of OpenAI's?

**Without memory**: Claude can only give a generic pros/cons comparison.

**With memory**:

> Claude: *(retrieves decision memory from March 26)* You made this decision on March 26. The reasons were:
> 1. all-MiniLM-L6-v2 had poor Chinese semantic understanding, failing cross-vocabulary searches
> 2. OpenAI embedding requires a VPN, with unstable latency
> 3. text-embedding-v4 supports 8192 tokens (up from 512), with dramatically better Chinese performance
>
> You also compared BGE-M3 but chose text-embedding-v4 because the Alibaba Cloud API was more stable.

**The difference**: Not just "what was chosen" but also "why" and "what was rejected." Three months later, no need to dig through chat logs.

### Scenario 3: Seamless Project Context Switching — "Where did we leave off?"

You maintain multiple projects simultaneously. The most painful part of switching is rebuilding context:

> You: Let's continue the Chinese chess project

**Without memory**: Claude only knows what files are in the directory — nothing about your progress, pitfalls encountered, or next steps.

**With memory**:

> Claude: *(retrieves project and solution memories)* Last time you finished the piece movement logic and check detection, but there's still a bug in the "horse leg" rule — the horse can still jump when its path is blocked. Your plan was to add an `isBlocked()` check in `canMove()`. Also, the capture animation hasn't been done yet — you said you wanted to use Framer Motion. Which one do you want to pick up?

**The difference**: Not starting from scratch reading code, but picking up right where your thought process left off.

### Scenario 4: Automatic Repeat Issue Filtering — "Have I asked this before?"

During development you often hit the same pitfall repeatedly:

> You: Claude Code MCP tools aren't loading, Graphiti's tool list is empty

**Without memory**: Claude has you check config files, restart services... you try everything and nothing works.

**With memory**:

> Claude: *(retrieves debug memory from March 26 — this trap has been hit 3 times)* You've encountered this before. The root cause is that **Claude Code only reads `~/.claude.json`, not `~/.claude/mcp.json`**. You need to register using `claude mcp add graphiti --transport http http://localhost:18001/mcp`. Last time you also discovered the transport must be `http`, not `sse` — watch out for that too.

**The difference**: Never fall into the same trap twice. Debug memories record the symptoms, root cause, and fix — delivering the complete solution directly.

### Scenario 5: Knowledge Graph Association Discovery — "How are these things related?"

Qdrant vector search finds "similar content," but Graphiti discovers "hidden connections":

> You: Which modules have changed recently? Are they related?

**Qdrant only**: Lists recent changes, but can't see dependencies between modules.

**With Graphiti**:

> Claude: *(hybrid_search queries both Qdrant + Graphiti)* Three modules changed recently:
> - `hybrid_search` function in `server_v3.py`
> - Qdrant write logic in `session-to-obsidian.py`
> - LaunchAgent environment variable config
>
> The Graphiti graph shows they're connected: `hybrid_search` depends on the Graphiti MCP (HTTP protocol), and the LaunchAgent is responsible for starting the Graphiti process. Last time, changing the Python path in LaunchAgent caused Graphiti not to start, which made all hybrid_search calls timeout. These three changes are likely on the same causal chain.

**The difference**: From "listing items" to "telling the story," understanding cause-and-effect between modules.

### Scenario 6: Low-Cost Obsidian Recall — "What did that design doc say?"

Claude previously wrote a 5,000-word design document stored in Obsidian:

> You: In that AI buyer scoring system design, what were the scoring dimensions?

**Without vectorization**: Reading the original via Obsidian MCP costs 8,000+ tokens and takes several seconds to load.

**With vectorization (Obsidian synced to Qdrant)**:

> Claude: *(search_memory hits the vectorized Obsidian content, ~300 tokens)* The scoring dimensions include:
> 1. Condition score (wear, scratches, oxidation)
> 2. Price reasonableness score (compared to historical transaction prices)
> 3. Market heat score (brand x model x color circulation speed)
> 4. Profit margin score (estimated selling price - purchase price - maintenance cost)

**The difference**: Same information, token consumption drops from 8,000 to 300 — over 10x faster. Ask 20 times a day and the token savings add up significantly.

### Scenario 7: Long-Term Trend Analysis — "What patterns are there over these months?"

Once memories accumulate, you can do retrospective analysis:

> You: Summarize what I've mainly been doing with Claude Code over the last three months

> Claude: *(search_memory + keyword_search with date range)*
> - **January**: Mainly working on the Chinese Chess React project — completed board rendering and basic movement rules
> - **February**: Shifted to the second-hand luxury bag inventory management app — Flutter + Supabase, completed product entry and photo features
> - **March**: Spent significant time building the memory system — migrated from Pinecone to Qdrant, integrated Graphiti, upgraded embedding from a small model to text-embedding-v4, resolved a dozen connectivity bugs
> - **Throughout**: Obsidian note system gradually established, session auto-archiving went from manual to fully automated
>
> Tech preference shift: From JavaScript to Python backend + Flutter frontend combo.

**The difference**: You might have forgotten what you were doing three months ago, but the memory system preserves your complete work trajectory.

### Scenario 8: New Project Cold Start — "Help me set up a new project"

> You: Help me set up a Next.js project

**Without memory**: Claude gives you a standard template.

**With memory**:

> Claude: *(retrieves preference memories)* Based on your previous preferences:
> - You prefer TypeScript strict mode
> - State management: Zustand over Redux
> - Styling: Tailwind CSS
> - You dislike the default ESLint config being too loose — last time you manually added `@typescript-eslint/strict`
> - Test framework: Vitest
>
> I'll initialize with these preferences. Sound good?

**The difference**: Claude becomes a partner who knows your coding habits — no need to repeat "I want TypeScript" and "I use Tailwind" every time.

---

## With Memory vs Without

| | No Memory System | Qdrant Only | Qdrant + Graphiti + Obsidian |
|---|---|---|---|
| **Cross-session** | Everything forgotten when you close the window | Every Q&A auto-stored as vectors, permanently | Same |
| **Search** | Only `MEMORY.md` (200 handwritten lines) | Semantic search — search "bag management" finds "inventory module" | Same + exact keyword search |
| **Knowledge reasoning** | Can't answer "who owns this module" | **Can't do it** — only text similarity, no entity understanding | Graphiti auto-extracts entities and relationships |
| **Note integration** | Obsidian notes disconnected from Claude | Manual copy-paste | Auto-sync Obsidian → vector DB every 5 min |
| **Search strategies** | `grep` | Semantic search (one method) | Semantic + keyword + graph fusion search |

**In one sentence: Qdrant helps you "find," Graphiti helps you "understand," Obsidian helps you "accumulate."**

---

## Core Mechanisms

### 1. Auto Memory: Sessions auto-archived to vector DB on close

Claude Code has no built-in cross-session memory — close the terminal, everything resets. This system solves it with **Hook-based auto-archiving**:

```
Session A (a complete conversation with Claude)
  │
  ├── You close the window / start a new session
  │
  └── SessionEnd Hook auto-triggers:
      └── session-to-obsidian.py reads Session A's full conversation
          │
          ├── ① Write to Obsidian — full Markdown archive (structured notes)
          ├── ② Write to Qdrant  — each Q&A round vectorized (semantically searchable)
          └── ③ Write to Graphiti — session summary with entity/relationship extraction (graph reasoning)

Session B (new window)
  │
  ├── SessionStart Hook auto-triggers:
  │   └── Scans unarchived past sessions, retries failed items (3 retries + pending staging)
  │
  └── When you ask a question, Claude auto-calls search_memory
      → Recalls memories from Session A and earlier, weaving them into answers
```

**The entire process is fully automatic.** Just use Claude Code normally — the moment you close the window, the previous session's content is archived to all three systems. Next time you open a new window, historical memories are automatically available.

**Reliability design**: The three targets (Obsidian / Qdrant / Graphiti) are independent and non-blocking — if one fails, it doesn't affect the others. Failed items are staged in a pending directory and auto-retried on the next session start.

This means:
- A bug you debugged last week — ask "how did we fix that Redis timeout last time" and Claude gives you the answer directly
- An architecture decision from three months ago — ask "why did we pick PostgreSQL over MongoDB" and the reasoning surfaces automatically
- Each Q&A round is stored by category (debug/decision/solution/feedback...), important memories get boosted, casual chat gets downweighted

### 2. Obsidian Backflow: Notes become low-cost memories

As mentioned above, session content auto-writes to Obsidian when you close the window. Beyond that, Claude Code also writes various documents to Obsidian during work — design proposals, retrospectives, architecture diagrams, TODO lists, etc.

These documents accumulate in the Obsidian vault as a great knowledge base. But the problem is **reading them costs Claude Code a lot**:

| Read Method | Token Cost | Speed |
|---|---|---|
| Via Obsidian MCP (full text) | **Thousands to tens of thousands of tokens** (depends on doc length) | Slow (full text loaded into context) |
| Via Qdrant vector search | **A few hundred tokens** (only relevant fragments returned) | Fast (millisecond-level semantic matching) |

**This is the core value of the Obsidian sync script** — it vectorizes Obsidian documents into Qdrant, letting Claude Code recall knowledge at minimal token cost:

```
Complete memory loop:

Claude Code session
  │
  ├── Close window → SessionEnd Hook
  │   ├── Full conversation → Obsidian (Markdown archive)
  │   ├── Each Q&A round → Qdrant (vector memory)
  │   └── Session summary → Graphiti (knowledge graph)
  │
  ├── During work → Claude writes to Obsidian
  │   └── Design docs, retrospectives, comparisons, etc.
  │
  └── obsidian-sync-qdrant.py (auto-runs every 5 minutes)
      ├── Scans all .md files via Obsidian REST API
      ├── Content hash change detection (only processes new/modified)
      ├── Auto-chunks long documents
      ├── text-embedding-v4 vectorization → writes to Qdrant
      └── Entity extraction → writes to Graphiti
          │
          └── Result: next time you ask in a new session
              └── search_memory can find everything in Obsidian
                  → No need to open files or read full text
                  → Only semantically relevant fragments returned
                  → Token consumption reduced by 90%+
```

**Key insight**: Obsidian serves as the **accumulation layer** in this system, not the source of information. The source is Claude Code conversations. Session archives and work documents flow into Obsidian, and the sync script flows them back into the vector DB, creating a **write → accumulate → low-cost recall** loop. Compared to reading the original text from Obsidian every time, vector search saves over 90% of tokens.

---

## Architecture

```
Claude Code
│
├── MCP: qdrant-memory-v3 (stdio)          ← Vector semantic memory
│   ├── store_memory      Store (auto-dedup)
│   ├── search_memory     Semantic search (weighted + time decay + dedup)
│   ├── keyword_search    Exact keyword search
│   ├── hybrid_search     Fusion search (Qdrant + Graphiti in parallel)
│   ├── delete_memory     Exact/fuzzy delete
│   ├── update_memory     In-place update
│   ├── compact_conversations  Compress old conversations by day
│   └── memory_stats      Statistics
│
├── MCP: graphiti (HTTP)                   ← Knowledge graph
│   ├── add_memory         Write (auto entity/relationship extraction)
│   ├── search_nodes       Search entity nodes
│   └── search_memory_facts Search relationship facts
│
└── Dual-write rule: every reply → writes to both Qdrant + Graphiti
│
│   ┌─────────────────────────────────────────────┐
│   │  hybrid_search internals:                    │
│   │  Thread 1: Qdrant vector search              │
│   │  Thread 2: Graphiti Streamable HTTP graph     │
│   │  → Results merged, deduped, unified return    │
│   └─────────────────────────────────────────────┘
│
├── Docker
│   ├── Qdrant     (localhost:6333)   Vector database
│   └── Neo4j 5    (localhost:7687)   Graph database (Graphiti backend)
│
└── Obsidian Auto-Sync (LaunchAgent, every 5 min)
    └── obsidian-sync-qdrant.py
        ├── Read notes via Obsidian REST API
        ├── Generate vectors with text-embedding-v4
        ├── Write to Qdrant (incremental, content hash change detection)
        └── Write to Graphiti (entity extraction)
```

### Qdrant vs Graphiti: Their Respective Roles

| | Qdrant Vector DB | Graphiti Knowledge Graph |
|---|---|---|
| **Stores** | Vector encodings of full text | Entities, relationships, and facts extracted from text |
| **Searches by** | Vector cosine similarity (semantic) | Graph traversal (entity relationship queries) |
| **Good at** | "Finding similar content" (fuzzy matching) | "Finding connected things" (precise reasoning) |
| **Example** | Search "returns" → finds all return-related conversations | Search "Zhang" → discovers he's a supplier, what he supplied |
| **Weakness** | Doesn't understand entity relationships | Not good at fuzzy semantic matching |
| **Backend** | Qdrant (port 6333) | Neo4j (port 7687) |

**`hybrid_search` queries both in parallel and returns unified results**, compensating for each other's weaknesses.

---

## Directory Structure

```
├── mcp-qdrant-memory/             # Core: Qdrant MCP server
│   ├── server_v3.py               #   Main server (9 MCP tools)
│   ├── compact_v3.py              #   Memory compaction (merge old conversations by day)
│   ├── healthcheck.sh             #   15-item diagnostic script
│   ├── requirements.txt           #   Python dependencies
│   ├── migrate_to_v3.py           #   Migrate data from v2
│   ├── backfill_importance.py     #   Backfill importance field
│   ├── capacity_alert.py          #   Capacity alerts
│   └── openclaw-plugin-v3/        #   OpenClaw gateway plugin
│
├── graphiti-local/                # Graphiti MCP local server
│   ├── mcp_server/                #   MCP Server source code
│   │   ├── src/graphiti_mcp_server.py  #   Main entry point
│   │   ├── config/                #   Config templates
│   │   ├── pyproject.toml         #   Dependency definitions
│   │   └── tests/                 #   Tests
│   └── patches/                   #   Chinese optimization patches (dedup/extraction prompts)
│
├── memory-docker/                 # Docker orchestration
│   ├── docker-compose.yml         #   Qdrant + Neo4j one-click start
│   ├── migrate_qdrant.py          #   Qdrant data migration
│   └── migrate_graphiti.py        #   Graphiti data migration
│
├── claude-config/                 # Claude Code config reference
│   ├── docs/memory-system.md      #   Full architecture doc (known issues & fix history)
│   └── scripts/                   #   Obsidian sync scripts
│       └── obsidian-sync-qdrant.py  # Obsidian → Qdrant + Graphiti
│
├── launchagents/                  # macOS LaunchAgent templates
│   ├── com.claude.obsidian-sync-qdrant.plist  # Obsidian sync daemon
│   ├── com.graphiti.tunnel.plist              # Graphiti service process
│   └── com.qdrant.ssh-tunnel.plist            # SSH tunnel (multi-machine)
│
└── bin/                           # Startup scripts
    ├── graphiti-tunnel.sh         #   Graphiti MCP process launcher
    └── qdrant-tunnel.sh           #   Qdrant SSH tunnel
```

---

## Quick Start

### Prerequisites

| Dependency | Purpose | Install |
|------|------|------|
| Docker Desktop | Run Qdrant + Neo4j | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Python 3.11+ | Run MCP Server | `brew install python@3.11` |
| Claude Code CLI | AI coding assistant | [claude.ai/code](https://claude.ai/code) |
| Alibaba Cloud DashScope API Key | text-embedding-v4 vectorization | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) |
| Obsidian + Local REST API plugin | (Optional) Note sync | [obsidian.md](https://obsidian.md/) |

> **About the Embedding Model**: This project defaults to Alibaba Cloud text-embedding-v4 (1024 dimensions, 8192 tokens, excellent Chinese performance). You can replace it with OpenAI text-embedding-3-small or any other REST API-compatible embedding service — just modify the `get_embedding()` function in `server_v3.py`.

### Step 1: Start Docker Containers

```bash
git clone https://github.com/hailanlan0577/claude-code-memory-system.git
cd claude-code-memory-system/memory-docker

# Edit Neo4j password (NEO4J_AUTH in docker-compose.yml)
docker compose up -d
```

Verify after starting:

```bash
# Qdrant should return {"title":"qdrant - vector search engine",...}
curl http://localhost:6333

# Neo4j browser at http://localhost:7474
```

### Step 2: Configure Environment Variables

Add to `~/.zshenv` (or `~/.bashrc`):

```bash
# Required: Alibaba Cloud Embedding API
export DASHSCOPE_API_KEY=your_dashscope_api_key

# Optional: Obsidian REST API (only needed for sync feature)
export OBSIDIAN_API_KEY=your_obsidian_api_key
```

Reload: `source ~/.zshenv`

### Step 3: Install Qdrant MCP Server

```bash
cd mcp-qdrant-memory
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Register with Claude Code:

```bash
claude mcp add qdrant-memory-v3 \
  -e DASHSCOPE_API_KEY \
  -- /path/to/mcp-qdrant-memory/venv/bin/python \
  /path/to/mcp-qdrant-memory/server_v3.py
```

### Step 4: Install Graphiti MCP Server

```bash
cd graphiti-local/mcp_server
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
```

Configure the `.env` file:

```bash
cp .env.example .env
# Edit .env, fill in Neo4j password and OpenAI/other LLM API Key
# Graphiti needs an LLM for entity and relationship extraction
```

Apply Chinese optimization patches (optional, improves Chinese entity extraction quality):

```bash
cd ../patches
bash apply-patches.sh
```

Start the Graphiti service:

```bash
cd ../mcp_server
venv/bin/python src/graphiti_mcp_server.py --transport http --port 18001
```

Register with Claude Code:

```bash
claude mcp add graphiti --transport http http://localhost:18001/mcp
```

### Step 5: Verify Installation

```bash
# Health check (15-item diagnostic)
bash mcp-qdrant-memory/healthcheck.sh
```

Restart Claude Code and test in a conversation:

```
> Remember: I prefer Python for backend and React for frontend

# Claude should auto-call store_memory to save this preference
# Future conversations will auto-recall it when searching related memories
```

### Step 6: Configure Dual-Write Rules (Recommended)

Add the following rules to your project's `CLAUDE.md` so Claude automatically writes to both systems after every substantive reply:

```markdown
## Auto Conversation Recording

After every reply, execute both:

### Write to Qdrant
Call `mcp__qdrant-memory-v3__store_memory`:
- content: "[Q] Question summary\n[A] Answer summary\n[Context] Project/tech stack"
- category: conversation (or debug/decision/solution/feedback)
- tags: "date,project-name,tech-keywords"

### Write to Graphiti
Call `mcp__graphiti__add_memory`:
- name: "[YYYY-MM-DD] One-line topic summary"
- episode_body: Same as Qdrant content
- group_id: "claude_code"
```

For the complete dual-write rule template and category self-check workflow, see Section 3 of `claude-config/docs/memory-system.md`.

### Step 7: Obsidian Auto-Sync (Optional)

If you use Obsidian for notes, configure auto-sync to continuously sync note content to Qdrant + Graphiti:

1. Install the Obsidian plugin [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) and generate an API Key
2. Copy the sync script:

```bash
mkdir -p ~/.claude/scripts/hooks
cp claude-config/scripts/obsidian-sync-qdrant.py ~/.claude/scripts/hooks/
```

3. Configure the LaunchAgent daemon (macOS):

```bash
# Edit the plist, modify script path and API Key
cp launchagents/com.claude.obsidian-sync-qdrant.plist ~/Library/LaunchAgents/
# Load after editing
launchctl load ~/Library/LaunchAgents/com.claude.obsidian-sync-qdrant.plist
```

The sync script reads notes via the Obsidian REST API every 5 minutes, incrementally (based on content hash change detection), and auto-chunks long documents.

---

## Search Tools Reference

### 9 MCP Tools at a Glance

| Tool | Purpose | Features |
|------|------|------|
| `store_memory` | Store memories | Auto-dedup (similarity >0.92 = skip), auto importance grading |
| `search_memory` | Semantic search | Vector similarity + importance weighting + time decay + result dedup |
| `keyword_search` | Keyword search | Exact match on content and tags, supports date search |
| `hybrid_search` | Fusion search | **Parallel query: Qdrant vectors + Graphiti graph, unified return** |
| `delete_memory` | Delete memories | Supports exact content delete and fuzzy semantic delete |
| `update_memory` | Update memories | In-place update, preserves original ID and creation time |
| `list_memories` | Browse memories | List all memories by category |
| `compact_conversations` | Compress conversations | Merge old conversation memories into daily summaries |
| `memory_stats` | Statistics | Per-category counts, 60s TTL cache |

### Search Strategy Guide

| What you want to do | Which tool | Why |
|---|---|---|
| Fuzzy search ("return-related issues") | `search_memory` | Vector semantic understanding, no exact word match needed |
| Exact search ("PR200156", "2026-03-19") | `keyword_search` | Exact text matching, nothing missed |
| Entity relationships ("what's Zhang's relationship with us") | `hybrid_search` | Graphiti graph reasons about entity relationships |
| Cross-project associations ("which projects use Redis") | `hybrid_search` | Graphiti relationship traversal |
| Can't find anything | Try both | Vector and keyword complement each other |

### Importance Weighting Mechanism

Memories are auto-graded by category, weighted during search:

| Importance | Weight | Categories |
|---|---|---|
| **high** (★) | 1.3x | project, architecture, solution, preference, debug, feedback, decision, summary |
| **medium** (☆) | 1.0x | fact, general, conversation |
| **low** (·) | 0.7x | other |

Search results also apply **time decay**: last 7 days 1.2x, 7-30 days 1.0x, 1-3 months 0.9x, 3-12 months 0.8x, over 1 year 0.7x.

### hybrid_search Internal Workflow

```
Call hybrid_search(query="Zhang's supply records")
│
├── Thread 1: Qdrant vector search
│   └── text-embedding-v4 → cosine similarity → top N
│
└── Thread 2: Graphiti graph search (Streamable HTTP)
    ├── POST /mcp → initialize (get Mcp-Session-Id)
    ├── POST /mcp → tools/call: search_nodes
    └── POST /mcp → tools/call: search_memory_facts
│
└── Merge results → Deduplicate → Weighted sort → Return
```

---

## Memory Category System

| Category | When to use | Example |
|---|---|---|
| `conversation` | Daily conversation records (auto dual-write) | "[Q] How to configure Redis [A] Recommend using docker..." |
| `project` | Key project information | "luxury-bag-inventory uses Flutter + Supabase" |
| `architecture` | Architecture decisions | "Memory system changed from shared-machine to independent-machine" |
| `decision` | Technical choices | "Chose text-embedding-v4 over OpenAI embedding" |
| `solution` | Problem solutions | "Neo4j dump requires stopping the DB first, use APOC stream export instead" |
| `debug` | Bug debugging experience | "Graphiti 404 root cause: used deprecated SSE transport" |
| `feedback` | User behavior corrections | "Don't mock the database in tests" |
| `preference` | User preferences | "User prefers Python backend + React frontend" |
| `summary` | Compressed summaries | Generated by compact_conversations |
| `general` | General information | Doesn't fit any above category |

---

## Advanced Configuration

### Replacing the Embedding Model

Modify the `get_embedding()` function in `server_v3.py`. For example, switching to OpenAI:

```python
EMBEDDING_API_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_DIM = 1536  # or 1024/512

def get_embedding(text: str, text_type: str = "document") -> list[float]:
    resp = _http_client.post(
        EMBEDDING_API_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", ...},
        json={"model": EMBEDDING_MODEL, "input": text, "dimensions": VECTOR_DIM},
    )
    return resp.json()["data"][0]["embedding"]
```

> **Note**: After changing the embedding model, you need to rebuild the Qdrant collection and re-import all data (due to dimension changes).

### Multi-Machine Deployment

`bin/qdrant-tunnel.sh` provides an SSH tunnel solution for cross-machine Qdrant access:

```bash
# MacBook Pro → Mac Mini's Qdrant
ssh -fNL 26333:localhost:6333 macmini

# search_openclaw_memory in server_v3.py accesses remote memories through this tunnel
```

Suitable for sharing memories across machines or deploying the database on a server.

### Daemon Processes (macOS LaunchAgent)

The `launchagents/` directory provides three daemon templates:

| File | Function | Frequency |
|------|------|------|
| `com.graphiti.tunnel.plist` | Graphiti MCP process keep-alive | KeepAlive |
| `com.qdrant.ssh-tunnel.plist` | SSH tunnel keep-alive | KeepAlive |
| `com.claude.obsidian-sync-qdrant.plist` | Obsidian sync | Every 5 min |

After modifying paths and API Keys:

```bash
cp launchagents/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.graphiti.tunnel.plist
```

Linux users can adapt the plist configs into systemd services.

---

## Health Check

```bash
bash mcp-qdrant-memory/healthcheck.sh        # Diagnose
bash mcp-qdrant-memory/healthcheck.sh --fix   # Auto-fix
```

Checks 15 items:

1. Qdrant container connectivity
2. Neo4j / Graphiti connectivity
3. Graphiti MCP Server (HTTP transport)
4. Claude Code MCP registration status
5. `server_v3.py` code integrity (Streamable HTTP vs deprecated SSE)
6. Qdrant data readability
7. Graphiti `search_nodes` end-to-end test
8. Total memory count and conversation ratio (>60% suggests running compact)
9. DashScope Embedding API availability
10. Backup freshness
11. Technical documentation completeness

---

## Known Issues & Pitfall Guide

These are pitfalls we've encountered — saving you from repeating them:

| Pitfall | Root Cause | Correct Approach |
|---|---|---|
| Graphiti MCP tools don't appear | Claude Code only reads `~/.claude.json`, not `~/.claude/mcp.json` | Register using `claude mcp add` command |
| Graphiti returns 404 | Used deprecated `--transport sse` | Must use `--transport http` |
| `hybrid_search` Graphiti always times out | Code uses SSE protocol (`GET /sse`) to connect to HTTP service | Use Streamable HTTP (`POST /mcp` + `Mcp-Session-Id`) |
| Neo4j dump requires stopping the DB | `neo4j-admin database dump` doesn't support online export | Use `CALL apoc.export.json.all(null, {stream:true})` |
| Poor Chinese semantic search | Small model (all-MiniLM-L6-v2) weak at Chinese | Switch to large-model-level embedding (text-embedding-v4) |
| Plaintext secrets in MCP config | `~/.claude.json` `env` field has secrets in cleartext | Put secrets in `~/.zshenv`, MCP subprocess inherits via environment variables |

For the complete troubleshooting history and fix details, see Section 5 of `claude-config/docs/memory-system.md`.

---

## Backup & Restore

### Backup

```bash
# Qdrant snapshot
curl -X POST "http://localhost:6333/collections/unified_memories_v3/snapshots"
# Download snapshot
curl -o qdrant-backup.snapshot \
  "http://localhost:6333/collections/unified_memories_v3/snapshots/<snapshot_name>"

# Neo4j export (online)
docker exec neo4j-memory cypher-shell -u neo4j -p YOUR_PASSWORD \
  "CALL apoc.export.json.all(null, {stream:true, useTypes:true}) YIELD data RETURN data" \
  > neo4j-backup.json
```

### Restore

```bash
# Qdrant restore
curl -X POST "http://localhost:6333/collections/unified_memories_v3/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@qdrant-backup.snapshot"

# Neo4j restore (requires APOC plugin)
cat neo4j-backup.json | docker exec -i neo4j-memory \
  cypher-shell -u neo4j -p YOUR_PASSWORD \
  "CALL apoc.import.json(null, {stream:true})"
```

---

## Who Is This For

This system isn't limited to programming scenarios. Any role that needs "cross-session memory + entity relationships + knowledge accumulation" can benefit:

| Role | What Qdrant does for you | What Graphiti adds |
|---|---|---|
| **Developers** | Search past debugging experience, architecture decisions | Module dependency graph |
| **Product Managers** | Search user feedback, requirement discussions | Requirement-feature-user association analysis |
| **Sales / Account Managers** | Search client communication records | Client profiles + relationship networks |
| **Researchers / Analysts** | Semantic search of literature notes | Person-organization-event association discovery |
| **Freelancers** | Cross-client context switching | Cross-client pattern discovery |
| **Team Leaders** | Search team discussions and decisions | Person → project → resource org charts |

---

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| Vector Database | [Qdrant](https://qdrant.tech/) | latest |
| Graph Database | [Neo4j](https://neo4j.com/) | 5.x |
| Knowledge Graph | [Graphiti](https://github.com/getzep/graphiti) | latest |
| MCP Framework | [FastMCP](https://github.com/jlowin/fastmcp) | via `mcp` package |
| Embedding | [Alibaba Cloud text-embedding-v4](https://help.aliyun.com/zh/model-studio/text-embedding) | 1024 dims |
| Note System | [Obsidian](https://obsidian.md/) + Local REST API | Optional |
| Container Orchestration | Docker Compose | - |
| Process Management | macOS launchd | - |

---

## License

MIT
