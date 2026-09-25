"""Generated use-case runs and verified publication snapshots."""

from alembic import op

revision = "0004_seo_journal"
down_revision = "0003_page_views"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE seo_runs (
            run_id varchar(128) PRIMARY KEY,
            source_sha varchar(64) NOT NULL,
            status varchar(16) NOT NULL CHECK (status IN ('prepared', 'skipped', 'failed')),
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            report jsonb NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX seo_runs_recent ON seo_runs (started_at DESC, run_id)")
    op.execute("""
        CREATE TABLE seo_publications (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id varchar(128) UNIQUE NOT NULL,
            source_sha varchar(64) NOT NULL,
            catalog_hash varchar(64) NOT NULL,
            generated_at timestamptz NOT NULL,
            published_at timestamptz NOT NULL,
            added_count integer NOT NULL CHECK (added_count >= 0),
            removed_count integer NOT NULL CHECK (removed_count >= 0),
            total_pages integer NOT NULL CHECK (total_pages >= 0),
            manifest jsonb NOT NULL
        )
    """)
    op.execute("CREATE INDEX seo_publications_recent ON seo_publications (id DESC)")
    op.execute("""
        CREATE TABLE seo_pages (
            slug varchar(120) PRIMARY KEY,
            title varchar(200) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            published_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX seo_pages_recent ON seo_pages (published_at DESC, slug)")
    op.execute("CREATE INDEX page_views_path ON page_views (path)")


def downgrade():
    op.drop_index("page_views_path", table_name="page_views")
    op.drop_table("seo_pages")
    op.drop_table("seo_publications")
    op.drop_table("seo_runs")
