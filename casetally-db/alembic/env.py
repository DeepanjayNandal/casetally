# from logging.config import fileConfig

# from sqlalchemy import engine_from_config
# from sqlalchemy import pool

# from alembic import context

# # this is the Alembic Config object, which provides
# # access to the values within the .ini file in use.
# config = context.config

# # Interpret the config file for Python logging.
# # This line sets up loggers basically.
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

# # add your model's MetaData object here
# # for 'autogenerate' support
# # from myapp import mymodel
# # target_metadata = mymodel.Base.metadata
# target_metadata = None

# # other values from the config, defined by the needs of env.py,
# # can be acquired:
# # my_important_option = config.get_main_option("my_important_option")
# # ... etc.


# def run_migrations_offline() -> None:
#     """Run migrations in 'offline' mode.

#     This configures the context with just a URL
#     and not an Engine, though an Engine is acceptable
#     here as well.  By skipping the Engine creation
#     we don't even need a DBAPI to be available.

#     Calls to context.execute() here emit the given string to the
#     script output.

#     """
#     url = config.get_main_option("sqlalchemy.url")
#     context.configure(
#         url=url,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#     )

#     with context.begin_transaction():
#         context.run_migrations()


# def run_migrations_online() -> None:
#     """Run migrations in 'online' mode.

#     In this scenario we need to create an Engine
#     and associate a connection with the context.

#     """
#     connectable = engine_from_config(
#         config.get_section(config.config_ini_section, {}),
#         prefix="sqlalchemy.",
#         poolclass=pool.NullPool,
#     )

#     with connectable.connect() as connection:
#         context.configure(
#             connection=connection, target_metadata=target_metadata
#         )

#         with context.begin_transaction():
#             context.run_migrations()


# if context.is_offline_mode():
#     run_migrations_offline()
# else:
#     run_migrations_online()

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ===================================================================
# Fix Python path for Docker (critical when running inside container)
# ===================================================================
# In Docker, code is at /app, but Alembic runs from /app/alembic
# This ensures the root package is importable
if os.path.exists("/app"):
    sys.path.insert(0, "/app")
else:
    # For local development, add the parent directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ===================================================================
# Import your SQLAlchemy Base and models
# ===================================================================
# Import Base from root __init__.py and models to register with metadata
try:
    from __init__ import Base
    # Import all models so they register with Base.metadata
    import models  # noqa: F401
except ImportError as e:
    raise ImportError(
        "Could not import database models. Check your project structure and PYTHONPATH. "
        "Error: " + str(e)
    )

# ===================================================================
# Alembic Config object
# ===================================================================
config = context.config

# ===================================================================
# Logging configuration
# ===================================================================
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ===================================================================
# Override DB URL from environment (critical for Docker)
# ===================================================================
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
else:
    # Fallback warning if no URL provided
    print("Warning: DATABASE_URL not set. Using alembic.ini default.")

# ===================================================================
# Metadata for autogenerate
# ===================================================================
target_metadata = Base.metadata


# ===================================================================
# Offline mode
# ===================================================================
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ===================================================================
# Online mode (default)
# ===================================================================
def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()