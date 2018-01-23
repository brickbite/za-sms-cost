import abc
import twilio.rest
import za

from za.biz.accounts import SMSMessageState

logger = za.get_logger(__name__)
_default_router = None


class SMSRouter(object):
    """Abstract base for SMS message routers."""

    @abc.abstractmethod
    def send_sms(self, recipient, body):
        """Route a single SMS message."""

        raise AssertionError("abstract method")


class DevNullSMSRouter(SMSRouter):
    """Route SMS messages into /dev/null."""

    def __init__(self, warn=False):
        """Construct null route."""

        self._warn = warn

    def send_sms(self, recipient, body):
        """Route a single SMS message."""

        if self._warn:
            logger.warning("sending SMS to %s via /dev/null", recipient)

        return {
            "state": SMSMessageState.FINAL_DELIVERED,
            "route_key": "dev_null",
            "route_message_key": None}


class TwilioSMSRouter(SMSRouter):
    """Route SMS messages through Twilio."""

    def __init__(self, account_sid=None, auth_token=None, from_=None):
        """Construct Twilio route."""

        if account_sid is None:
            account_sid = za.config["TWILIO_ACCOUNT_SID"]
        if auth_token is None:
            auth_token = za.config["TWILIO_AUTH_TOKEN"]
        if from_ is None:
            from_ = za.config["TWILIO_NUMBER"]

        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from = from_

    def send_sms(self, recipient, body):
        """Route a single SMS message."""

        logger.debug("sending SMS message to %s via Twilio", recipient)

        client = twilio.rest.TwilioRestClient(
            self._account_sid,
            self._auth_token)

        try:
            message = client.sms.messages.create(
                to=recipient,
                from_=self._from,
                body=body)
        except twilio.TwilioRestException as error:
            # If Twilio returns an HTTP response error, this means that
            # Twilio is unable to process your request and thus you will
            # not be charged - http://bit.ly/1NgPf2c
            if error.msg.strip().startswith("21614:"):
                raise ValueError("not a valid mobile number")
            else:
                raise

        logger.info("twilio message: %r", message)

        return {
            "state": SMSMessageState.FINAL_UNCONFIRMED,
            "route_key": "twilio",
            "route_message_key": message.sid}

    def get_sms_cost(self, sms_sid):
        """Get cost of a single SMS message."""

        logger.debug("==== get_sms_cost: getting cost of SMS message of %s from Twilio", sms_sid)

        client = twilio.rest.TwilioRestClient(
            self._account_sid,
            self._auth_token)

        try:
            message = client.messages(sms_sid).fetch()
        except twilio.TwilioRestException as error:
            # If Twilio returns an HTTP response error, this means that
            # Twilio is unable to process your request and thus you will
            # not be charged - http://bit.ly/1NgPf2c
            if error.msg.strip().startswith("21614:"):
                raise ValueError("not a valid mobile number")
            else:
                raise

        logger.info("==== get_sms_cost: twilio message: %r", message)

        return {
            "state": message.status,
            "cost": message.price,
            "cost_currency": message.price_unit}


class SequentialSMSRouter(SMSRouter):
    """Route SMS messages by sequential condition-matching.

    Valid conditions are:

    - `None` (always matches)
    - `basestring` (matches iff a prefix of the recipient)
    - any object satisfying `callable()` (matches iff `condition(recipient)`)
    """

    def __init__(self, routes):
        """Construct prefix-matching route.

        A route is a `(condition, router)` pair.
        """

        self._routes = routes
        logger.debug("SequentialRouter: self._routes: %s", self._routes)

    def send_sms(self, recipient, body):
        """Route a single SMS message."""

        if not recipient.startswith("+"):
            raise ValueError("recipient number is not valid E.164")

        for (condition, router) in self._routes:
            if self._route_matches(condition, recipient):
                logger.debug(
                    "routing message to %s through %s",
                    recipient,
                    router)

                return router.send_sms(recipient, body)

        raise RuntimeError("no matching route for SMS recipient")
    
    def _route_matches(self, condition, recipient):
        """Return `True` iff the recipient meets the specified condition."""

        if condition is None:
            return True
        elif isinstance(condition, basestring):
            return recipient.startswith(condition)
        elif callable(condition):
            return condition(recipient)


def get_default_router():
    """Return the default SMS router."""

    global _default_router

    if _default_router is None:
        routes = []

        # attempt to add Twilio route
        try:
            twilio_router = TwilioSMSRouter()
        except:
            logger.info("could not construct Twilio SMS route")
        else:
            routes.append((None, twilio_router))

        # add null route
        routes.append((None, DevNullSMSRouter(warn=True)))

        # build router
        logger.info("final SMS routes table: %s", routes)

        _default_router = SequentialSMSRouter(routes)

    return _default_router
