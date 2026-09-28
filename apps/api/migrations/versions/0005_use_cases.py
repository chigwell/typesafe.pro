"""Use-case content in Postgres: categories, tags, pages with full-text search, skips."""

from alembic import op

revision = "0005_use_cases"
down_revision = "0004_seo_journal"
branch_labels = None
depends_on = None

CATEGORIES = [
    ("routing-triage", "Routing & triage", "Send each request to the right queue, team or flow."),
    ("moderation-safety", "Moderation & safety", "Screen content for spam, abuse or risk."),
    ("tone-sentiment", "Tone & sentiment", "Read the mood, tone or emotion in a message."),
    ("quality-completeness", "Quality & completeness", "Check whether text is clear and complete."),
    ("scoring-prioritisation", "Scoring & prioritisation", "Rate urgency, severity or effort."),
    ("matching-recommendation", "Matching & recommendation", "Pick the best fitting option."),
    ("detection-classification", "Detection & classification", "Spot a signal or label the text."),
    ("creative-lifestyle", "Creative & lifestyle", "Everyday, creative and personal apps."),
]


STATEMENTS = [
    """
    CREATE TABLE use_case_categories (
            id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            slug varchar(64) NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            name varchar(80) NOT NULL,
            description varchar(300) NOT NULL DEFAULT '',
            sort_order integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """,
    """
    CREATE TABLE use_case_tags (
            id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            slug varchar(48) NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            name varchar(64) NOT NULL
        )
    """,
    """
    CREATE TABLE use_cases (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            slug varchar(120) NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            status varchar(16) NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
            category_id integer REFERENCES use_case_categories (id),
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
            fingerprint char(64) NOT NULL UNIQUE,
            title varchar(200) NOT NULL,
            meta_description varchar(400) NOT NULL,
            summary varchar(800) NOT NULL,
            industry varchar(800) NOT NULL,
            audience varchar(800) NOT NULL,
            task_type varchar(80) NOT NULL,
            question_types text[] NOT NULL DEFAULT '{}',
            has_demo boolean NOT NULL DEFAULT false,
            content jsonb NOT NULL,
            inspiration jsonb,
            novelty real,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            published_at timestamptz,
            search tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A')
                || setweight(to_tsvector('english',
                    coalesce(summary, '') || ' ' || coalesce(task_type, '') || ' '
                    || coalesce(industry, '') || ' ' || coalesce(audience, '')), 'B')
                || setweight(to_tsvector('english',
                    coalesce(content ->> 'problem', '') || ' '
                    || coalesce(content ->> 'intro', '') || ' '
                    || coalesce(content ->> 'solution', '')), 'C')
            ) STORED,
            CHECK (status <> 'published' OR published_at IS NOT NULL)
        )
    """,
    """
    CREATE INDEX use_cases_search ON use_cases USING gin (search)
    """,
    """
    CREATE INDEX use_cases_listing ON use_cases (status, published_at DESC, id DESC)
    """,
    """
    CREATE INDEX use_cases_category
            ON use_cases (status, category_id, published_at DESC, id DESC)
    """,
    """
    CREATE INDEX use_cases_task_type ON use_cases (task_type)
    """,
    """
    CREATE TABLE use_case_tag_links (
            use_case_id bigint NOT NULL REFERENCES use_cases (id) ON DELETE CASCADE,
            tag_id integer NOT NULL REFERENCES use_case_tags (id),
            PRIMARY KEY (use_case_id, tag_id)
        )
    """,
    """
    CREATE INDEX use_case_tag_links_tag ON use_case_tag_links (tag_id, use_case_id)
    """,
    """
    CREATE TABLE use_case_skips (
            fingerprint char(64) PRIMARY KEY,
            slug varchar(120) NOT NULL,
            summary varchar(800) NOT NULL,
            task_type varchar(80) NOT NULL,
            decision varchar(800) NOT NULL,
            reason varchar(800) NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """,
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
    for order, (slug, name, description) in enumerate(CATEGORIES):
        op.execute(
            "INSERT INTO use_case_categories (slug, name, description, sort_order) "
            f"VALUES ('{slug}', '{name}', '{description}', {order}) ON CONFLICT (slug) DO NOTHING"
        )


def downgrade():
    for table in (
        "use_case_skips",
        "use_case_tag_links",
        "use_cases",
        "use_case_tags",
        "use_case_categories",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
