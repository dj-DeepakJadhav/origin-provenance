CREATE TABLE IF NOT EXISTS corpus_search_index (
    corpus_id UUID NOT NULL,
    doc_id    STRING NOT NULL,
    embedding VECTOR(1024),
    PRIMARY KEY (corpus_id, doc_id)
);

CREATE VECTOR INDEX IF NOT EXISTS idx_search_corpus_prefix
    ON corpus_search_index (corpus_id, embedding vector_cosine_ops);
