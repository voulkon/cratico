-- Vector similarity search (extension name is "vector", not "pgvector" —
-- pgvector is the project/image name, the SQL extension is "vector")
CREATE EXTENSION IF NOT EXISTS vector;

-- Extras that make FTS nicer
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram similarity
CREATE EXTENSION IF NOT EXISTS unaccent;  -- remove accents in search
