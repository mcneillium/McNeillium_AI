# Retrieval-Augmented Generation (RAG)

## What it is
RAG is a technique that enhances LLM responses by retrieving relevant information from an external knowledge base before generating an answer. Instead of relying solely on what the model memorised during training, RAG fetches up-to-date, domain-specific documents and includes them in the prompt context. This dramatically reduces hallucinations and lets the model work with private or recent data it was never trained on.

## How it works
The RAG pipeline has three stages. First, indexing: documents are split into chunks (typically 200-500 tokens), each chunk is converted into a vector embedding (a numerical representation of meaning), and stored in a vector database. Second, retrieval: when a user asks a question, the query is also embedded, and the system finds the most semantically similar document chunks using cosine similarity or approximate nearest neighbour search. Third, generation: the retrieved chunks are injected into the LLM's prompt as context, and the model generates an answer grounded in that evidence. Think of it like an open-book exam: the model can look up the answers rather than relying on memory alone.

## Key concepts
- **Embeddings**: Dense vector representations of text that capture semantic meaning
- **Vector databases**: Specialised stores for similarity search (Pinecone, Weaviate, Chroma, pgvector)
- **Chunking strategies**: How documents are split affects retrieval quality — too small loses context, too large dilutes relevance
- **Hybrid search**: Combining semantic (vector) search with keyword (BM25) search for better recall
- **Reranking**: A second model scores and reorders retrieved chunks by relevance before passing to the LLM
- **Context window management**: Fitting retrieved content within the model's token limit

## Current state (2026)
RAG is the most widely deployed LLM pattern in production. Nearly every enterprise AI chatbot, customer support bot, and internal knowledge assistant uses some form of RAG. Advanced techniques include graph RAG (using knowledge graphs instead of flat documents), agentic RAG (agents that decide what to retrieve and when), and multimodal RAG (retrieving images, tables, and code alongside text). The tooling has matured significantly with frameworks like LlamaIndex and LangChain.

## Why it matters
RAG solves the two biggest problems with LLMs: hallucination and stale knowledge. It lets organisations build AI that actually knows their specific data without expensive fine-tuning. For any AI application that needs accuracy and recency, RAG is the standard approach.

## Related topics
- [[llms]] — The generation component of RAG
- [[transformers]] — Architecture that powers both the embeddings and the generator
- [[prompt-engineering]] — How retrieved context is formatted for the LLM
