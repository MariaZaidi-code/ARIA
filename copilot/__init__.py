"""ARIA Copilot — provider-independent RAG over connected databases.

One intelligent Copilot with interchangeable LLM execution backends
(Ollama local / Groq cloud). The RAG layer here never depends on which LLM
provider is active: retrieval, schema indexing, ranking, conversation memory,
SQL validation and database execution are all provider-independent.
"""

from .schema_index import SchemaIndex, build_schema_index
from .retriever import SchemaRetriever, RetrievedContext
from .embeddings import create_embedder, Embedder
from .conversation import ConversationMemory
from .sql_engine import SqlEngine, SqlResult
from .pipeline import CopilotPipeline, CopilotAnswer, create_pipeline

__all__ = [
    "SchemaIndex",
    "build_schema_index",
    "SchemaRetriever",
    "RetrievedContext",
    "create_embedder",
    "Embedder",
    "ConversationMemory",
    "SqlEngine",
    "SqlResult",
    "CopilotPipeline",
    "CopilotAnswer",
    "create_pipeline",
]