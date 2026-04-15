CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_key text UNIQUE NOT NULL,
    canonical_name text NOT NULL,
    entity_type text NOT NULL DEFAULT 'concept',
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_type text NOT NULL DEFAULT 'alias',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_id, normalized_alias)
);

CREATE TABLE IF NOT EXISTS claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    text text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    confidence numeric(4,3) NOT NULL DEFAULT 0.500 CHECK (confidence >= 0 AND confidence <= 1),
    source_weight numeric(4,3) NOT NULL DEFAULT 0.500 CHECK (source_weight >= 0 AND source_weight <= 1),
    claim_role text NOT NULL DEFAULT 'support' CHECK (claim_role IN ('core', 'support', 'caution', 'conflict', 'example')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_role ON claims(claim_role);
CREATE INDEX IF NOT EXISTS idx_claims_search_vector ON claims USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_claims_text_trgm ON claims USING gin(lower(text) gin_trgm_ops);

CREATE TABLE IF NOT EXISTS evidences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_type text NOT NULL,
    source_uri text,
    excerpt text,
    hash text,
    note text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidences_claim_id ON evidences(claim_id);

CREATE TABLE IF NOT EXISTS claim_mentions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    mention_text text NOT NULL,
    normalized_mention text NOT NULL,
    role text,
    entity_id uuid REFERENCES entities(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (claim_id, normalized_mention)
);

CREATE INDEX IF NOT EXISTS idx_claim_mentions_claim_id ON claim_mentions(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_mentions_normalized ON claim_mentions(normalized_mention);
CREATE INDEX IF NOT EXISTS idx_claim_mentions_trgm ON claim_mentions USING gin(normalized_mention gin_trgm_ops);

CREATE TABLE IF NOT EXISTS claim_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    to_claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    link_type text NOT NULL CHECK (link_type IN ('related', 'supports', 'conflicts', 'supersedes')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (from_claim_id, to_claim_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_claim_links_from ON claim_links(from_claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_links_to ON claim_links(to_claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_links_type ON claim_links(link_type);

CREATE TABLE IF NOT EXISTS capsules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    summary jsonb NOT NULL DEFAULT '[]'::jsonb,
    key_points jsonb NOT NULL DEFAULT '[]'::jsonb,
    cautions jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_claim_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    confidence numeric(4,3) NOT NULL DEFAULT 0.500 CHECK (confidence >= 0 AND confidence <= 1),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary::text, ''))
    ) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_capsules_source_claim_ids ON capsules USING gin(source_claim_ids);
CREATE INDEX IF NOT EXISTS idx_capsules_search_vector ON capsules USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_capsules_title_trgm ON capsules USING gin(lower(title) gin_trgm_ops);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_claims_updated_at ON claims;
CREATE TRIGGER set_claims_updated_at
BEFORE UPDATE ON claims
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_capsules_updated_at ON capsules;
CREATE TRIGGER set_capsules_updated_at
BEFORE UPDATE ON capsules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_entities_updated_at ON entities;
CREATE TRIGGER set_entities_updated_at
BEFORE UPDATE ON entities
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
