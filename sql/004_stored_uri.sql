-- ORIGIN — separate "where it came from"ance from "where the bytes are"
--
-- Fixes a real defect: admit_document was writing the storage location into
-- source_uri, discarding the external source URI it was handed. Provenance rows
-- pointed at a local file path instead of the document's origin, and that value
-- was also being emitted to DataHub as externalUrl.
--
-- For a provenance ledger this is close to the worst possible bug: the source is
-- the provenance. A local cache path answers "where is the copy", which nobody
-- asked, while destroying the answer to "where did this come from", which is the
-- entire question.
--
-- The two are genuinely different facts and both are needed — the source for
-- attribution and audit, the storage location to serve retrieval snippets — so
-- they now have a column each.

SET database = origin;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS stored_uri STRING;

COMMENT ON COLUMN documents.source_uri IS
    'Where the document came from: the external, citable origin. Never a local path.';

COMMENT ON COLUMN documents.stored_uri IS
    'Where our copy of the bytes lives (file:// or s3://). An implementation detail, not provenance.';
