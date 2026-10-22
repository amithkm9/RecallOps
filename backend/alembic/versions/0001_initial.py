"""Initial PostgreSQL schema, frozen from the v1 model contract."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE stores (\n\tname VARCHAR(160) NOT NULL, \n\tmode VARCHAR(16) NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (mode IN ('live','replay','evaluation'))\n)\n\n"
    )
    op.execute("CREATE INDEX ix_stores_created_at ON stores (created_at)")
    op.execute("CREATE INDEX ix_stores_mode ON stores (mode)")
    op.execute(
        "\nCREATE TABLE recalls (\n\tsource_id VARCHAR(100) NOT NULL, \n\treference VARCHAR(100) NOT NULL, \n\tcurrent_version_id VARCHAR(36), \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (source_id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_recalls_created_at ON recalls (created_at)")
    op.execute("CREATE INDEX ix_recalls_reference ON recalls (reference)")
    op.execute(
        "\nCREATE TABLE evaluation_runs (\n\tsample_size INTEGER NOT NULL, \n\tbenchmark TEXT NOT NULL, \n\tresults JSONB NOT NULL, \n\tcases JSONB NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_evaluation_runs_created_at ON evaluation_runs (created_at)"
    )
    op.execute(
        "\nCREATE TABLE source_state (\n\tid VARCHAR(50) NOT NULL, \n\tlast_successful_sync TIMESTAMP WITH TIME ZONE, \n\tlast_attempt TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tdetails JSONB NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE inventory_lots (\n\tstore_id VARCHAR(36) NOT NULL, \n\tsku VARCHAR(120) NOT NULL, \n\tproduct_name VARCHAR(500) NOT NULL, \n\tgtin VARCHAR(14) NOT NULL, \n\tlot VARCHAR(300), \n\tlot_key VARCHAR(300) NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tsupplier VARCHAR(300) NOT NULL, \n\texpires_on DATE, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_inventory_identity UNIQUE (store_id, sku, lot_key), \n\tCHECK (quantity >= 0), \n\tCONSTRAINT ck_gtin_format CHECK (gtin ~ '^[0-9]{8}$|^[0-9]{12,14}$'), \n\tFOREIGN KEY(store_id) REFERENCES stores (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_inventory_lots_created_at ON inventory_lots (created_at)"
    )
    op.execute("CREATE INDEX ix_inventory_lots_gtin ON inventory_lots (gtin)")
    op.execute("CREATE INDEX ix_inventory_lots_store_id ON inventory_lots (store_id)")
    op.execute(
        "\nCREATE TABLE recall_versions (\n\trecall_id VARCHAR(36) NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tofficial_version VARCHAR(30) NOT NULL, \n\tproduct_name VARCHAR(1000) NOT NULL, \n\tbrand VARCHAR(500) NOT NULL, \n\tcategory VARCHAR(300) NOT NULL, \n\tpublished_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsource_updated_at TIMESTAMP WITH TIME ZONE, \n\tsource_url TEXT NOT NULL, \n\treason TEXT NOT NULL, \n\trisk TEXT NOT NULL, \n\traw JSONB NOT NULL, \n\tparse_warnings JSONB NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_recall_content UNIQUE (recall_id, content_hash), \n\tFOREIGN KEY(recall_id) REFERENCES recalls (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_recall_versions_created_at ON recall_versions (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_recall_versions_recall_id ON recall_versions (recall_id)"
    )
    op.execute(
        "\nCREATE TABLE incidents (\n\tstore_id VARCHAR(36) NOT NULL, \n\trecall_id VARCHAR(36) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_incident_store_recall UNIQUE (store_id, recall_id), \n\tFOREIGN KEY(store_id) REFERENCES stores (id), \n\tFOREIGN KEY(recall_id) REFERENCES recalls (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_incidents_recall_id ON incidents (recall_id)")
    op.execute("CREATE INDEX ix_incidents_created_at ON incidents (created_at)")
    op.execute("CREATE INDEX ix_incidents_store_id ON incidents (store_id)")
    op.execute("CREATE INDEX ix_incidents_status ON incidents (status)")
    op.execute(
        "\nCREATE TABLE recall_targets (\n\trecall_version_id VARCHAR(36) NOT NULL, \n\tgtin VARCHAR(14) NOT NULL, \n\tscope JSONB NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(recall_version_id) REFERENCES recall_versions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_recall_targets_gtin ON recall_targets (gtin)")
    op.execute(
        "CREATE INDEX ix_recall_targets_recall_version_id ON recall_targets (recall_version_id)"
    )
    op.execute(
        "CREATE INDEX ix_recall_targets_created_at ON recall_targets (created_at)"
    )
    op.execute(
        "\nCREATE TABLE evidence (\n\tincident_id VARCHAR(36) NOT NULL, \n\tinventory_lot_id VARCHAR(36), \n\trecall_version_id VARCHAR(36), \n\tkind VARCHAR(40) NOT NULL, \n\tlabel VARCHAR(300) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tsource_url TEXT, \n\tsynthetic BOOLEAN NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_evidence_content UNIQUE (incident_id, fingerprint), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tFOREIGN KEY(inventory_lot_id) REFERENCES inventory_lots (id), \n\tFOREIGN KEY(recall_version_id) REFERENCES recall_versions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_evidence_incident_id ON evidence (incident_id)")
    op.execute(
        "CREATE INDEX ix_evidence_inventory_lot_id ON evidence (inventory_lot_id)"
    )
    op.execute("CREATE INDEX ix_evidence_created_at ON evidence (created_at)")
    op.execute(
        "\nCREATE TABLE events (\n\tidempotency_key VARCHAR(200) NOT NULL, \n\tincident_id VARCHAR(36), \n\tstore_id VARCHAR(36), \n\tkind VARCHAR(60) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlocked_at TIMESTAMP WITH TIME ZONE, \n\terror TEXT, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (idempotency_key), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tFOREIGN KEY(store_id) REFERENCES stores (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_outbox_queue ON events (status, available_at)")
    op.execute("CREATE INDEX ix_events_status ON events (status)")
    op.execute("CREATE INDEX ix_events_created_at ON events (created_at)")
    op.execute("CREATE INDEX ix_events_incident_id ON events (incident_id)")
    op.execute("CREATE INDEX ix_events_store_id ON events (store_id)")
    op.execute(
        "\nCREATE TABLE audit_log (\n\tincident_id VARCHAR(36), \n\tstore_id VARCHAR(36), \n\tkind VARCHAR(80) NOT NULL, \n\tactor VARCHAR(80) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tFOREIGN KEY(store_id) REFERENCES stores (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_audit_log_created_at ON audit_log (created_at)")
    op.execute("CREATE INDEX ix_audit_log_store_id ON audit_log (store_id)")
    op.execute("CREATE INDEX ix_audit_log_incident_id ON audit_log (incident_id)")
    op.execute(
        "\nCREATE TABLE replays (\n\tstore_id VARCHAR(36) NOT NULL, \n\tincident_id VARCHAR(36) NOT NULL, \n\tstep INTEGER NOT NULL, \n\tevents JSONB NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (store_id), \n\tFOREIGN KEY(store_id) REFERENCES stores (id), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_replays_created_at ON replays (created_at)")
    op.execute(
        "\nCREATE TABLE agent_runs (\n\tincident_id VARCHAR(36) NOT NULL, \n\tevent_id VARCHAR(36) NOT NULL, \n\trecall_version_id VARCHAR(36) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tactive_node VARCHAR(80) NOT NULL, \n\tllm_mode VARCHAR(60) NOT NULL, \n\tstate JSONB NOT NULL, \n\tsteps JSONB NOT NULL, \n\tsummary TEXT NOT NULL, \n\tdraft TEXT NOT NULL, \n\tlatency_ms FLOAT, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tUNIQUE (event_id), \n\tFOREIGN KEY(event_id) REFERENCES events (id), \n\tFOREIGN KEY(recall_version_id) REFERENCES recall_versions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_agent_runs_incident_id ON agent_runs (incident_id)")
    op.execute("CREATE INDEX ix_agent_runs_created_at ON agent_runs (created_at)")
    op.execute(
        "\nCREATE TABLE decisions (\n\tincident_id VARCHAR(36) NOT NULL, \n\trun_id VARCHAR(36) NOT NULL, \n\tinventory_lot_id VARCHAR(36) NOT NULL, \n\trecall_version_id VARCHAR(36) NOT NULL, \n\tverdict VARCHAR(30) NOT NULL, \n\texplanation TEXT NOT NULL, \n\taction VARCHAR(60) NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tlot VARCHAR(300), \n\tprevious_verdict VARCHAR(30), \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_run_decision UNIQUE (run_id, inventory_lot_id), \n\tCHECK (verdict IN ('affected','unaffected','review','conflict')), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tFOREIGN KEY(run_id) REFERENCES agent_runs (id), \n\tFOREIGN KEY(inventory_lot_id) REFERENCES inventory_lots (id), \n\tFOREIGN KEY(recall_version_id) REFERENCES recall_versions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_decisions_run_id ON decisions (run_id)")
    op.execute("CREATE INDEX ix_decisions_created_at ON decisions (created_at)")
    op.execute("CREATE INDEX ix_decisions_incident_id ON decisions (incident_id)")
    op.execute(
        "\nCREATE TABLE decision_evidence (\n\tdecision_id VARCHAR(36) NOT NULL, \n\tevidence_id VARCHAR(36) NOT NULL, \n\tPRIMARY KEY (decision_id, evidence_id), \n\tFOREIGN KEY(decision_id) REFERENCES decisions (id), \n\tFOREIGN KEY(evidence_id) REFERENCES evidence (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE inventory_holds (\n\tincident_id VARCHAR(36) NOT NULL, \n\tinventory_lot_id VARCHAR(36) NOT NULL, \n\tdecision_id VARCHAR(36) NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\treleased_at TIMESTAMP WITH TIME ZONE, \n\treleased_by VARCHAR(120), \n\trelease_reason TEXT, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (quantity > 0), \n\tFOREIGN KEY(incident_id) REFERENCES incidents (id), \n\tFOREIGN KEY(inventory_lot_id) REFERENCES inventory_lots (id), \n\tFOREIGN KEY(decision_id) REFERENCES decisions (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_inventory_holds_inventory_lot_id ON inventory_holds (inventory_lot_id)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_holds_created_at ON inventory_holds (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_holds_incident_id ON inventory_holds (incident_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_hold ON inventory_holds (incident_id, inventory_lot_id) WHERE status = 'active'"
    )
    op.execute(
        "ALTER TABLE recalls ADD CONSTRAINT fk_recall_current_version FOREIGN KEY(current_version_id) REFERENCES recall_versions (id)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS source_state CASCADE")
    op.execute("DROP TABLE IF EXISTS replays CASCADE")
    op.execute("DROP TABLE IF EXISTS evaluation_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS inventory_holds CASCADE")
    op.execute("DROP TABLE IF EXISTS decision_evidence CASCADE")
    op.execute("DROP TABLE IF EXISTS decisions CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS evidence CASCADE")
    op.execute("DROP TABLE IF EXISTS incidents CASCADE")
    op.execute("DROP TABLE IF EXISTS recall_targets CASCADE")
    op.execute("DROP TABLE IF EXISTS recall_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS recalls CASCADE")
    op.execute("DROP TABLE IF EXISTS inventory_lots CASCADE")
    op.execute("DROP TABLE IF EXISTS stores CASCADE")
