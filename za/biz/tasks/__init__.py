import os
import abc
import sqlalchemy
import sqlalchemy.orm
import celery
import celery.signals
import za.biz
import za.biz.accounts

from za.celery import celery as za_celery

sa = sqlalchemy
biz = za.biz
logger = za.get_logger(__name__)


class Rule(celery.Task):
    """Base for ECA rules."""

    abstract = True

    @abc.abstractmethod
    def check(self, target):
        raise NotImplementedError()

    @abc.abstractmethod
    def execute(self, target):
        raise NotImplementedError()

    def run(self, target_id):
        target = biz.accounts.SMSMessage.from_id(target_id)
        logger.info("checking %s (in run)", target)
        if self.check(target):
            logger.info("%s check true; firing now (in run)", self)
            self.execute(target)
        else:
            logger.info("%s check false (in run)", self)

        biz.commit()


@celery.signals.worker_process_init.connect
def on_worker_process_init(*args, **kwargs):
    """Prepare global state in worker process."""

    logger.debug("worker process init; pid %i", os.getpid())

    # prepare error reporting
    za.configure_logging_sentry()

    # prepare SQLAlchemy session
    logger.debug("initializing SA session (%s; %s)", args, kwargs)

    engine = sa.create_engine(
        za.config.get("DATABASE_URL", za.DEFAULT_DATABASE_URL),
        echo=False,
        isolation_level="REPEATABLE READ")
    session = sa.orm.scoped_session(sa.orm.sessionmaker(bind=engine))

    biz.set_global(session)


@celery.signals.task_postrun.connect
def on_task_postrun(*args, **kwargs):
    """Clean up global state after task completion."""

    logger.debug("cleaning up after task (%s; %s)", args, kwargs)

    biz.remove()
