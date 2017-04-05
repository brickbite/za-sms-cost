# -*- coding: utf-8 -*-
import os
import bz2
import sys
import time
import json
import decimal
import enum
import logging
import datetime as dt
import functools
import traceback
import pwd
import gzip
import shutil
import tempfile
import subprocess
import contextlib
import dateutil.parser
import babel.dates
import pytz
import times
import sqlparse

logger = logging.getLogger(__name__)


#
# GENERAL IO
#

def get_package_file_path(name):
    """Path to a package file."""

    return os.path.join(os.path.dirname(__file__), "files", name)


@contextlib.contextmanager
def mkdtemp_scoped(prefix=None):
    """
    Create, and then delete, a temporary directory.
    """

    # provide a reasonable default prefix
    if prefix is None:
        prefix = "angaza.%s." % pwd.getpwuid(os.getuid())[0]

    # create the context
    path = None

    try:
        path = tempfile.mkdtemp(prefix=prefix)

        yield path
    finally:
        if path is not None:
            shutil.rmtree(path, ignore_errors=True)


def call_capturing(arguments, input=None, preexec_fn=None):
    """Fork a process and return its output and status code."""

    popened = None

    try:
        # launch the subprocess
        popened = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec_fn)

        # wait for its natural death
        (stdout, stderr) = popened.communicate(input)
    except:
        raised = Raised()

        if popened is not None and popened.poll() is None:
            try:
                popened.kill()
                popened.wait()
            except:
                pass

        raised.re_raise()
    else:
        return (stdout, stderr, popened.returncode)


def check_call_capturing(arguments, input=None, preexec_fn=None):
    """Fork a process and return its output."""

    (stdout, stderr, code) = call_capturing(arguments, input, preexec_fn)

    if code == 0:
        return (stdout, stderr)
    else:
        error = subprocess.CalledProcessError(code, arguments)

        error.stdout = stdout
        error.stderr = stderr

        raise error


def openz(path, mode="rb", closing=True):
    """Open a file with transparent [de]compression."""

    (_, extension) = os.path.splitext(path)

    if extension == ".bz2":
        file_ = bz2.BZ2File(path, mode)
    elif extension == ".gz":
        file_ = gzip.GzipFile(path, mode)
    elif extension == ".xz":
        raise NotImplementedError()
    else:
        file_ = open(path, mode)

    if closing:
        return contextlib.closing(file_)
    else:
        return file_


#
# EXCEPTION HELPERS
#

class Raised(object):
    """
    Store the currently-handled exception.

    The current exception must be saved before errors during error handling are
    handled, so that the original exception can be re-raised with its context
    information intact.
    """

    def __init__(self):
        (self.type, self.value, self.traceback) = sys.exc_info()

    def format(self):
        """Return a list of lines describing the exception."""

        return traceback.format_exception(
            self.type,
            self.value, self.traceback)

    def re_raise(self):
        """Re-raise the stored exception."""

        raise self.type, self.value, self.traceback

    def print_ignored(
            self,
            message="An error was unavoidably ignored:",
            file=sys.stderr):
        """
        Print an exception-was-ignored message.
        """

        file.write("\n%s\n" % message)
        file.write("".join(self.format()))
        file.write("\n")


def forever(rest=1.0):
    def decorator(function):
        @functools.wraps(function)
        def wrapper():
            while True:
                try:
                    function()
                except KeyboardInterrupt:
                    raise
                except:
                    logger.exception("error running %s", function)

                if rest is not None:
                    time.sleep(rest)

        wrapper()

    return decorator


#
# JSON HELPERS
#


class TaggedJSONEncoder(json.JSONEncoder):
    """Encoder for a simple custom type-tagged JSON format."""

    def default(self, o):
        to_json = getattr(o, "__json__", None)

        if to_json is None:
            for (type_, default_for) in self.defaults:
                if isinstance(o, type_):
                    return default_for(self, o)

            return json.JSONEncoder.default(self, o)
        else:
            return to_json()

    def default_decimal(self, o):
        return {
            "_type": "decimal",
            "value": str(o)}

    def default_datetime(self, o):
        if o.tzinfo is not None:
            raise ValueError("refusing to serialize a datetime with tzinfo")
        else:
            string = o.isoformat()

        return {
            "_type": "iso8601",
            "value": string}

    def default_timedelta(self, o):
        return {
            "_type": "timedelta",
            "value": str(o.total_seconds())}

    defaults = [
        (decimal.Decimal, default_decimal),
        (dt.datetime, default_datetime),
        (dt.timedelta, default_timedelta)]


class TaggedJSONDecoder(json.JSONDecoder):
    """Decoder for a simple custom type-tagged JSON format."""

    def __init__(self, *args, **kwargs):
        super(TaggedJSONDecoder, self).__init__(
            *args,
            object_hook=self.object_hook,
            **kwargs)

    def object_hook(self, o):
        type_name = o.get("_type")

        if type_name is not None:
            return self.decoders[type_name](self, o)
        else:
            return o

    def decode_decimal(self, o):
        return decimal.Decimal(o["value"])

    def decode_iso8601(self, o):
        d = dateutil.parser.parse(o["value"])

        if d.tzinfo is not None and d.tzinfo.tzname(d) != "UTC":
            raise ValueError("refusing to deserialize non-UTC datetime")

        return d.replace(tzinfo=None)

    def decode_timedelta(self, o):
        return dt.timedelta(seconds=float(o["value"]))

    decoders = {
        "decimal": decode_decimal,
        "iso8601": decode_iso8601,
        "timedelta": decode_timedelta}


def jsonify(value, sort_keys=True, indent=2, **kwargs):
    """Serialize a Python structure to JSON with type tags."""

    return json.dumps(
        value,
        cls=TaggedJSONEncoder,
        sort_keys=sort_keys,
        indent=indent,
        **kwargs)


def dejsonify(string):
    """Deserialize type-tagged JSON data."""

    return json.loads(string, cls=TaggedJSONDecoder)


#
# TIME HELPERS
#

def parse_time(string):
    """Parse the specified time string into a UTC datetime object.

    Times without an explicit timezone (such as those produced by calling
    `isoformat()` on a datetime returned from this function) are assumed UTC.
    Times with an explicit timezone are converted to UTC. Values returned do
    not have an explicit attached timezone, i.e., they follow the convention of
    the `times` library. For example:

    .. doctest::

        >>> parse_time('2014-10-31T15:52:56T00:00+01:00')
        datetime.datetime(2014, 10, 30, 23, 0, 56)

    :param string: time string to parse, ideally ISO 8601
    :type string: :class:`basestring`
    :return: parsed datetime with no explicit timezone
    :rtype: :class:`datetime.datetime`
    """

    parsed = times.parse(string)

    if parsed.tzinfo is not None:
        return times.to_universal(parsed)
    else:
        return parsed


def time_is_polite(utc, tz_name=None):
    """Is the specific UTC time polite in the specified zone?"""

    local = times.to_local(utc, tz_name)

    return 9 < local.hour < 22


def locale_to_timezone_str(locale):
    """Convert POSIX locale identifier to timezone name.

    XXX: Does not handle countries with multiple timezones very well, but
    this is not a huge problem today because everyone in the US is in Pacific
    and everywhere else Angaza operates is a single timezone country. Until
    we get to Kazakhstan...

    :param locale: POSIX locale identifier, without encoding, e.g. en_US
    :type locale: :class:`string`
    :return: string in target locale's timezone
    :rtype: :class:`string`
    """
    (lang, country) = locale.split("_")
    if country == 'US':
        tz_str = "America/Los_Angeles"
    else:
        tz_str = pytz.country_timezones(country)[0]

    return tz_str


def localized_date_str(utc, locale, format='medium'):
    """Convert a naive UTC datetime to a localized unicode string.

    We tend to work with UTC dates internally, and they should always
    be naive datetime objects; ie, without tzinfo attached.

    However, when displaying dates to the user, we should do so:
        a) in the local time zone
        b) using the appropriate localization format

    Examples:
     >>> print za.util.localized_date_str(times.now(), 'en_US', format='long')
     November 19, 2014
     >>> print za.util.localized_date_str(times.now(), 'en_US', format='short')
     11/19/14
     >>> print za.util.localized_date_str(times.now(), 'ur_PK', format='long')
     20 نومبر، 2014
     >>> print za.util.localized_date_str(times.now(), 'en_IN')
     20-Nov-2014

    :param utc: datetime object
    :type utc: :class:`datetime.datetime`
    :param locale: POSIX locale identifier, without encoding, e.g. en_US
    :type locale: :class:`string`
    :param format: babel.dates.format_* arg, e.g. short, medium, long, full
    :type format: :class:`string`
    :return: unicode string in target locale's timezone
    :rtype: :class:`unicode`
    """
    tz_str = locale_to_timezone_str(locale)

    # Add UTC tzinfo to naive UTC time
    utc_tz = pytz.utc.normalize(pytz.utc.localize(utc))

    # Now conver to local datetime using astimezone()
    local_tz = pytz.timezone(tz_str)
    local_date = local_tz.normalize(utc_tz.astimezone(local_tz))

    return babel.dates.format_date(local_date, format=format, locale=locale)


@enum.unique
class Currency(enum.Enum):
    """Standard unit of money.

    Instances can be referenced via ISO 4217 currency codes, e.g.,
    `Currency.EUR`.
    """

    locals().update({
        code: object() for code in list(babel.Locale("en", "US").currencies)})


def locale_currency(locale):
    """Convert locale to Currency

    :param locale: POSIX locale identifier, without encoding, e.g. en_US
    :type locale: :class:`string:
    :return: currency of input locale
    :rtype: :class:`Currency`
    """

    # TODO use get_territory_currencies() when babel 2.0 is released
    territory_currencies = {
        "GH": Currency.GHS,
        "IN": Currency.INR,
        "KE": Currency.KES,
        "MW": Currency.MWK,
        "PK": Currency.PKR,
        "TZ": Currency.TZS,
        "UG": Currency.UGX,
        "US": Currency.USD,
        "ZM": Currency.ZMW}
    group_locale = babel.Locale.parse(locale)

    return territory_currencies[group_locale.territory]


#
# OTHER HELPERS
#

def script_main(main, name):
    def run_script_main():
        import plac

        plac.call(main)

    if name == "__main__":
        run_script_main()

    return run_script_main


def reformat_sql(expression):
    """Parse and reformat a SQL expression, for pretty-printing.

    This function performs no validation, so placeholder values are acceptable.

    For example:

    >>> print reformat_sql("select * from foo where bar")
    SELECT *
    FROM foo
    WHERE bar

    :param expression: expression to reformat
    :type expression: `basestring` or SQLAlchemy object, e.g.,
        :class:`sqlalchemy.orm.Query`
    :return: reformatted expression
    :rtype: `str`
    """

    return sqlparse.format(
        str(expression),
        reindent=True,
        keyword_case="upper")


def memoize(warn_at_size=1024):
    """Cache identical calls to the wrapped `callable` object.

    Builds a new decorator. Example:

    >>> a = []
    >>> @memoize()
    ... def foo(x):
    ...     a.append(x)
    ...
    >>> foo(42)
    >>> foo(42)
    >>> foo(43)
    >>> a
    [42, 43]

    :param warn_at_size: log a warning if the cache exceeds this count
    :type warn_at_size: `int`
    :return: generated decorator
    :rtype: `function`
    """

    def decorator(function):
        unique_calls = {}

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))

            try:
                result = unique_calls[key]
            except KeyError:
                result = unique_calls[key] = function(*args, **kwargs)

            if len(unique_calls) > warn_at_size:
                logger.warning("memoization cache exceeds reasonable size")

            return result

        return wrapper

    return decorator
