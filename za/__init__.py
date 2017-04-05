import os
import sys
import logging
import flask
import jinja2
import sqlalchemy.orm.properties

from jinja2 import StrictUndefined

get_logger = logging.getLogger
logger = get_logger(__name__)


DEFAULT_DATABASE_URL = "postgres:///za_sandbox"
DEFAULT_CELERY_BROKER_URL = "redis://localhost:6379/0"


class Config(object):
    """Fetch config data from the appropriate source."""

    # XXX the semantics here are a mess
    # XXX where are we using the environment, and why?
    # XXX doesn't support non-str values, etc.
    # XXX should separate "flask server config" from "angaza logic config"?
    # XXX no way to temporarily push config values (for testing)

    def __init__(self, from_environ=True):
        # XXX "from_environ" doesn't override app context
        self._from_environ = from_environ
        self._values = {}

    def __getitem__(self, key):
        app = flask.current_app

        if bool(app):
            return app.config[key]
        elif self._from_environ:
            return os.environ[key]
        else:
            return self._values[key]

    def __setitem__(self, key, value):
        app = flask.current_app

        if bool(app):
            app.config[key] = value
        elif self._from_environ:
            os.environ[key] = value
        else:
            self._values[key] = value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

config = Config()


class Global(object):
    """Flask-independent globals object."""

    @property
    def Session(self):
        if bool(flask.g):
            return flask.g.Session
        elif bool(flask.current_app):
            return flask.current_app.Session
        else:
            return self._Session

g = Global()


def dictify_orm(extra=(), only=None, empty=(), uri=()):
    def dictify(mapped):
        # prepare property list
        if only is None:
            properties = list(extra)

            for p in mapped.__mapper__.iterate_properties:
                if isinstance(p, sqlalchemy.orm.properties.ColumnProperty):
                    properties.append(p.key)
        else:
            properties = only

        # retrieve properties
        d = {}

        for p in properties:
            assert p not in d

            d[p] = getattr(mapped, p)

        # add empty fields
        for p in empty:
            assert p not in d

            d[p] = None

        # add URI fields
        for p in uri:
            assert p not in d

            v = getattr(mapped, p)

            d[p] = v.uri if v else None

        # ...
        return d

    return dictify


def configure_logging_sentry():
    """Create and attach a Sentry logging handler."""

    sentry_dsn = os.environ.get("SENTRY_DSN")

    if sentry_dsn is not None:
        import raven.conf
        import raven.handlers.logging

        client = raven.Client(sentry_dsn)
        handler = raven.handlers.logging.SentryHandler(client)

        handler.setLevel(logging.ERROR)

        logging.root.addHandler(handler)

        logger.info("configured Sentry logging handler")


def configure_logging(stdout_level=logging.INFO):
    """Set up logging according to defaults."""

    # create std{out,err} handlers
    stdout_handler = logging.StreamHandler(sys.stdout)
    stderr_handler = logging.StreamHandler(sys.stderr)

    stdout_handler.setLevel(stdout_level)
    stderr_handler.setLevel(logging.ERROR)

    # define formatting
    line_format = "%(asctime)s %(levelname)s : %(message)s"
    date_format = "%H:%M:%S %y-%m-%d"
    formatter = logging.Formatter(line_format, date_format)

    stdout_handler.setFormatter(formatter)
    stderr_handler.setFormatter(formatter)

    # add the handlers
    logging.root.addHandler(stdout_handler)
    logging.root.addHandler(stderr_handler)

    logging.root.setLevel(logging.NOTSET)

    # other handlers
    configure_logging_sentry()


def configure_globals():
    configure_logging()


def render_template(template, **kwargs):
    jj = jinja2.Environment(loader=jinja2.PackageLoader("za", "templates"))
    template = jj.get_template(template)

    return template.render(**kwargs)


def render_sms_template_string(template_string,
                               account=None,
                               payment=None,
                               explanation=None,
                               keycode=None):
    def add_supported(key, obj, member):
        if obj is None:
            supported_dict[key] = jinja2.StrictUndefined(name=key)
            return

        # Support object args without members
        if member is None:
            supported_dict[key] = obj
            return

        var = getattr(obj, member)
        if var is None:
            supported_dict[key] = jinja2.StrictUndefined(name=key)
        else:
            supported_dict[key] = var

    supported_dict = {}
    add_supported('payment_amount', payment, 'amount')
    add_supported('keycode', keycode, None)
    add_supported('explanation', explanation, None)
    add_supported('account', account, None)
    add_supported('payment', payment, None)
    add_supported(
        'payment_due_date',
        account,
        'next_payment_due_localized_date_str')

    jj = jinja2.Environment(undefined=jinja2.StrictUndefined)
    template = jj.from_string(template_string)

    return template.render(**supported_dict)


def json_response(value=None, status=None, headers=None, mimetype=None):
    if value is None:
        response_value = None
    else:
        response_value = jsonify(value, indent=None)

    if mimetype is None:
        mimetype = "application/json"

    return flask.Response(
        response_value,
        status=status,
        headers=headers,
        mimetype=mimetype)

from .util import jsonify

#from . import util
#from . import external
