from alembic import context
from sqlalchemy import text
from app.core.database import Base, engine
from app import models

config = context.config
target_metadata = Base.metadata


def offline():
    from app.core.config import settings

    context.configure(
        url=settings.db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def online():
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(4242000)"))
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(4242000)"))
            connection.commit()


if context.is_offline_mode():
    offline()
else:
    online()
