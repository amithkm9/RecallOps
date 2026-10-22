"""Protect immutable provenance and require evidence for every decision."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE FUNCTION reject_provenance_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Provenance is append-only: %', TG_TABLE_NAME; END $$"""
    )
    for table in [
        "recall_versions",
        "recall_targets",
        "evidence",
        "decisions",
        "decision_evidence",
        "audit_log",
    ]:
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_provenance_mutation()"
        )
    op.execute("""CREATE FUNCTION decision_requires_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM decision_evidence WHERE decision_id=NEW.id) THEN RAISE EXCEPTION 'Decision requires contributing evidence'; END IF;
      IF EXISTS (SELECT 1 FROM decision_evidence de JOIN evidence e ON e.id=de.evidence_id WHERE de.decision_id=NEW.id AND e.incident_id<>NEW.incident_id) THEN RAISE EXCEPTION 'Decision evidence must belong to same incident'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE CONSTRAINT TRIGGER decision_has_evidence AFTER INSERT ON decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION decision_requires_evidence()"
    )


def downgrade():
    op.execute("DROP TRIGGER decision_has_evidence ON decisions")
    op.execute("DROP FUNCTION decision_requires_evidence()")
    for table in [
        "recall_versions",
        "recall_targets",
        "evidence",
        "decisions",
        "decision_evidence",
        "audit_log",
    ]:
        op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
    op.execute("DROP FUNCTION reject_provenance_mutation()")
