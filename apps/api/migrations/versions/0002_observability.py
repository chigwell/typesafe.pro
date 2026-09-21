"""Real IPs and stable pagination for admin error history."""

from alembic import op

revision = "0002_observability"
down_revision = "0001_admission"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE proxy_error_events ADD COLUMN client_ip inet")
    op.execute(
        "CREATE INDEX proxy_error_events_page ON proxy_error_events (created_at DESC, id DESC)"
    )


def downgrade():
    op.execute("DROP INDEX proxy_error_events_page")
    op.execute("ALTER TABLE proxy_error_events DROP COLUMN client_ip")
