import os
import json
import uuid
import time
import urllib
import unicodedata
import itsdangerous
import sqlalchemy
import sqlalchemy.sql as sql
import flask
import flask.views
import werkzeug.wsgi
import werkzeug.routing
import werkzeug.exceptions
import za.biz.accounts

from za.biz.accounts import SMSMessageRole

sa = sqlalchemy
biz = za.biz
logger = za.get_logger(__name__)


class AuthenticationError(Exception):
    def __init__(self, code=None):
        super(AuthenticationError, self).__init__()

        self.code = code


class AuthorizationError(Exception):
    pass


class FancyRequestError(Exception):
    def __init__(self, code, **kwargs):
        super(FancyRequestError, self).__init__()

        self.code = code
        self.context = kwargs


class AnonymousActor(object):
    pass


class LoginToken(object):
    def __init__(self, string, format_="token"):
        if format_ not in ["token"]:
            raise ValueError()

        self._string = string
        self._format = format_

    @property
    def string(self):
        return self._string

    @property
    def format(self):
        return self._format

    @property
    def actor(self):
        signer = itsdangerous.TimestampSigner(
            flask.current_app.config["SECRET_KEY"])
        self._qualified_id = signer.unsign(self._string)

        return biz.accounts.get_named_entity(self._qualified_id)

    @staticmethod
    def generate(actor):
        """Generate new login token for specified actor."""

        if isinstance(actor, biz.accounts.User):
            qualified_id = "US{}".format(actor.id)
        else:
            assert False

        signer = itsdangerous.TimestampSigner(
            flask.current_app.config["SECRET_KEY"])

        return LoginToken(signer.sign(qualified_id))


def decode_auth_value(encoded_value):
    """Decode the value part of transferred username or password information.

    See :func:`authenticated_actor()` for context.

    :param encoded: the raw encoded value part
    :type encoded: :class:`bytes`
    :return: the decoded value part
    :rtype: :class:`unicode`
    """

    return unicodedata.normalize(
        "NFKC",
        urllib.unquote(encoded_value).decode("utf-8"))


def authname_parts(full_username):
    """Unpack an authentication username."""

    parts = full_username.split("=")

    if len(parts) != 2:
        raise AuthenticationError()

    (namespace, username) = parts

    return (namespace, decode_auth_value(username))


def authname_actor(namespace, username):
    """Look up the actor associated with an authentication username pair."""

    if namespace == "op":
        try:
            return biz.accounts.User.from_username(username)
        except sa.orm.exc.NoResultFound:
            raise AuthenticationError()
    else:
        raise ValueError()


def authpass_parts(full_password):
    """Unpack an authentication password."""

    parts = full_password.split("=")

    if len(parts) == 1:
        passtype = "raw"
        encoded_password = full_password
    elif len(parts) == 2:
        (passtype, encoded_password) = parts
    else:
        raise AuthenticationError()

    return (passtype, decode_auth_value(encoded_password))


def authpass_matches(passtype, password, actor, require_fresh=False):
    """Does the specified full password match?"""

    if isinstance(actor, biz.accounts.User):
        if passtype == "raw":
            return actor.password_matches(password)
        elif passtype == "token":
            token = LoginToken(password, format_=passtype)

            return token.actor.id == actor.id
        else:
            raise ValueError("unrecognized authpass type")
    else:
        raise ValueError("unrecognized actor type")


def authenticated_actor(require_fresh=False):
    """Retrieve the entity authenticated for the current request, if any.

    This authentication scheme is built on top of HTTP Basic, as follows.

    Per the standard, authentication information is passed as a (username,
    password) pair. These components are separated by a colon, Base64-encoded,
    and placed in the "Authorization" header of the HTTP request.

    http://en.wikipedia.org/wiki/Basic_access_authentication

    Here, both the username and password components consist of a *type* and a
    *value*. The type designates what kind of authentication information is
    provided, e.g., "raw" for password information. The value carries the
    actual authentication information, e.g., the password itself.

    The type is restricted to pure alphanumeric ASCII. The value is UTF-8- and
    URL-encoded (see :func:`decode_auth_value()`) and is NFKC-normalized on the
    server side. In the transferred authentication data, the type and value are
    joined together with an "=" separator. If no type is present in the
    password component, the type is implicitly "raw" and no "=" is present.

    :param require_fresh: is a raw password required?
    :type require_fresh: :class:`bool`
    :return: the authenticated user, or anonymous
    :rtype: :class:`biz.accounts.User` or :class:`AnonymousActor`
    """

    # extract basic auth info and handle anonymity
    authorization = flask.request.authorization

    if authorization is None:
        return AnonymousActor()

    full_username = authorization["username"]
    full_password = authorization["password"]

    # unpack auth info
    (nametype, username) = authname_parts(full_username)
    (passtype, password) = authpass_parts(full_password)

    # check auth info
    actor = authname_actor(nametype, username)
    credentials_ok = authpass_matches(
        passtype,
        password,
        actor,
        require_fresh=require_fresh)

    # TODO: Should we raise an AuthorizationError instead?
    if not actor.login_access_enabled:
        logger.info("Actor is suspended.")
        raise AuthenticationError("access_suspended")

    if credentials_ok:
        return actor
    else:
        raise AuthenticationError()


def request_arg_or(name, default=None, type_=str):
    """
    Return the named request argument, or the default.

    Subtly different than MultDict.get(), since we want to toss an error
    if value parsing fails; we don't want to silently return the default.
    """

    value = flask.request.args.get(name)

    if value is None:
        return default
    elif value == "*":
        return default
    else:
        try:
            return type_(value)
        except ValueError:
            flask.abort(400)


def request_args_or(name, default=None, type_=str):
    """Return the named request arguments, or the default.

    Assumes that multiple arguments are semicolon-separated.
    """

    value = flask.request.args.get(name)

    if value is None:
        return default
    elif value == "*":
        return default
    elif len(value) == 0:
        return []
    else:
        try:
            return map(type_, value.replace(";", ",").split(","))
        except ValueError:
            flask.abort(400)


def apply_query_sorting(query, sort_by, columns, descending=None):
    """Apply order-by criteria according to a sort specification.

    Example:

    >>> query = sa.orm.Query("something")
    >>> print apply_query_sorting(
    ...     query,
    ...     ["bar_name", "-bob_name"],
    ...     {"bar_name": "bar", "bob_name": "bob"})
    SELECT something ORDER BY bar, bob DESC

    The `descending` parameter is provided only for backwards compatibility
    with early sort formats.

    :param query: query to sort
    :type query: :class:`sqlalchemy.orm.Query`
    :param sort_by: list of columns to sort by
    :type sort_by: :class:`list`
    :param descending: should all columns be sorted descending?
    :type descending: `bool`
    :deprecated: descending
    :param columns: map of named sort criteria
    :type columns: :class:`list`
    :return: sorted query
    :rtype: :class:`sqlalchemy.orm.Query`
    """

    for sort in sort_by:
        criterion = columns[sort.lstrip("-")]

        if descending or sort.startswith("-"):
            criterion = sa.sql.desc(criterion)

        query = query.order_by(criterion)

    return query


#
# URI HELPERS
#

def external_url_for(name, *args, **kwargs):
    return flask.url_for(
        name,
        *args,
        _external=True,
        _scheme="https",
        **kwargs)


class URITemplateValue(object):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return "_TEMPLATE_{}_".format(self.name)


def url_template_for(name, _optional=[], _fixed={}, **kwargs):
    # generate a URL with placeholders for required parameters
    combined_kwargs = dict(_fixed)

    for (i, k) in enumerate(kwargs):
        combined_kwargs[k] = URITemplateValue(i)

    raw_url = external_url_for(name, **combined_kwargs)

    # then replace each placeholder with {param}
    for (k, v) in kwargs.iteritems():
        placeholder = str(combined_kwargs[k])
        parameter = "{{{}}}".format(v)

        raw_url = raw_url.replace(placeholder, parameter)

    # then add optional query parameters, if any
    if len(_optional) > 0:
        raw_url += "{{{character}{arguments}}}".format(
            character="&" if len(combined_kwargs) > 0 else "?",
            arguments=",".join(_optional))

    return raw_url


def add_url_template_support_to_app(app):
    # TODO handle this more elegantly
    def make_template_converter(wrapped):
        class TemplateConverterWrapper(wrapped):
            def to_python(self, value):
                return wrapped.to_python(self, value)

            def to_url(self, value):
                if isinstance(value, URITemplateValue):
                    return str(value)
                else:
                    return wrapped.to_url(self, value)

        return TemplateConverterWrapper

    # hack converters to pass through "template value" parameters
    for (converter_name, default_converter) in app.url_map.converters.items():
        app.url_map.converters[converter_name] = make_template_converter(
            default_converter)


#
# REPRESENTATIONS
#

class LinkMedia(object):
    def __init__(self, href, templated=False):
        self.href = href
        self.templated = templated

    def __json__(self):
        document = {"href": self.href}

        if self.templated:
            document["templated"] = True

        return document


class CollectionMedia(object):
    def __init__(
            self,
            url,
            items,
            next_url=None,
            prev_url=None,
            offset=None,
            limit=None,
            total_count=None):
        self.url = url
        self.items = items
        self.next_url = next_url
        self.prev_url = prev_url
        self.offset = 0 if offset is None else offset
        self.limit = len(items) if limit is None else limit
        self.total_count = len(items) if total_count is None else total_count

    def __json__(self):
        document = {
            "_links": {
                "self": LinkMedia(self.url),
                "type": LinkMedia("/types/collection"),
                "item": [LinkMedia(v.url) for v in self.items]},
            "_embedded": {
                "item": self.items},
            "offset": self.offset,
            "limit": self.limit,
            "total_count": self.total_count}

        if self.next_url is not None:
            document["_links"]["next"] = LinkMedia(self.next_url)
        if self.prev_url is not None:
            document["_links"]["prev"] = LinkMedia(self.prev_url)

        return document

    @classmethod
    def from_request_and_query(
            cls,
            query,
            item_media_type,
            sortable_columns=None):
        # apply sorting, if specified
        if sortable_columns is not None:
            sort_by = request_args_or("sort_by", [], str)
            descending = request_arg_or("descending", None, json.loads)

            query = biz.reports.apply_query_sorting(
                query,
                sort_by,
                sortable_columns,
                descending=descending)

        # limit results page, but include row count of complete query
        limit = request_arg_or("limit", 100, int)
        offset = request_arg_or("offset", 0, int)
        query = (
            query
            .limit(limit)
            .offset(offset)
            .add_columns(sql.func.count().over().label("total_count")))

        # fetch the items page
        tuples = query.all()
        items = [item_media_type(t[0]) for t in tuples]
        total_count = 0 if len(tuples) == 0 else tuples[0].total_count

        # build link URLs
        endpoint = flask.request.endpoint
        url_args = dict(
            flask.request.view_args.items()
            + flask.request.args.items())
        self_url = external_url_for(flask.request.endpoint, **url_args)

        if total_count > offset + len(items):
            next_query_args = url_args.copy()

            next_query_args.update({
                "offset": offset + limit,
                "limit": limit})

            next_url = external_url_for(endpoint, **next_query_args)
        else:
            next_url = None

        if offset > 0:
            prev_query_args = url_args.copy()

            prev_query_args.update({
                "offset": max(0, offset - limit),
                "limit": limit})

            prev_url = external_url_for(endpoint, **prev_query_args)
        else:
            prev_url = None

        return CollectionMedia(
            self_url,
            items,
            next_url,
            prev_url,
            limit=limit,
            offset=offset,
            total_count=total_count)


class RootMedia(object):
    def __json__(self):
        account_url_template = url_template_for(".account", id_="id")
        group_url_template = url_template_for(".group", id_="id")
        login_token_url_template = url_template_for(
            ".login_token",
            nametype="nametype",
            username="username",
            client="client")

        document = {
            "_links": {
                "self": LinkMedia(self.url),
                "type": LinkMedia("/types/root"),
                "za:account": LinkMedia(account_url_template, templated=True),
                "za:group": LinkMedia(group_url_template, templated=True),
                "za:portal": LinkMedia(
                    url_template_for(".portal", qid="qid"),
                    templated=True),
                "za:login-token": LinkMedia(
                    login_token_url_template,
                    templated=True)},
            "_embedded": {}}

        return document

    @property
    def url(self):
        # hackishly remove trailing slash, if any
        # (can be introduced as an artifact of Flask rule requirements)
        return external_url_for(".root").rstrip("/")


class LoginTokenMedia(object):
    def __init__(self, auth_name, token):
        self.auth_name = auth_name
        self.token = token

    def __json__(self):
        user_media = UserMedia(self.token.actor)

        return {
            "_links": {
                "za:user": LinkMedia(user_media.url)},
            "format": self.token.format,
            "token": self.token.string,
            "auth_name": self.auth_name}


class UserMedia(object):
    def __init__(self, user):
        self.user = user

    def __json__(self):
        return {
            "_links": {
                "self": LinkMedia(self.url),
                "type": LinkMedia("/types/user")},
            "qid": self.user.qid,
            "username": self.user.username,
            "role": self.user.role,
            "login_access_enabled": self.user.login_access_enabled,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "locale": self.user.locale,
            "primary_phone": self.user.primary_phone}

    @property
    def url(self):
        return external_url_for(".user", id_=self.user.id)


class PaymentMedia(object):
    def __init__(self, payment):
        self.payment = payment

    def __json__(self):
        source_string = (
            self.payment.source
            if isinstance(self.payment, za.biz.accounts.ManualPayment)
            else "")
        document = {
            "_links": {
                "self": LinkMedia(self.url)},
            "qid": self.payment.qid,
            "type": self.payment.type,
            "source": source_string,
            "phone": self.payment.phone,
            "amount": self.payment.amount,
            "currency": self.payment.currency,
            "recorded": self.payment.recorded}

        return document

    @property
    def url(self):
        return external_url_for(".payment", id_=self.payment.id)


class SMSMessageMedia(object):
    def __init__(self, sms_message):
        self.sms_message = sms_message

    def __json__(self):
        document = {
            "_links": {
                "self": LinkMedia(self.url),
                "type": LinkMedia("/types/sms_message")},
            "id": self.sms_message.id,
            "recipient": self.sms_message.recipient,
            "body": self.sms_message.body,
            ############ ADDING for cost
            "cost": {
                "_type": "decimal",
                "value": self.sms_message.cost_value
            },
            "cost_currency": self.sms_message.cost_currency,
            ############
            "created_when": self.sms_message.created_when,
            "sent_when": self.sms_message.sent_when,
            "state": self.sms_message.state,
            "error": self.sms_message.error}

        return document

    @property
    def url(self):
        return external_url_for(".sms_message", id_=self.sms_message.id)


#
# METHODS
#

class RelView(flask.views.MethodView):
    def get(self, name):
        flask.abort(404)


class RootView(flask.views.MethodView):
    """Root of the API."""

    def get(self):
        root_media = RootMedia()

        return za.json_response(root_media)


class LoginTokenView(flask.views.MethodView):
    """Manipulate a login token."""

    def get(self):
        """Retrieve a login token for the named actor.

        Sufficient authorization must be provided.

        Query parameters:

        * nametype
        * username

        Response fields:

        * format
        * token
        """

        # fetch requested actor
        nametype = flask.request.args.get("nametype")
        full_username = flask.request.args["username"]
        client = flask.request.args.get("client")

        if nametype is None:
            (nametype, username) = authname_parts(full_username)
        else:
            username = full_username

        actor = authname_actor(nametype, username)

        if client == "hub" and actor.role == "agent":
            flask.abort(403)

        # check authorization
        requestor = authenticated_actor(require_fresh=True)

        if isinstance(requestor, biz.accounts.User):
            if requestor.username != actor.username:
                flask.abort(401)
        elif isinstance(requestor, AnonymousActor):
            flask.abort(401)
        else:
            assert False

        # respond with new token for actor
        token = LoginToken.generate(actor)

        return za.json_response(LoginTokenMedia(full_username, token))


class UserView(flask.views.MethodView):
    def get(self, id_):
        authenticated_actor()

        user = biz.g.session.query(biz.accounts.User).get(id_)

        if user is None:
            flask.abort(404)
        else:
            user_media = UserMedia(user)

            return za.json_response(user_media)

    def patch(self, id_):
        """PATCH this user."""

        update = za.util.dejsonify(flask.request.data)

        logger.info("applying patch %s to user %s", update, id_)

        user = biz.accounts.User.from_id(id_)

        if user is None:
            flask.abort(404)

        if "email" in update:
            user.email = update["email"]
            user.username = update["email"]
        if "first_name" in update:
            user.first_name = update["first_name"]
        if "last_name" in update:
            user.last_name = update["last_name"]
        if "primary_phone" in update:
            user.primary_phone = update["primary_phone"]
        if "role" in update:
            user.role = update["role"]
        if "locale" in update:
            user.locale = update["locale"]
        if "password" in update:
            user.assign_password(update["password"])
        if "login_access_enabled" in update:
            user.login_access_enabled = update["login_access_enabled"]
        if "all_groups" in update and update["all_groups"]:
            user.set_registration_groups(all_groups=True)
        elif "registration_groups" in update:
            new_groups = [biz.accounts.Group.from_qid(qid) for qid in update["registration_groups"]]
            user.set_registration_groups(registration_groups=new_groups)

        biz.commit()

        return za.json_response(UserMedia(user))

    def delete(self, id_):
        """DELETE this user."""

        user = biz.g.session.query(biz.accounts.User).get(id_)

        if user is None:
            flask.abort(404)
        else:
            biz.g.session.delete(user)
            biz.commit()

            return za.json_response(status=204)


class UsersView(flask.views.MethodView):
    """HTTP methods for `User` entities."""

    def get(self, organization_id=None):
        """GET representation of a `UserMedia` collection."""

        # build root query
        query = biz.g.session.query(biz.accounts.User)
        organization_id = flask.request.args.get("organization_id")

        if organization_id is not None:
            query = query.filter_by(organization_id=int(organization_id))

        # apply pagination and return results
        media = CollectionMedia.from_request_and_query(
            query,
            UserMedia,
            sortable_columns={
                "username": biz.accounts.User.username,
                "role": biz.accounts.User.role,
                "email": biz.accounts.User.email,
                "first_name": biz.accounts.User.first_name,
                "last_name": biz.accounts.User.last_name})

        return za.json_response(media)

    def post(self):
        """POST new user according to request entity."""

        posted = flask.request.json
        user = biz.accounts.User(
            role=posted["role"],
            username=posted["email"],
            email=posted["email"],
            first_name=posted["first_name"],
            last_name=posted["last_name"],
            primary_phone=posted["primary_phone"],
            locale=posted.get("locale", "en_US"),
            raw_password=posted["password"],
            login_access_enabled=posted["login_access_enabled"])

        biz.g.session.add(user)
        biz.g.session.commit()

        return za.json_response(UserMedia(user), status=201)


class PaymentView(flask.views.MethodView):
    """HTTP methods for :class:`~biz.accounts.Payment` entities."""

    def get(self, id_):
        payment = biz.g.session.query(biz.accounts.Payment).get(id_)

        if payment is None:
            flask.abort(404)
        else:
            return za.json_response(PaymentMedia(payment))


class PaymentsView(flask.views.MethodView):
    """HTTP methods for `Payment` collections."""

    def get(self):
        args = self.args_from_request()
        query = biz.reports.PaymentsTableReporter.query_from_args(**args)
        media = CollectionMedia.from_request_and_query(query, PaymentMedia)

        return za.json_response(media)

    def post(self):
        actor = authenticated_actor()

        if isinstance(actor, AnonymousActor):
            raise AuthenticationError()

        document = flask.request.json
        payment = biz.accounts.ManualPayment(
            phone=document["phone"],
            amount=document["amount"],
            source="WEB",
            currency=za.util.Currency.USD.name)

        biz.accounts.record_payment(payment)
        biz.commit()

        return za.json_response(PaymentMedia(payment))

    @classmethod
    def args_from_request(cls):
        return dict(
            sort_by=request_args_or("sort_by", [], str),
            descending=request_arg_or("descending", False, u"true".__eq__),
            with_mobile=request_arg_or("with_mobile", None, u"true".__eq__),
            with_manual=request_arg_or("with_manual", None, u"true".__eq__),
            from_when=request_arg_or("from_when", None, za.util.parse_time),
            to_when=request_arg_or("to_when", None, za.util.parse_time),
            phone=request_arg_or("phone", None, str))


class SMSMessageView(flask.views.MethodView):
    def get(self, id_):
        message = biz.g.session.query(biz.accounts.SMSMessage).get(id_)

        if message is None:
            flask.abort(404)
        else:
            return za.json_response(SMSMessageMedia(message))


class SMSMessagesView(flask.views.MethodView):
    """HTTP methods for `SMSMessage` entities."""

    def get(self, organization_qid=None):
        """GET `SMSMessage` representations."""

        args = self.args_from_request()
        query = self.query_from_args(**args)
        media = CollectionMedia.from_request_and_query(query, SMSMessageMedia)

        return za.json_response(media)

    def post(self):
        """POST a new `SMSMessage`."""

        # unpack and validate post body
        posted = flask.request.json

        if not posted["recipient"].startswith("+"):
            # TODO better validation
            flask.abort(400)

        # create SMS message
        message = biz.accounts.SMSMessage.send_sms_raw(
            posted["recipient"],
            SMSMessageRole.MANUAL_FROM_WEB,
            posted["body"])

        biz.commit()

        # ...
        return za.json_response(SMSMessageMedia(message))

    @classmethod
    def args_from_request(cls):
        return dict(
            sort_by=request_args_or("sort_by", [], str),
            descending=request_arg_or("descending", False, u"true".__eq__),
            from_when=request_arg_or("from_when", None, za.util.parse_time),
            to_when=request_arg_or("to_when", None, za.util.parse_time))

    @classmethod
    def query_from_args(
            cls,
            sort_by=[],
            descending=None,
            from_when=None,
            to_when=None,
            _session=None,
            _prefetch_all=False):
        # normalize arguments
        session = biz.g.session if _session is None else _session

        # construct query
        query = session.query(biz.accounts.SMSMessage)

        if from_when is not None:
            query = query.filter(
                biz.accounts.SMSMessage.created_when >= from_when)
        if to_when is not None:
            query = query.filter(
                biz.accounts.SMSMessage.created_when <= to_when)

        # apply sorting
        sortable_columns = {
            "recipient": biz.accounts.SMSMessage.recipient,
            "sent_when": biz.accounts.SMSMessage.sent_when,
            "created_when": biz.accounts.SMSMessage.created_when,
            "state": biz.accounts.SMSMessage.state}
        query = apply_query_sorting(
            query,
            sort_by,
            sortable_columns,
            descending=descending)

        # ...
        return query


#
# APPLICATION
#

class BizAPIBlueprintConfig(object):
    """Configuration defaults for the biz API blueprint."""

    def __init__(self):
        """:rtype: `BizAPIBlueprintConfig`"""

        self.PREFERRED_URL_SCHEME = os.environ.get(
            "PREFERRED_URL_SCHEME",
            "https")


def create_blueprint(at_prefix):
    """Create a Flask blueprint for the biz API.

    :return: the blueprint
    :rtype: :class:`flask.Blueprint`
    """

    blueprint = flask.Blueprint("biz_api", __name__)

    @blueprint.record_once
    def on_app_register(state):
        add_url_template_support_to_app(state.app)

        state.app.config.from_object(BizAPIBlueprintConfig())

    #
    # ERRORS
    #

    @blueprint.after_request
    def report_api_request(response):
        # normalize headers
        type_map = {"content_length": int}
        response_headers = {}

        for (key, value) in response.headers.items():
            normal_key = key.replace("-", "_").lower()
            type_ = type_map.get(normal_key, lambda d: d)

            response_headers[normal_key] = type_(value)

        return response

    @blueprint.errorhandler(AuthenticationError)
    def make_fancy_auth_error(error):
        if error.code is not None:
            error_code = error.code
        else:
            error_code = "incorrect_username_password_combination"

        return za.json_response(
            {
                "description": "auth required",
                "error_code": error_code},
            status=401,
            mimetype="application/vnd.error+json")

    @blueprint.errorhandler(FancyRequestError)
    def make_fancy_request_error(error):
        logger.info(
            "bad request exception: %s (%s)",
            error.code.value,
            error.context)

        return za.json_response(
            {
                "description": "bad request",
                "error_code": error.code.value,
                "context": error.context},
            status=400,
            mimetype="application/vnd.error+json")

    @blueprint.errorhandler(Exception)
    def make_exception_error(error):
        logger.exception("unrecognized unhandled exception")

        return za.json_response(
            {},
            status=500,
            mimetype="application/vnd.error+json")

    def make_http_exception_error(error):
        logger.info("unhandled HTTP exception: %s", error.code)

        # TODO should return vnd.error+json
        response = za.json_response({}, status=error.code)

        return response

    for code in werkzeug.exceptions.default_exceptions.iterkeys():
        # some errors cannot be registered per-blueprint
        app_level_errors = [500]

        if code in app_level_errors:
            continue

        # handle all others within this blueprint
        blueprint.errorhandler(code)(make_http_exception_error)

    @blueprint.app_errorhandler(404)
    def make_404_error(error):
        # TODO somehow handle 404s per-blueprint
        return make_http_exception_error(error)

    #
    # ROUTES
    #

    rel_view = RootView.as_view("rel")
    root_view = RootView.as_view("root")
    user_view = UserView.as_view("user")
    users_view = UsersView.as_view("users")
    payment_view = PaymentView.as_view("payment")
    payments_view = PaymentsView.as_view("payments")
    sms_message_view = SMSMessageView.as_view("sms_message")
    sms_messages_view = SMSMessagesView.as_view("sms_messages")

    if len(at_prefix) > 0:
        blueprint.add_url_rule("", view_func=root_view)

    blueprint.add_url_rule("/", view_func=root_view)
    blueprint.add_url_rule("/rels/<name>", view_func=rel_view)
    blueprint.add_url_rule(
        "/login-token",
        view_func=LoginTokenView.as_view("login_token"))
    blueprint.add_url_rule("/users/US<int:id_>", view_func=user_view)
    blueprint.add_url_rule("/users", view_func=users_view)
    blueprint.add_url_rule("/payments/<int:id_>", view_func=payment_view)
    blueprint.add_url_rule("/payments", view_func=payments_view)
    blueprint.add_url_rule(
        "/sms_messages/SM<int:id_>",
        view_func=sms_message_view)
    blueprint.add_url_rule("/sms_messages", view_func=sms_messages_view)

    return blueprint
