"""Daily public page views."""

from alembic import op

revision = "0003_page_views"
down_revision = "0002_observability"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE page_views (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            view_date date NOT NULL,
            path varchar(1024) NOT NULL,
            visitor_hash varchar(64) NOT NULL CHECK (length(visitor_hash) = 64),
            first_seen_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL,
            hits integer NOT NULL DEFAULT 1 CHECK (hits > 0),
            UNIQUE (view_date, path, visitor_hash)
        )
    """)
    op.execute("CREATE INDEX page_views_rollup ON page_views (view_date DESC, path)")


def downgrade():
    op.drop_table("page_views")
