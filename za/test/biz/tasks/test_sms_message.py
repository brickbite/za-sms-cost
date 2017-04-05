import datetime as dt
import nose.tools
import times
import za.biz as biz
import za.biz.tasks.sms_message

from za.biz.accounts import (
    SMSMessageRole,
    SMSMessageState,
    SMSMessage)
from za.test.test_sms import (
    FakeSMSRouter,
    FakeSMSRaisingRouter,
    FakeSMSFailingRouter)


def create_messages(specs):
    messages = []

    for spec in specs:
        spec = dict(spec)

        spec["recipient"] = spec.get("recipient", "+15550000000")
        spec["body"] = spec.get("body", u"body body body")
        spec["role"] = SMSMessageRole.CATCH_ALL

        messages.append(SMSMessage(**spec))

    biz.g.session.add_all(messages)
    biz.flush()

    return messages


class TestSendSMSMessageRule(za.test.biz.FakeServiceFixture):
    def inner_setup(self):
        self._router = FakeSMSRouter()
        self._rule = biz.tasks.sms_message.SendSMSMessageRule(self._router)

    def test_check__already_sent__false_returned(self):
        (message,) = create_messages([{
            "state": SMSMessageState.FINAL_DELIVERED.name}])

        nose.tools.assert_false(self._rule.check(message))

    def test_check__not_sent__true_returned(self):
        (message,) = create_messages([{
            "state": SMSMessageState.SCHEDULED.name}])

        nose.tools.assert_true(self._rule.check(message))

    def test_execute__no_error_during_send__message_sent(self):
        (message,) = create_messages([{}])

        self._rule.execute(message)

        nose.tools.assert_equal(len(self._router.routed), 1)
        nose.tools.assert_is_not_none(message.sent_when)

    def test_execute__overly_long_message__truncated_message_sent(self):
        body = u"xyzzy" * 64
        (message,) = create_messages([{"body": body}])

        self._rule.execute(message)

        (body_routed,) = self._router.routed_bodies

        nose.tools.assert_equal(body_routed, body[:160])

    def test_execute__send_sms__fails_ok(self):
        router = FakeSMSFailingRouter()
        rule = biz.tasks.sms_message.SendSMSMessageRule(router)

        (message,) = create_messages([{
            "state": SMSMessageState.SCHEDULED.name}])

        rule.execute(message)

        nose.tools.assert_equal(
            message.state,
            SMSMessageState.FINAL_FAILED.name)
        nose.tools.assert_is_none(message.route_message_key)

    def test_execute__send_sms_raises(self):
        router = FakeSMSRaisingRouter()
        rule = biz.tasks.sms_message.SendSMSMessageRule(router)

        (message,) = create_messages([{
            "state": SMSMessageState.SCHEDULED.name}])

        rule.execute(message)

        nose.tools.assert_equal(
            message.state,
            SMSMessageState.FINAL_FAILED.name)


class TestExpireSMSMessageRule(za.test.biz.FakeServiceFixture):
    def inner_setup(self):
        self._rule = biz.tasks.sms_message.ExpireSMSMessageRule()

    def assert_rule_checks_match(self, message_specs, expected):
        messages = create_messages(message_specs)

        for message in messages:
            nose.tools.assert_equal(self._rule.check(message), expected)

    def test_check__not_expired__false_returned(self):
        message_specs_not_expired = [
            {"state": SMSMessageState.IN_TRANSIT.name},
            {"state": SMSMessageState.FINAL_DELIVERED.name}]

        self.assert_rule_checks_match(message_specs_not_expired, False)

    def test_check__expired__true_returned(self):
        message_specs_expired = [
            {
                "state": SMSMessageState.SCHEDULED.name,
                "created_when": times.now() - dt.timedelta(hours=73)},
            {
                "state": SMSMessageState.IN_TRANSIT.name,
                "created_when": times.now() - dt.timedelta(hours=73)}]

        self.assert_rule_checks_match(message_specs_expired, True)

    def test_execute__scheduled_message__new_state_correct(self):
        # create messages and apply rule
        messages = create_messages([
            {"state": SMSMessageState.SCHEDULED.name},
            {"state": SMSMessageState.IN_TRANSIT.name}])

        for message in messages:
            self._rule.execute(message)

        # verify new states
        (message_scheduled, message_in_transit) = messages

        nose.tools.assert_equal(
            message_scheduled.state,
            SMSMessageState.FINAL_NOT_SENT.name)
        nose.tools.assert_equal(
            message_in_transit.state,
            SMSMessageState.FINAL_UNCONFIRMED.name)
