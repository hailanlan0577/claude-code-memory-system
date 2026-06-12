# 2026-06-12 补丁：本地 llama.cpp(llama-server) 抽取改用 json_schema 强制语法

把 Graphiti 抽取后端切到 **llama.cpp / llama-server（OpenAI 兼容，跑本地大模型如 Qwen3.6-35B 等）** 后，`2026-05-02-additional-changes` 那套「`responses.parse` 失败回退 `chat.completions` + `json_object`」**不再够用**。本补丁取代其中 `openai_client.py` 的部分。

## 为什么旧方案不够

llama.cpp 上踩到两个新坑：

1. **`/v1/responses`（Responses API）不强制结构化**：`responses.parse` 拿到的内容被模型裹进 ` ```json ... ``` ` markdown 围栏 → 严格校验抛 `json_invalid`。
2. **`/v1/chat/completions` 的 `json_object` 模式也不强制语法**：实测同一个抽取请求，时而吐合法 JSON，时而吐纯文本（如 `"张三" (Entity)`）→ `json.loads` 报 `Expecting value: line 1 column 1`。

结果：Graphiti 抽取全程失败，知识图谱静默停止写入。

## 本补丁怎么修

改 `graphiti_core/llm_client/openai_client.py` 的 `_create_structured_completion`：

- 用 `chat.completions` + **`response_format={'type':'json_schema', 'json_schema':{'name':..., 'schema': response_model.model_json_schema()}}`**。llama.cpp 会把 schema 编译成 **GBNF 语法**，从 token 级强制输出合法且符合 schema 的 JSON（实测稳定）。
- 复杂 schema 万一编译失败（API 400），回退 `json_object`。
- 统一 `_strip_code_fences()` 去 markdown 围栏兜底。
- 返回 `_StructuredResponseShim`（只暴露 `_handle_structured_response` 用到的 `output_text` / `usage` / `refusal`），契约对齐基类，绕开会坏的 Responses API。

## 怎么应用

```bash
cp openai_client.reference.py \
  <venv>/lib/python3.11/site-packages/graphiti_core/llm_client/openai_client.py
find <venv>/lib/python3.11/site-packages/graphiti_core -name '*.pyc' -delete
# 重启 Graphiti MCP
```

> 注：本 reference **取代** `2026-05-02-additional-changes/openai_client.reference.py`（那版是 json_object fallback，对 llama.cpp 不够）。`extract_nodes.reference.py`（SummarizedEntities 归一化）仍需照旧应用。
>
> `apply-patches.sh` 已接入：会先打 `.patch` 系列（含 `openai_base_client.py`），再 `cp` 本 reference 覆盖 `openai_client.py`，一键全恢复。

## 配套前提

1. **LLM 端点指向 llama.cpp / llama-server**（OpenAI 兼容 `/v1`）。Graphiti `.env` 的 `OPENAI_BASE_URL` / `LLM__PROVIDERS__OPENAI__API_URL` 指过去。
2. **API key**：若 llama-server 启用了 `--api-key`，`.env` 的 `OPENAI_API_KEY` + `LLM__PROVIDERS__OPENAI__API_KEY` 必须填该 key，否则 401。
3. embedder 可继续用本地 OpenAI 兼容 embedding 服务（按 `.env` 配置）。

## 适配的本地后端

- ✅ **llama.cpp / llama-server**（GGUF 本地模型）— 本补丁针对它，json_schema 强制语法稳定。
- 旧的 `mlx_lm.server`（MLX 版）走 `2026-05-02` 那套也能跑。

## 验证

加一条 `add_memory("张三在 Acme 公司负责销售")`，Neo4j 应出现实体 `张三`/`Acme 公司` 及关系事实 `张三在 Acme 公司负责销售`。本补丁 2026-06-12 实测通过。
