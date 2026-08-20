-- Phase 0 schema (PostgreSQL).
-- Maps the domain models onto storage. org_id is present everywhere even
-- though v1 is single-tenant — carrying it now is free, retrofitting is misery.
-- Files live in object storage (S3/Blob/GCS); only references live here.

CREATE TABLE org (
    org_id        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Canonical best-practice library. New versions are new rows (immutable history).
CREATE TABLE canonical_control (
    control_id          TEXT NOT NULL,
    version             INT  NOT NULL,
    domain              TEXT NOT NULL,
    statement           TEXT NOT NULL,
    best_practice_refs  JSONB NOT NULL DEFAULT '[]',
    default_threshold   TEXT NOT NULL,
    default_applicability INT NOT NULL,   -- DataClassification ordinal
    risk_weight         INT  NOT NULL CHECK (risk_weight BETWEEN 1 AND 5),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (control_id, version)
);

-- Per-tenant overlay: overrides + custom controls. JSONB gives schema flexibility
-- for terminology maps and future fields without migrations.
CREATE TABLE control_override (
    org_id                  TEXT NOT NULL REFERENCES org(org_id),
    control_id              TEXT NOT NULL,
    base_version            INT  NOT NULL,   -- baseline version authored against
    threshold_override      TEXT,
    applicability_override  INT,
    risk_weight_override    INT CHECK (risk_weight_override BETWEEN 1 AND 5),
    terminology             JSONB NOT NULL DEFAULT '{}',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, control_id)
);

CREATE TABLE custom_control (
    org_id          TEXT NOT NULL REFERENCES org(org_id),
    control_id      TEXT NOT NULL,
    domain          TEXT NOT NULL,
    statement       TEXT NOT NULL,
    threshold       TEXT NOT NULL,
    applicability   INT  NOT NULL,
    risk_weight     INT  NOT NULL CHECK (risk_weight BETWEEN 1 AND 5),
    version         INT  NOT NULL DEFAULT 1,
    PRIMARY KEY (org_id, control_id)
);

-- Suppliers (10k expected) and their documents (files in object storage).
CREATE TABLE supplier (
    supplier_id   TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES org(org_id),
    name          TEXT NOT NULL,
    attributes    JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document (
    document_id     TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES org(org_id),
    supplier_id     TEXT REFERENCES supplier(supplier_id),
    object_uri      TEXT NOT NULL,        -- s3://... pointer, NOT the bytes
    content_type    TEXT,
    extracted_text  TEXT,                 -- for RAG / search
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Frozen effective-policy snapshot taken at assessment start.
CREATE TABLE policy_snapshot (
    snapshot_id   TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES org(org_id),
    content_hash  TEXT NOT NULL,
    serialised    JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE assessment (
    assessment_id   TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES org(org_id),
    supplier_id     TEXT NOT NULL REFERENCES supplier(supplier_id),
    snapshot_id     TEXT NOT NULL REFERENCES policy_snapshot(snapshot_id),
    status          TEXT NOT NULL DEFAULT 'in_progress',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only, hash-chained audit trail. Enforced immutable by trigger.
CREATE TABLE audit_entry (
    seq           BIGINT NOT NULL,
    org_id        TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    actor         TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    payload       JSONB NOT NULL,
    prev_hash     TEXT NOT NULL,
    entry_hash    TEXT NOT NULL,
    PRIMARY KEY (seq)
);

CREATE OR REPLACE FUNCTION audit_no_mutate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_entry is append-only; % rejected', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_immutable
    BEFORE UPDATE OR DELETE ON audit_entry
    FOR EACH ROW EXECUTE FUNCTION audit_no_mutate();

-- pgvector for RAG (Phase 4) can be added in-instance later:
--   CREATE EXTENSION vector;
--   ALTER TABLE document ADD COLUMN embedding vector(1536);

-- ============================================================
-- Phase 1: actors, evidence, ratings, governance
-- ============================================================

CREATE TABLE engagement (
    engagement_id  TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES org(org_id),
    vendor_id      TEXT NOT NULL REFERENCES supplier(supplier_id),
    scope          TEXT,                 -- the specific use this engagement covers
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every message carries author role (Q1) -> drives trust + visibility.
CREATE TABLE chat_message (
    message_id     TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES org(org_id),
    engagement_id  TEXT NOT NULL REFERENCES engagement(engagement_id),
    author_role    INT  NOT NULL,        -- ActorRole: 1 vendor, 2 assessor, 3 system
    visibility     INT  NOT NULL,        -- Visibility: 1 internal_only, 2 shared
    body           TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Evidence carries source type (Q4) for precedence resolution.
CREATE TABLE evidence (
    evidence_id    TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES org(org_id),
    engagement_id  TEXT NOT NULL REFERENCES engagement(engagement_id),
    source_type    INT  NOT NULL,        -- SourceType: higher int = higher precedence
    author_role    INT  NOT NULL,
    domain         TEXT NOT NULL,
    claim          TEXT NOT NULL,
    captured_on    DATE NOT NULL,
    valid_until    DATE,
    document_id    TEXT REFERENCES document(document_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ratings: per-domain, per-engagement, per-vendor (Q2).
CREATE TABLE domain_rating (
    rating_id      TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES org(org_id),
    engagement_id  TEXT NOT NULL REFERENCES engagement(engagement_id),
    domain         TEXT NOT NULL,
    computed_tier  INT  NOT NULL CHECK (computed_tier BETWEEN 1 AND 4),
    confidence     REAL NOT NULL,
    rationale      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE engagement_rating (
    engagement_id        TEXT PRIMARY KEY REFERENCES engagement(engagement_id),
    org_id               TEXT NOT NULL REFERENCES org(org_id),
    computed_tier        INT  NOT NULL CHECK (computed_tier BETWEEN 1 AND 4),
    concentration_applied BOOLEAN NOT NULL DEFAULT FALSE,
    roll_up_method       TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vendor rating keeps computed tier and the human-only Tier 0 flag SEPARATE (Q5).
CREATE TABLE vendor_rating (
    vendor_id            TEXT PRIMARY KEY REFERENCES supplier(supplier_id),
    org_id               TEXT NOT NULL REFERENCES org(org_id),
    computed_tier        INT  NOT NULL CHECK (computed_tier BETWEEN 1 AND 4),
    governance_flag      TEXT,             -- 'TIER_0_CRITICAL_VENDOR' or NULL
    governance_actor     TEXT,             -- human who designated; NULL if none
    governance_reason    TEXT,
    concentration_applied BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Tier 0 must always have a human actor recorded.
    CONSTRAINT tier0_requires_human CHECK (
        governance_flag IS NULL OR governance_actor IS NOT NULL
    )
);
