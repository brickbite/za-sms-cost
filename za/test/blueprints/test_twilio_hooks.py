import nose.tools
import flask
import werkzeug.exceptions
import za.biz
import za.test.biz
import za.blueprints.twilio_hooks as module

from xml.etree import ElementTree

biz = za.biz


class TestModule(object):
    def test_normalize_phone__various_inputs__correct_outputs_returned(self):
        def assert_normalized_ok(input_number, normalized_number):
            output_number = module.normalize_phone(input_number)

            nose.tools.assert_equal(output_number, normalized_number)

        input_expectation_pairs = [
            # valid E.164 numbers should map to themselves
            ("+15551234", "+15551234"),
            ("+260973293375", "+260973293375"),
            # invalid +1 prefixes should be stripped
            ("+1260973611879", "+260973611879"),
            ("+1254973611879", "+254973611879"),
            # invalid weird +011 prefixes should be stripped
            ("+011254733124505", "+254733124505"),
            ("+011254712049365", "+254712049365")]

        for (input_number, normalized_number) in input_expectation_pairs:
            yield (assert_normalized_ok, input_number, normalized_number)


class FakeInboundSMSHandler(object):
    def __init__(self):
        self.handled = []

    def __call__(self, from_, body):
        self.handled.append((from_, body))


class TestSMSInView(za.test.biz.FakeServiceFixture):
    def inner_setup(self):
        self._sms_handler = FakeInboundSMSHandler()
        self._view = module.SMSInView(sms_handler=self._sms_handler)
        self._app = flask.Flask(__name__)

    def assert_valid_empty_twiml_response(self, response):
        """Extract the text of the reply SMS."""

        nose.tools.assert_equal(response.status_code, 200)

        root = ElementTree.fromstring(response.data)

        nose.tools.assert_equal(root.tag, "Response")
        nose.tools.assert_equal(root.getchildren(), [])

    def test_post__args_valid__200_returned(self):
        with self._app.test_request_context(
                "/twilio/sms_in",
                method="POST",
                data={"From": "+15551234567", "Body": "message body"}):
            response = self._view.post()

        self.assert_valid_empty_twiml_response(response)

        nose.tools.assert_equal(len(self._sms_handler.handled), 1)

    def test_post__args_missing__400_returned(self):
        with self._app.test_request_context("/twilio/sms_in", method="POST"):
            nose.tools.assert_raises(
                werkzeug.exceptions.BadRequestKeyError,
                self._view.post)

        nose.tools.assert_equal(len(self._sms_handler.handled), 0)
