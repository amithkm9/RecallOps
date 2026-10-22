"""Operational history, scoped credentials, ordered intake and case ownership."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE incidents ADD COLUMN assigned_to varchar(120), ADD COLUMN review_status varchar(30) NOT NULL DEFAULT 'open', ADD COLUMN closed_at timestamptz"
    )
    op.execute(
        "CREATE TABLE source_refreshes (id varchar(36) PRIMARY KEY, created_at timestamptz NOT NULL, source varchar(30) NOT NULL, status varchar(30) NOT NULL, finished_at timestamptz, details jsonb NOT NULL)"
    )
    op.execute(
        "CREATE INDEX ix_source_refreshes_created_at ON source_refreshes(created_at)"
    )
    op.execute("CREATE INDEX ix_source_refreshes_status ON source_refreshes(status)")
    op.execute(
        "CREATE TABLE source_rejections (id varchar(36) PRIMARY KEY, created_at timestamptz NOT NULL, refresh_id varchar(36) NOT NULL REFERENCES source_refreshes(id), reason text NOT NULL, raw jsonb NOT NULL)"
    )
    op.execute(
        "CREATE INDEX ix_source_rejections_refresh_id ON source_rejections(refresh_id)"
    )
    op.execute(
        "CREATE INDEX ix_source_rejections_created_at ON source_rejections(created_at)"
    )
    op.execute(
        "CREATE TABLE access_credentials (id varchar(36) PRIMARY KEY, created_at timestamptz NOT NULL, name varchar(120) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE, role varchar(20) NOT NULL CHECK (role IN ('admin','operator','integration','viewer')), store_ids jsonb NOT NULL, active boolean NOT NULL)"
    )
    op.execute(
        "CREATE INDEX ix_access_credentials_created_at ON access_credentials(created_at)"
    )
    op.execute(
        "CREATE TABLE inventory_receipts (id varchar(36) PRIMARY KEY, created_at timestamptz NOT NULL, store_id varchar(36) NOT NULL REFERENCES stores(id), external_id varchar(160) NOT NULL, sequence integer NOT NULL, content_hash varchar(64) NOT NULL, payload jsonb NOT NULL, CONSTRAINT uq_inventory_receipt UNIQUE(store_id,external_id,sequence))"
    )
    op.execute(
        "CREATE INDEX ix_inventory_receipts_created_at ON inventory_receipts(created_at)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_receipts_store_id ON inventory_receipts(store_id)"
    )
    op.execute(
        "CREATE TABLE request_budgets (key varchar(100) NOT NULL, bucket_window integer NOT NULL, count integer NOT NULL, PRIMARY KEY(key,bucket_window))"
    )


def downgrade():
    for name in [
        "request_budgets",
        "inventory_receipts",
        "access_credentials",
        "source_rejections",
        "source_refreshes",
    ]:
        op.execute(f"DROP TABLE {name}")
    op.execute(
        "ALTER TABLE incidents DROP COLUMN closed_at, DROP COLUMN review_status, DROP COLUMN assigned_to"
    )
