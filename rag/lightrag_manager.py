"""LightRAG initialization, indexing, and retrieval."""
import os
import asyncio
import logging
from functools import partial
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete, openai_embed as _openai_embed_default
from lightrag.rerank import jina_rerank
from lightrag.utils import EmbeddingFunc

logger = logging.getLogger(__name__)


def _get_or_create_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop

class LightRAGManager:
    def __init__(self, config: dict):
        rag_cfg = config.get("lightrag", {})
        self.working_dir = rag_cfg.get("working_dir", "./lightrag_data")
        os.makedirs(self.working_dir, exist_ok=True)

        # LLM config (OpenAI-compatible Qwen endpoint)
        llm_cfg = rag_cfg.get("llm", {})
        llm_model = llm_cfg.get("model", "qwen3.5-plus")
        llm_api_key = llm_cfg.get("api_key", "")
        llm_base_url = llm_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        llm_timeout = int(llm_cfg.get("timeout", 180))
        llm_max_tokens = int(llm_cfg.get("max_tokens", 4096))

        # Embedding config (SiliconFlow / bge-m3)
        emb_cfg = rag_cfg.get("embedding", {})
        emb_model = emb_cfg.get("model", "BAAI/bge-m3")
        emb_api_key = emb_cfg.get("api_key", "")
        emb_base_url = emb_cfg.get("base_url", "https://api.siliconflow.cn/v1")
        emb_dim = emb_cfg.get("dim", 1024)
        emb_max_tokens = emb_cfg.get("max_tokens", 8192)

        embedding_func = EmbeddingFunc(
            embedding_dim=emb_dim,
            max_token_size=emb_max_tokens,
            func=partial(
                _openai_embed_default.func,
                model=emb_model,
                api_key=emb_api_key,
                base_url=emb_base_url,
            ),
        )

        # Rerank config (SiliconFlow / bge-reranker-v2-m3)
        rerank_cfg = rag_cfg.get("rerank", {})
        rerank_model = rerank_cfg.get("model", "BAAI/bge-reranker-v2-m3")
        rerank_api_key = rerank_cfg.get("api_key", "")
        rerank_base_url = rerank_cfg.get("base_url", "https://api.siliconflow.cn/v1/rerank")

        rerank_func = partial(
            jina_rerank,
            model=rerank_model,
            api_key=rerank_api_key,
            base_url=rerank_base_url,
        )

        self.rag = LightRAG(
            working_dir=self.working_dir,
            llm_model_func=openai_complete,
            llm_model_name=llm_model,
            llm_model_kwargs={
                "api_key": llm_api_key,
                "base_url": llm_base_url or None,
                "timeout": llm_timeout,
                "max_tokens": llm_max_tokens,
            },
            embedding_func=embedding_func,
            rerank_model_func=rerank_func,
            addon_params={"language": "Simplified Chinese"},
        )

        # Initialize storages
        loop = _get_or_create_event_loop()
        loop.run_until_complete(self.rag.initialize_storages())

    def index_text(self, text: str):
        """Index text into LightRAG."""
        self.rag.insert(text)

    def query(self, query_text: str, mode: str = "mix") -> str:
        """Query LightRAG. mode: naive/local/global/hybrid/mix"""
        try:
            return self.rag.query(query_text, param=QueryParam(mode=mode))
        except Exception as e:
            logger.error("LightRAG query failed: %s", e)
            return ""

    def batch_query(self, queries: list, mode: str = "mix") -> list:
        """Run multiple queries, return list of results."""
        return [self.query(q, mode) for q in queries if q]

    def batch_query_parallel(self, queries: list, mode: str = "mix", batch_size: int = 3) -> list:
        """Run multiple queries concurrently in batches using asyncio."""
        filtered = [q for q in queries if q]
        if not filtered:
            return []
        loop = _get_or_create_event_loop()

        async def _run():
            all_results = []
            for i in range(0, len(filtered), batch_size):
                batch = filtered[i:i + batch_size]
                tasks = [self.rag.aquery(q, param=QueryParam(mode=mode)) for q in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                all_results.extend(results)
                if i + batch_size < len(filtered):
                    await asyncio.sleep(2)
            return all_results

        results = loop.run_until_complete(_run())
        out = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("LightRAG parallel query failed: %s", r)
                out.append("")
            else:
                out.append(r or "")
        return out
