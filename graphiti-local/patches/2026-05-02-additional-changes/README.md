# 2026-05-02 补丁补充

切换到本地 LLM (Mac Studio Qwen3.6-35B-A3B 或类似 mlx_lm.server) 后,在原 qwen-plus 补丁基础上需要追加 2 处修改。

## 新增改动

### 1. `llm_client/openai_client.py` 第 119-149 行

**问题**:原版 fallback 只在错误信息含 `validation error` 或 `json` 时触发,但:
- mlx_lm.server **不实现** `/v1/responses` → 报 404 Not Found
- mlx_vlm.server 实现了但返回 ParsedResponse.parsed=None → 报 "Invalid response from LLM"

**修复**:`responses.parse` 任何失败都尝试 fallback 到 `chat.completions`,fallback 也失败再 raise 原 error。

**代码改动**:把 `if 'validation error' in error_msg.lower() or 'json' in error_msg.lower():` 这个 if 判断**去掉**,所有 except 都走 fallback 流程。

### 2. `prompts/extract_nodes.py` SummarizedEntities

**问题**:35B 模型返回 `{'实体名': 'summary 文本', ...}` 这种 dict-only 格式,不是 graphiti 期望的 `{'summaries': [{...}]}`。

**修复**:`normalize_summaries_field` 加一段:检测 dict 全部 value 都是 str 时,转成 `{'summaries': [{'name': k, 'summary': v}]}`。

## 怎么应用

直接把 `openai_client.reference.py` 和 `extract_nodes.reference.py` 的内容**覆盖** venv 里对应文件:

```bash
cp openai_client.reference.py /your/venv/lib/.../graphiti_core/llm_client/openai_client.py
cp extract_nodes.reference.py /your/venv/lib/.../graphiti_core/prompts/extract_nodes.py
```

## 适配的本地 LLM

测试通过的:
- **Qwen3.6-35B-A3B BF16**(MoE,3B 激活)— 推荐,提取质量好,60s/episode
- ❌ Qwen3.6-27B-bf16(reasoning model,**不要用**,慢 5 倍且字段名不兼容)

## 调用方式

不要直接调 `/v1/responses`,让 graphiti 自动 fallback 到 `/v1/chat/completions`。

```env
LLM__MODEL=/path/to/Qwen3.6-35B-A3B-bf16
OPENAI_BASE_URL=http://your-llm-server:port/v1
OPENAI_API_KEY=any-string-no-auth
```
