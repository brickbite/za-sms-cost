import bcrypt
import unicodedata
import enum
import times
import sqlalchemy.sql
import sqlalchemy.orm
import sqlalchemy.dialects.postgresql as pgsql
import sqlalchemy.ext.hybrid
import sqlalchemy.types as types
import za
import za.biz as biz
from za.util import Currency

sa = sqlalchemy
logger = za.get_logger(__name__)

# TODO don't use global session explicitly


def get_named_entity(name):
    # TODO scan for __qid_prefix__ instead of hardcoding map
    type_tag = name[:2]
    type_names = {
        "PA": biz.accounts.Payment,
        "US": biz.accounts.User,
        "SM": biz.accounts.SMSMessage}
    named_type = type_names[type_tag]

    def from_qid_default(qid):
        return biz.g.session.query(named_type).get(int(qid[2:]))

    from_qid = getattr(named_type, "from_qid", from_qid_default)
    entity = from_qid(name)

    if entity is None:
        raise KeyError("name does not specify an extant entity")
    else:
        return entity

get_named = get_named_entity


def record_payment(payment):
    """Record a payment and handle the associated business logic."""

    biz.g.session.add(payment)
    biz.flush()

    logger.info("recording payment %s", payment.id)

    SMSMessage.send_sms(
        payment.phone,
        SMSMessageRole.PAYMENT_CONFIRMATION,
        payment=payment)


class PaymentCode(enum.Enum):
    """Payment Code types for special-case payment processing."""

    TRACER = "TRACER"
    EXISTS = "EXISTS"
    ADHOC = "ADHOC"
    REMIT = "REMIT"
    NOT_PAYMENT = "NOT_PAYMENT"

    def __init__(self, value):
        assert value == self.name

    @property
    def human_name(self):
        names = {
            "TRACER": 'Tracer',
            "EXISTS": 'Exists',
            "ADHOC": 'Ad hoc payment',
            "REMIT": 'Remittance',
            "NOT_PAYMENT": 'The message was not a payment'}

        return names[self.name]


class Payment(biz.DomainBase):
    __tablename__ = "payments"
    __qid_prefix__ = "PA"

    def __init__(self, *args, **kwargs):
        biz.DomainBase.__init__(self, *args, **kwargs)

    id = sa.Column(sa.Integer, primary_key=True)
    xid = sa.Column(pgsql.UUID(as_uuid=True), unique=True)
    type = sa.Column(
        sa.Enum(
            "manual",
            "mpesa_tz",
            "mpesa_ke",
            "airtel_za",
            name="payment_type",
            native_enum=False))
    phone = sa.Column(sa.String)
    amount = sa.Column(sa.Numeric, nullable=False)
    currency = sa.Column(
        sa.Enum(*Currency.__members__, native_enum=False),
        nullable=False,
        default=Currency.USD.name)
    recorded = sa.Column(sa.DateTime, default=times.now)

    @property
    def qid(self):
        """Qualified ID of this entity."""

        if self.id is None:
            raise RuntimeError("cannot make qid; entity has no id")

        return "{}{:d}".format(self.__qid_prefix__, self.id)

    @property
    def age(self):
        return times.now() - self.recorded

    @classmethod
    def from_qid(cls, qid):
        """Find entity from qualified ID.

        :param qid: qualified ID to look up
        :type qid: str
        """

        if not qid.startswith(cls.__qid_prefix__):
            raise ValueError("qid qualifier not as expected")

        id_ = int(qid[len(cls.__qid_prefix__):], 10)

        return biz.g.session.query(cls).get(id_)

    __mapper_args__ = {"polymorphic_on": type}


class ManualPayment(Payment):
    __tablename__ = "payments_manual"
    __mapper_args__ = {"polymorphic_identity": "manual"}

    id = sa.Column(sa.Integer, sa.ForeignKey("payments.id"), primary_key=True)
    source = sa.Column(
        sa.Enum(
            'UNKNOWN',
            'WEB',
            'MOBILE',
            'SMS_COMMAND',
            native_enum=False))

    def __init__(self, currency=None, **kwargs):
        super(ManualPayment, self).__init__(
            currency=currency,
            **kwargs)

    @property
    def sent_when(self):
        return self.recorded

    @classmethod
    def find_or_init(cls, **kwargs):
        """Find payment that matches specified details, or create one.

        :return: (existing or new payment, whether payment is new, why/not)
        :rtype: (:class:`ManualPayment`, `bool`, `str`)
        """

        xid = kwargs.get("xid")

        if xid is None:
            existing = None
        else:
            existing = biz.g.session.query(cls).filter_by(xid=xid).first()

        if existing is None:
            return (cls(**kwargs), True, None)
        else:
            return (existing, False, PaymentCode.EXISTS)


class User(biz.DomainBase):
    """Full-fledged user account."""

    __tablename__ = "users"
    __qid_prefix__ = "US"

    # columns
    id = sa.Column(sa.Integer, primary_key=True)
    username = sa.Column(sa.String, nullable=False, unique=True)
    password = sa.Column(sa.String, nullable=False)
    role = sa.Column(sa.Enum(
        "admin",
        "operator",
        "agent",
        "viewer",
        native_enum=False))
    email = sa.Column(sa.String)
    first_name = sa.Column(sa.String)
    last_name = sa.Column(sa.String)
    locale = sa.Column(sa.String, nullable=False)
    login_access_enabled = sa.Column(sa.Boolean, nullable=False, default=True)
    primary_phone = sa.Column(sa.String, unique=True)  # E.164

    def __init__(self, raw_password, **kwargs):
        """
        :param raw_password: raw unencoded password
        :type raw_password: :class:`unicode`
        :param kwargs: all other fields
        :type kwargs: :class:`dict`
        """

        assert "password" not in kwargs

        super(User, self).__init__(**kwargs)

        self.assign_password(raw_password)

    @property
    def qid(self):
        """Qualified ID of this entity."""

        if self.id is None:
            raise RuntimeError("cannot make qid; entity has no id")

        return "{}{:06x}".format(self.__qid_prefix__, self.id)

    def assign_password(self, raw_password):
        """(Re)assign this user's password.

        :param raw_password: the password, unencoded and unhashed
        :type raw_password: :class:`unicode`
        """

        self.password = User._hash_password(raw_password)

    def password_matches(self, raw_password):
        """Does this user have the specified password?

        :param raw_password: password, unencoded and unhashed
        :type raw_password: :class:`unicode`
        """

        # salt will be extracted from the current password
        hashed_password = User._hash_password(raw_password, salt=self.password)

        return hashed_password == self.password

    @staticmethod
    def _hash_password(raw_password, salt=None):
        """Hash the normalized, encoded version of the password provided."""

        if not isinstance(raw_password, unicode):
            # we're strict about unicode input because it is important for
            # callers to make certain that they are getting the decoding right
            raise TypeError("raw password is not a unicode string")

        if salt is None:
            salt = bcrypt.gensalt()

        return bcrypt.hashpw(
            unicodedata.normalize("NFKC", raw_password).encode("utf-8"),
            salt)

    @staticmethod
    def from_username(username):
        return (
            biz.g.session.query(User)
            .filter_by(username=username)
            .one())

    @staticmethod
    def from_phone(phone):
        return (
            biz.g.session.query(User)
            .filter_by(primary_phone=phone)
            .one())


class SMSMessageState(enum.Enum):
    """State of an SMS message.

    At any given time, a message is in one of several possible states:

    - scheduled
    - in_transit (message being delivered by MNO)
    - final_delivered (confirmation of handset delivery received)
    - final_unconfirmed (no confirmation received, and none will be received)
    - final_failed (message explicitly failed to be delivered)

    The enum value is arbitrary and should be ignored!
    """

    SCHEDULED = 0
    IN_TRANSIT = 1
    FINAL_DELIVERED = 2
    FINAL_UNCONFIRMED = 3
    FINAL_FAILED = 4
    FINAL_NOT_SENT = 5

    @property
    def human_name(self):
        names = {
            'SCHEDULED': 'Scheduled',
            'IN_TRANSIT': 'In Transit',
            'FINAL_DELIVERED': 'Delivered',
            'FINAL_UNCONFIRMED': 'Unconfirmed',
            'FINAL_FAILED': 'Failed',
            'FINAL_NOT_SENT': 'Not Sent'}

        return names[self.name]


class SMSMessageError(enum.Enum):
    """Detail about an SMS message delivery error.

    Errors are not always associated with a permanent delivery failure.
    ABSENT_SUBSCRIBER_TEMPORARY, for example, may be set even when a
    message is in state `SMSMessageState.IN_TRANSIT`.

    The error list is largely taken from that used by Nexmo for its DLRs

    https://docs.nexmo.com/index.php/sms-api/handle-delivery-receipt#dlr_status

    which may have been taken from SMPP.
    """

    UNKNOWN = "UNKNOWN"
    ABSENT_SUBSCRIBER_TEMPORARY = "ABSENT_SUBSCRIBER_TEMPORARY"
    ABSENT_SUBSCRIBER_PERMANENT = "ABSENT_SUBSCRIBER_PERMANENT"
    CALL_BARRED = "CALL_BARRED"
    PORTABILITY_ERROR = "PORTABILITY_ERROR"
    UNSPECIFIED_REJECTION = "UNSPECIFIED_REJECTION"
    ANTI_SPAM_REJECTION = "ANTI_SPAM_REJECTION"
    HANDSET_BUSY = "HANDSET_BUSY"
    NETWORK_ERROR = "NETWORK_ERROR"
    ILLEGAL_NUMBER = "ILLEGAL_NUMBER"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    UNROUTABLE = "UNROUTABLE"
    UNREACHABLE = "UNREACHABLE"
    GENERAL_ERROR = "GENERAL_ERROR"
    TEMPLATE_UNPARSEABLE = "TEMPLATE_UNPARSEABLE"

    def __init__(self, value):
        assert value == self.name


class PyEnum(types.TypeDecorator):
    """Augmented Enum class for SQLAlchemy/Python types

    Python's enum.Enum class cannot be stored directly in a postgres row
    because it is too complex, and raises:

        sqlalchemy.exc.ProgrammingError: (ProgrammingError) can't adapt type

    We could work-around by storing enum.Enum.name, but it looks ugly
    and who wants to type that much? Instead, provide this SQLAlchemy
    "augmented type" so we can continue to use enum.Enum and persist it
    in postgres.
    """

    impl = types.Enum

    def __init__(self, python_class, *args, **kw):
        self.python_class = python_class
        super(PyEnum, self).__init__(*args, **kw)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = value.name

        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = self.python_class[value]

        return value

    def python_type(self):
        return self.python_class


@enum.unique
class SMSMessageRole(enum.Enum):
    """Role of an SMS message.

    SMSes are used for various functional roles, such as reminding customers
    to make a scheduled payment, etc.

    The enum value is arbitrary and should be ignored!
    """

    # These templates are expected to typically live at the Group level
    PAYMENT_PRE_REMINDER = object()  #: reminder before payment becomes overdue
    PAYMENT_POST_REMINDER = object()  #: reminder after payment is overdue
    PAYMENT_SYNC_REMINDER = object()  #: reminder to activate "stored" payment
    PAYMENT_CONFIRMATION = object()  #: confirmation of payment (before unlock)
    PAYMENT_BAD_SERIAL = object()  #: notice of an invalid account number
    PAYMENT_UNLOCKED = object()  #: confirmation of final payment
    #: confirmation of successful audio activation
    PAYMENT_CALL_SEQUENCE_SUCCESS = object()
    #: notice of unsuccessful audio activation
    PAYMENT_CALL_SEQUENCE_FAILURE = object()

    # These templates tend to live at the Organization level
    ACCOUNT_ATTACH_FAILED = object()  #: notice of failed audio registration
    ACCOUNT_ATTACH_SCHEDULED = object()  #: notice of pending attach call
    #: confirmation of successful audio registration
    ACCOUNT_ATTACH_SUCCEEDED = object()
    #: confirmation of successful audio unregistration
    ACCOUNT_DETACH_SUCCEEDED = object()
    #: notice of invalid attach initiation attempt
    ACCOUNT_ATTACHED_ALREADY = object()
    #: notice of invalid attach initiation attempt
    ACCOUNT_DETACHED_ALREADY = object()
    #: notice of insufficient payment, usually mobile money
    PAYMENT_MORE_MONEY_NEEDED = object()
    #: notice to customer of an overdue-payment penalty
    PAYMENT_PENALTY_APPLIED = object()
    #: notice of activation failure due to a low battery
    UNIT_BATTERY_LOW = object()

    # Special-case templates associated only with Angaza Organization
    # They'll probably grow separate namespaces in the future: HELP_*, ...
    #: terms and conditions sent to customer after registration
    REGISTRATION_WELCOME = object()
    #: generic "contact distributor" response to a customer action
    HELP_GENERIC = object()
    #: error response to an incoming SMS command
    SMS_INBOUND_PROCESSING_FAILURE = object()

    # Templates not associated with any entities at all.
    #: ad-hoc message without any particular role
    MANUAL_FROM_WEB = object()
    #: message role unknown
    CATCH_ALL = object()

    @property
    def human_name(self):
        names = {
            'PAYMENT_PRE_REMINDER': 'Upcoming Payment Reminder',
            'PAYMENT_POST_REMINDER': 'Overdue Payment Reminder',
            'PAYMENT_SYNC_REMINDER': 'Activate Credit Reminder',
            'PAYMENT_CONFIRMATION': 'Payment Confirmation',
            'PAYMENT_BAD_SERIAL': 'Invalid Account Number Notification',
            'PAYMENT_UNLOCKED': 'Final Payment Confirmation',
            'PAYMENT_CALL_SEQUENCE_SUCCESS': 'Successful Call Notification',
            'PAYMENT_CALL_SEQUENCE_FAILURE': 'Unsuccessful Call Notification',
            'ACCOUNT_ATTACH_FAILED': 'Failed Audio Registration',
            'ACCOUNT_ATTACH_SCHEDULED': 'Pending Audio Registration',
            'ACCOUNT_ATTACH_SUCCEEDED': 'Successful Audio Registration',
            'ACCOUNT_DETACH_SUCCEEDED': 'Successful Audio De-Registration',
            'ACCOUNT_ATTACHED_ALREADY': 'Invalid Audio Registration',
            'ACCOUNT_DETACHED_ALREADY': 'Invalid Audio Registration',
            'PAYMENT_MORE_MONEY_NEEDED': 'Insufficient Payment Notification',
            'PAYMENT_PENALTY_APPLIED': 'Overdue Payment Penalty Notification',
            'UNIT_BATTERY_LOW': 'Failed Audio Registration (Battery Low)',
            'REGISTRATION_WELCOME': 'Registration Welcome',
            'HELP_GENERIC': 'Help Message',
            'SMS_INBOUND_PROCESSING_FAILURE': 'SMS Processing Error',
            'MANUAL_FROM_WEB': 'Manual SMS from Hub',
            'CATCH_ALL': 'Manual SMS'}

        return names[self.name]


class SMSMessage(biz.DomainBase):
    """Specific single SMS message, in some state.

    If a delivery receipt is later received (via some webhook, for example),
    that receipt is normalized in the receiver implementation and then applied
    via `update()`.
    """

    __tablename__ = "sms_messages"

    id = sa.Column(sa.Integer, primary_key=True)
    created_when = sa.Column(sa.DateTime, nullable=False)
    sent_when = sa.Column(sa.DateTime)
    state = sa.Column(
        sa.Enum(*SMSMessageState.__members__.keys(), native_enum=False),
        nullable=False,
        default=SMSMessageState.SCHEDULED.name)
    error = sa.Column(sa.Enum(*SMSMessageError.__members__, native_enum=False))
    role = sa.Column(
        PyEnum(
            SMSMessageRole,
            *SMSMessageRole.__members__,
            native_enum=False),
        nullable=False)
    route_key = sa.Column(sa.String)
    route_message_key = sa.Column(sa.String)
    route_message_status = sa.Column(sa.String)
    recipient = sa.Column(sa.String, nullable=False)
    body = sa.Column(sa.UnicodeText, nullable=False)
    template_name = sa.Column(sa.String)
    payment_id = sa.Column(sa.Integer, sa.ForeignKey("payments.id"))
    payment = sa.orm.relationship(
        "Payment",
        backref=sa.orm.backref("sms_messages"))

    def __init__(self, **kwargs):
        # normalize and validate args
        full_kwargs = {"created_when": times.now()}

        full_kwargs.update(kwargs)

        assert isinstance(kwargs.get("role"), SMSMessageRole)

        # then init
        super(SMSMessage, self).__init__(**full_kwargs)

    @property
    def age(self):
        return times.now() - self.created_when

    def update(
            self,
            state,
            error=None,
            route_message_status=None,
            force_report=True):
        """Update the reported message delivery state.

        :param state: latest message state
        :type state: :class:`SMSMessageState`
        :param error: delivery error, if any
        :type error: :class:`SMSMessageError` or :class:`NoneType`
        :param route_message_status: raw route message status, if any
        :type route_message_status: :class:`basestring` or :class:`NoneType`
        :param force_report: some callers always want to report, some don't
        :type force_report: :class:`bool`
        """

        self.state = state.name
        self.error = None if error is None else error.name
        self.route_message_status = route_message_status

        if self.sent_when is None:
            sent_when_str = None
        else:
            sent_when_str = self.sent_when.isoformat()

    @classmethod
    def send_sms(
            cls,
            recipient,
            role,
            payment=None,
            explanation=None,
            keycode=None):
        """Create and send an SMS message."""

        templates = {
            SMSMessageRole.PAYMENT_CONFIRMATION:
            "Your payment of {{ payment.currency }}"
            " {{ payment.amount }} was received!"}
        body = za.render_sms_template_string(
            templates.get(role, role.name),
            payment=payment,
            explanation=explanation,
            keycode=keycode)

        return cls.send_sms_raw(
            recipient,
            role,
            body,
            payment=payment)

    @classmethod
    def send_sms_raw(
            cls,
            recipient,
            role,
            body,
            payment=None,
            error=None):
        """Create and send an SMS message."""

        message = cls(
            recipient=recipient,
            role=role,
            body=body,
            created_when=times.now(),
            payment=payment)

        biz.g.session.add(message)
        biz.flush()

        if error is None:
            # send the SMS message asynchronously via celery
            from za.biz.tasks.sms_message import SendSMSMessageRule
            biz.commit()
            sms_message_rule = SendSMSMessageRule()
            sms_message_rule.delay(message.id)
        else:
            message.error = error.name
            message.state = SMSMessageState.FINAL_FAILED.name

            biz.g.session.add(message)
            biz.flush()

            # report failure for monitoring
            message.update(state=SMSMessageState.FINAL_FAILED, error=error)

        return message

    @classmethod
    def from_route_info(class_, route_key, route_message_key):
        return (
            biz.g.session.query(class_)
            .filter_by(
                route_key=route_key,
                route_message_key=route_message_key)
            .one())
