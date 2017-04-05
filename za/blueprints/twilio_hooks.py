import flask
import flask.views
import twilio.twiml
import za
import za.biz as biz
import za.biz.accounts

logger = za.get_logger(__name__)


class SMSInView(flask.views.MethodView):
    """Respond to a Twilio SMS notification."""

    def __init__(self, sms_handler):
        self._sms_handler = sms_handler

    def post(self):
        """Handle an incoming SMS."""

        logger.info(
            "received SMS notification from Twilio: \"%s\"",
            flask.request.values)

        # interpret the body
        sms_from = flask.request.form["From"]
        sms_body = flask.request.form["Body"]

        self._sms_handler(sms_from, sms_body)

        biz.commit()

        # return 200 OK
        empty_reply = twilio.twiml.Response()

        return flask.Response(str(empty_reply), mimetype="application/xml")


def normalize_phone(phone):
    if len(phone) == 14 and phone.startswith("+1260"):
        normalized = "+" + phone[2:]
    elif len(phone) == 14 and phone.startswith("+1256"):
        normalized = "+" + phone[2:]
    elif len(phone) == 14 and phone.startswith("+1255"):
        normalized = "+" + phone[2:]
    elif len(phone) == 14 and phone.startswith("+1254"):
        normalized = "+" + phone[2:]
    elif len(phone) == 16 and phone.startswith("+011"):
        normalized = "+" + phone[4:]
    else:
        normalized = phone

    logger.debug("normalized phone \"%s\" to \"%s\"", phone, normalized)

    return normalized


def create_blueprint(at_prefix, sms_handler=None):
    """Create the Twilio-receiver service blueprint."""

    # prepare defaults
    if sms_handler is None:
        def log_message(from_, body):
            logger.info("received SMS message %s from %s", body, from_)
        sms_handler = log_message

    # create the blueprint
    blueprint = flask.Blueprint("twilio_hooks", __name__)

    blueprint.add_url_rule(
        "/twilio/sms_in",
        view_func=SMSInView.as_view("twilio_sms_in", sms_handler=sms_handler))

    return blueprint
