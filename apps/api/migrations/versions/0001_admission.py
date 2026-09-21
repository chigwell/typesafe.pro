"""Client tokens, configurable admission policies and three-day error events."""

from alembic import op

revision = "0001_admission"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE api_client_tokens (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            token_hash varchar(64) NOT NULL UNIQUE CHECK (length(token_hash) = 64),
            tier text NOT NULL CHECK (tier IN ('free', 'paid')),
            label text,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz,
            revoked_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE rate_limit_policies (
            tier text PRIMARY KEY CHECK (tier IN ('anonymous', 'free', 'paid')),
            rpm integer NOT NULL CHECK (rpm BETWEEN 1 AND 1000000),
            burst integer NOT NULL CHECK (burst BETWEEN 1 AND 10000),
            queue_wait_seconds double precision NOT NULL
                CHECK (queue_wait_seconds > 0 AND queue_wait_seconds <= 30),
            queue_size integer NOT NULL CHECK (queue_size BETWEEN 1 AND 4096)
        )
    """)
    op.execute("""
        INSERT INTO rate_limit_policies VALUES
            ('anonymous', 30, 5, 3, 64), ('free', 120, 10, 10, 128),
            ('paid', 1000, 20, 30, 256)
    """)
    op.execute("""
        CREATE TABLE proxy_error_events (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at timestamptz NOT NULL,
            request_id varchar(128) NOT NULL,
            client_tier text NOT NULL,
            client_hash varchar(64),
            ip_hash varchar(64),
            method varchar(32) NOT NULL,
            path varchar(1024) NOT NULL,
            status integer NOT NULL,
            error_code varchar(64) NOT NULL,
            duration_ms double precision NOT NULL,
            queue_ms double precision NOT NULL,
            upstream_ms double precision,
            master_key_id varchar(32),
            upstream_status integer,
            upstream_valid boolean,
            estimated_tokens bigint NOT NULL,
            usage_tokens bigint,
            request_bytes integer NOT NULL,
            exception_class varchar(128),
            error_detail text,
            raw_response text,
            response_truncated boolean NOT NULL
        )
    """)
    op.execute("CREATE INDEX proxy_error_events_created_at ON proxy_error_events (created_at)")
    op.execute("CREATE INDEX proxy_error_events_request_id ON proxy_error_events (request_id)")


def downgrade():
    op.drop_table("proxy_error_events")
    op.drop_table("rate_limit_policies")
    op.drop_table("api_client_tokens")
