import os
import sqlalchemy as sa
import za
import za.biz as biz
import za.test.data

logger = za.get_logger(__name__)


#
# PACKAGE FIXTURE
#

def setup_package():
    # make sure that we do *not* have live AWS or Twilio access
    assert "AWS_ACCESS_KEY_ID" not in os.environ


def teardown_package():
    pass


#
# INNER SUPPORT
#

class FakeServiceFixture(object):
    """Base for actual test fixtures."""

    _static_connection = None

    def setup(self):
        # prepare the database
        echo = os.environ.get("ZA_TEST_ECHO_SQL") == "YES"
        url = os.environ.get("ZA_TEST_DB_URL", "postgres:///za_test")

        if FakeServiceFixture._static_connection is None:
            # connect to test database
            engine = sa.create_engine(url, echo=echo)
            connection = engine.connect()

            # verify that test database is empty
            reflected = sa.MetaData(bind=engine)

            reflected.reflect()

            if len(reflected.tables) > 0:
                raise RuntimeError("test database is not empty")

            # emit DDL inside an (outer) transaction
            connection.begin()

            za.test.data.create_schema(connection)

            # preserve connection across tests
            FakeServiceFixture._static_connection = connection
        else:
            # retrieve preserved connection
            connection = FakeServiceFixture._static_connection

        # prepare database session
        self.transaction = connection.begin_nested()
        self.session = sa.orm.scoped_session(
            sa.orm.sessionmaker(bind=connection))
        self.fake = za.test.data.SyntheticData(self.session)

        biz.set_global(self.session)

        # apply default configuration
        za.config._from_environ = False

        # run inner setup routine
        try:
            self.inner_setup()
        except:
            logger.error("error raised by inner setup; tearing down")

            self.teardown()

            raise

    def inner_setup(self):
        pass

    def teardown(self):
        # disconnect from the database
        logger.info("rolling back any pending transaction(s)")

        biz.remove_global()

        self.transaction.rollback()

        # run inner teardown tasks(s)
        self.inner_teardown()

    def inner_teardown(self):
        pass
