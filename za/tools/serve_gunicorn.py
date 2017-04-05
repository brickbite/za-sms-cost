import flask
import gunicorn.app.base
import logging.config
import os
import plac
import raven.contrib.flask
import sqlalchemy
import sqlalchemy.orm
import sys
import uuid
import werkzeug.contrib.profiler
import za
import za.biz as biz
import za.util

logger = za.get_logger(__name__)
sa = sqlalchemy


class StandardConfig(object):
    """Flask configuration defaults across all blueprints."""

    def __init__(self):
        """Initialize config from environment."""

        getenv = os.environ.get

        try:
            self.SERVER_NAME = os.environ["SERVER_NAME"]
        except KeyError:
            pass

        self.DEBUG = bool(getenv("FLASK_DEBUG"))
        self.SECRET_KEY = str(uuid.uuid4())
        self.SENTRY_DSN = getenv("SENTRY_DSN")
        self.DATABASE_URL = getenv("DATABASE_URL", za.DEFAULT_DATABASE_URL)
        self.ZA_CELERY_BROKER_URL = getenv(
            "ZA_CELERY_BROKER_URL",
            za.DEFAULT_CELERY_BROKER_URL)
        self.SESSION_COOKIE_HTTPONLY = True  # set cookie's "httponly" flag


def parse_registration(raw):
    """Parse a Flash blueprint registration request."""

    (blueprint_name, url_prefix) = raw.split(":")

    return (blueprint_name, url_prefix)


@plac.annotations(
    interface=("hostname", "option", "i", str),
    port=("port number", "option", "p", int),
    workers=("workers count", "option", "w", int),
    timeout=("worker timeout", "option", "t", int),
    profiling=("enable per-request profiling", "flag", "r"),
    echo_sql=("log emitted SQL", "flag", "s"),
    registrations=(
        "blueprint registrations",
        "positional",
        None,
        parse_registration))
def main(
        interface="127.0.0.1",
        port=8000,
        workers=1,
        timeout=120,
        profiling=False,
        echo_sql=False,
        *registrations):
    """Serve the specified set of blueprints.

    Blueprint registrations are of the form "blueprint_name:/url/prefix".
    """

    def on_starting(server):
        logger.info("server is starting")

        # set up logging
        logging.config.dictConfig({
            "version": 1,
            "incremental": False,
            "disable_existing_loggers": False,
            "formatters": {
                "concise": {
                    "datefmt": None,
                    "format": "%(asctime)s [%(process)d] %(message)s"}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "level": "NOTSET",
                    "formatter": "concise",
                    "stream": sys.stdout}},
            "loggers": {
                "": {
                    "level": "INFO",
                    "handlers": ["stdout"]},
                "gunicorn.access": {
                    # used for access messages (e.g., "POST /url")
                    "level": "INFO",
                    "handlers": []},
                "gunicorn.error": {
                    # used for server messages (e.g., "worker started")
                    "level": "INFO",
                    "handlers": []}}})

        za.configure_logging_sentry()

        logger.info("logging configured")

    def when_ready(server):
        logger.info("server is ready")

    class GunicornServer(gunicorn.app.base.Application):
        """Gunicorn server with custom configuration.

        Instantiated in the parent; `load()` is then called, post-fork, in each
        child.
        """

        def init(self, parser, opts, args):
            logconfig_name = "logging_gunicorn_reset.conf"

            return {
                "logconfig": za.util.get_package_file_path(logconfig_name),
                "access_log_format": "%(h)s %(r)s %(s)s (%(b)s bytes) '%(a)s'",
                "bind": "{0}:{1}".format(interface, port),
                "workers": workers,
                "timeout": timeout,
                "on_starting": on_starting,
                "when_ready": when_ready}

        def load(self):
            # create app and initialize config
            from za.blueprints.index import named_blueprint_factories

            app = flask.Flask("za")

            app.config.from_object(StandardConfig())

            # set up Sentry, if possible
            try:
                dsn = app.config["SENTRY_DSN"]
            except KeyError:
                dsn = None

            if bool(dsn):
                raven.contrib.flask.Sentry(app)

                logger.info("Sentry DSN provided; raven enabled")
            else:
                logger.info("Sentry DSN not provided; raven disabled")

            database_uri = app.config.get(
                "DATABASE_URL",
                za.DEFAULT_DATABASE_URL)
            engine = sa.create_engine(database_uri, echo=echo_sql)
            session = sa.orm.scoped_session(
                sa.orm.sessionmaker(bind=engine))

            biz.change_global_proxy(flask.g)

            @app.before_request
            def before_request():
                biz.set_global(session)

            @app.teardown_request
            def teardown_request(exception):
                biz.remove_global()

            logger.info("ORM session configured")

            # register specified blueprints
            for (blueprint_name, url_prefix) in registrations:
                # canonicalize URL prefix to avoid Flask pitfalls
                if len(url_prefix) >= 1 and url_prefix.endswith("/"):
                    # including a trailing slash breaks blueprint routes
                    # with a leading slash, i.e., virtually all standard
                    # routes
                    logger.warning(
                        "removing trailing slash from %s URL prefix",
                        blueprint_name)

                    url_prefix = url_prefix[:-1]

                logger.info(
                    "registering blueprint %s at URL prefix %s",
                    blueprint_name,
                    url_prefix)

                factory = named_blueprint_factories[blueprint_name]
                blueprint = factory(url_prefix)

                app.register_blueprint(blueprint, url_prefix=url_prefix)

            if profiling:
                return werkzeug.contrib.profiler.ProfilerMiddleware(
                    app,
                    sort_by=("time",),
                    restrictions=(16,))
            else:
                return app

    # run the server, temporarily overwriting argv to satisfy gunicorn
    # (there is no decent way of preventing it from consuming arguments)
    old_argv = sys.argv

    try:
        sys.argv = sys.argv[:1]

        server = GunicornServer()

        server.run()
    except:
        sys.argv = old_argv

script_main = za.util.script_main(main, __name__)
