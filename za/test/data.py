import logging
import random
import sqlalchemy as sa
import za
import za.biz as biz
import za.biz.accounts

logger = za.get_logger(__name__)


class SyntheticData(object):
    def __init__(self, session):
        self._session = session


def fill_dev_db(session):
    """Initialize the empty development database."""

    return SyntheticData(session)


def wipe_database(connection):
    """Wipe all content in the database.

    Implemented here because the simple `MetaData.drop_all()` method does not
    handle circular relationships between tables.
    """

    inspector = sa.engine.reflection.Inspector.from_engine(connection)
    metadata = sa.MetaData()
    all_foreign_keys = []
    tables = []

    for table_name in inspector.get_table_names():
        table_foreign_keys = []

        for key in inspector.get_foreign_keys(table_name):
            if key.get("name") is None:
                continue

            table_foreign_keys.append(
                sa.ForeignKeyConstraint((), (), name=key["name"]))

        table = sa.Table(table_name, metadata, *table_foreign_keys)

        tables.append(table)

        all_foreign_keys.extend(table_foreign_keys)

    for key in all_foreign_keys:
        logger.debug("dropping foreign key %s", key)

        connection.execute(sa.schema.DropConstraint(key))

    for table in tables:
        logger.debug("dropping table %s", table)

        connection.execute(sa.schema.DropTable(table))


def create_schema(connection):
    """Populate database schema, if necessary.

    Attempts to create only aspects of the schema which are missing.

    :param connection: connection-like object with an `execute()` method
    :type connection: :class:`sa.engine` or other
    """

    connection.execute("CREATE EXTENSION IF NOT EXISTS hstore")

    biz.DomainBase.metadata.create_all(connection)


def fill(name, url, echo=True, wipe=False, must_be_clean=False):
    """Populate a database with synthetic data."""

    random.seed(15551234567)

    # set up SQL engine
    logger.info("setting up SQL engine")

    if echo:
        za.get_logger("sqlalchemy.engine").setLevel(logging.INFO)

    engine = sa.create_engine(url, echo=echo)

    with engine.begin() as connection:
        # wipe if requested
        if wipe:
            logger.warning("wiping database")

            wipe_database(connection)

        # check for cleanliness if requested
        if must_be_clean:
            logger.info("verifying that existing database is empty")

            reflected = sa.MetaData(bind=connection)

            reflected.reflect()

            if len(reflected.tables) > 0:
                raise RuntimeError("database is not empty")

        # prepare the session
        create_schema(connection)

        session = sa.orm.scoped_session(sa.orm.sessionmaker(bind=connection))

        # populate the database
        fill_methods = {"dev": fill_dev_db}

        with biz.global_context(session=session):
            if name is None:
                logger.info("leaving database empty")

                data = SyntheticData(session)
            else:
                logger.info("populating %s database", name)

                data = fill_methods[name](session)

                logger.info("done populating database")

    # ...
    return (engine, session, data)
