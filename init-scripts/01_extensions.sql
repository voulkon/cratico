-- Vector similarity search
CREATE EXTENSION IF NOT EXISTS pgvector;

-- Extras that make FTS nicer
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram similarity
CREATE EXTENSION IF NOT EXISTS unaccent;  -- remove accents in search
