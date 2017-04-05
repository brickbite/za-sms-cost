import mock
import nose.tools
import twilio
import za.sms

from za.biz.accounts import SMSMessageState


class FakeSMSRouter(za.sms.SMSRouter):
    def __init__(self):
        self.routed = []
        self.routed_bodies = []

    def send_sms(self, recipient, body):
        self.routed.append(recipient)
        self.routed_bodies.append(body)

        return {
            "state": SMSMessageState.FINAL_UNCONFIRMED,
            "route_key": "fakeroute",
            "route_message_key": "message1234"}


class FakeSMSFailingRouter(za.sms.SMSRouter):
    def __init__(self):
        self.routed = []
        self.routed_bodies = []

    def send_sms(self, recipient, body):
        self.routed.append(recipient)
        self.routed_bodies.append(body)

        return {
            "state": SMSMessageState.FINAL_FAILED,
            "route_key": "fakeroute",
            "route_message_key": None}


class FakeSMSRaisingRouter(za.sms.SMSRouter):
    def __init__(self):
        self.routed = []
        self.routed_bodies = []

    def send_sms(self, recipient, body):
        raise ValueError


class TestModule(object):
    def test_get_default_router__called__returns_not_none(self):
        router = za.sms.get_default_router()

        nose.tools.assert_is_not_none(router)


class TestTwilioSMSRouter(object):
    def setup(self):
        za.config["TWILIO_ACCOUNT_SID"] = "faketwilioaccountsid"
        za.config["TWILIO_AUTH_TOKEN"] = "faketwilioauthtoken"
        za.config["TWILIO_NUMBER"] = "+15557654321"

    def teardown(self):
        za.config["TWILIO_ACCOUNT_SID"] = ""
        za.config["TWILIO_AUTH_TOKEN"] = ""
        za.config["TWILIO_NUMBER"] = ""

    def test_send_sms__valid_recipient__correct_call_made(self):
        router = za.sms.TwilioSMSRouter()
        recipient = "+15551234567"
        body = "test message body"

        with mock.patch("twilio.rest") as twilio_rest:
            message = twilio_rest.TwilioRestClient().sms.messages.create()
            message.sid = "SMd21d154781fca5bd2724a8d911ee638a"

            router.send_sms(recipient, body)

        twilio_rest.TwilioRestClient().sms.messages.create.assert_called_with(
            to=recipient,
            from_=za.config["TWILIO_NUMBER"],
            body=body)

    def test_send_sms__error_on_send__same_error_raised(self):
        router = za.sms.TwilioSMSRouter()

        with mock.patch("twilio.rest") as twilio_rest:
            twilio_client = twilio_rest.TwilioRestClient()

            twilio_client.sms.messages.create.side_effect = (
                twilio.TwilioRestException(400, ""))

            nose.tools.assert_raises(
                twilio.TwilioRestException,
                router.send_sms,
                "+15551234567",
                "test message body")

    def test_send_sms__error_on_send__error_21614(self):
        router = za.sms.TwilioSMSRouter()

        with mock.patch("twilio.rest") as twilio_rest:
            twilio_client = twilio_rest.TwilioRestClient()

            twilio_client.sms.messages.create.side_effect = (
                twilio.TwilioRestException(
                    400,
                    "",
                    msg="21614: invalid number"))

            nose.tools.assert_raises(
                ValueError,
                router.send_sms,
                "+15551234567",
                "test message body")


class TestSequentialSMSRouter(object):
    def setup(self):
        self._router254 = FakeSMSRouter()
        self._router255 = FakeSMSRouter()

    def assert_routed(self, router, to, router_expected):
        router.send_sms(to, "message body")

        nose.tools.assert_in(to, router_expected.routed)

    def test_send_sms__two_routes_two_messages__correctly_routed(self):
        router = za.sms.SequentialSMSRouter([
            ("+254", self._router254),
            ("+255", self._router255)])

        self.assert_routed(router, "+2540123456789", self._router254)
        self.assert_routed(router, "+2550123456789", self._router255)

        nose.tools.assert_equal(
            len(self._router254.routed) + len(self._router255.routed),
            2)

    def test_send_sms__callable_condition__correctly_routed(self):
        router = za.sms.SequentialSMSRouter([
            (lambda v: v.startswith("+254"), self._router254),
            (None, self._router255)])

        self.assert_routed(router, "+2540123456789", self._router254)
        self.assert_routed(router, "+2550123456789", self._router255)

        nose.tools.assert_equal(
            len(self._router254.routed) + len(self._router255.routed),
            2)
