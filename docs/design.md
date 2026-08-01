# SmartLearn Agent - Product Design

## User Stories

1. As a student, I want to upload a PDF and ask questions about it, so that I can study more efficiently.
2. As a student, I want to get answers with page numbers, so that I can quickly find the original content in the PDF.
3. As a student, I want to ask follow-up questions in a conversatio, so that I can deepen understanding of a topic.

## Feature List

| Priority | Feature | Notes |
|----------|---------|------|
| P0 | PDF text extraction | The foundation; nothing works without it |
| P0 | LLM Q&A with page citation | The core feature; users upload a PDF and ask questions |
| P1 | RAG pipeline | Handles long PDFs by retrieving only the most relevant parts |
| P1 | Web UI | Lets users interact through a browser |
| P2 | Chat history | Remembers earlier questions and supports follow-ups |

## What We Will NOT Build

- User authentication — skip login
- Multi-file support — perfect the single-PDF experience first
- Mobile app — web version only

## Data Flow

### Day 2: Simple Mode

PDF File
  -> [PDF parser / extract text]          # How do we get text out?
  -> pages[]
  -> [build prompt: pages + question]          # How do we combine with question?
  -> [LLM]
  -> Answer with [Page X]

### Day 3: RAG Mode

PDF -> [extract text] -> pages
    -> [split into chunks] -> chunks with source_page
    -> [embed] -> embeddings
    -> [vector store (FAISS)]  # storage

Question -> [encode] -> [similarity search] -> relevant chunks -> [LLM] -> Answer