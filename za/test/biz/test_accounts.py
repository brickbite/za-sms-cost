# coding=utf-8

import uuid
import decimal
import datetime as dt
import sqlalchemy as sa
import times
import nose.tools
import za.biz.accounts

from nose.tools import (
    assert_true,
    assert_false,
    assert_raises)

from za.biz.accounts import PaymentCode

biz = za.biz
module = biz.accounts


def ago(**kwargs):
    return times.now() - dt.timedelta(**kwargs)


class TestSMSMessage(za.test.biz.FakeServiceFixture):
    def inner_setup(self):
        payment = biz.accounts.ManualPayment(
            phone="+11110000000",
            amount=100,
            recorded=times.now())

        biz.accounts.record_payment(payment)

    def test_init__with_enum__role_ok(self):
        msg = module.SMSMessage(
            recipient="+15550000000",
            body=unicode("body body body"),
            role=module.SMSMessageRole.CATCH_ALL)

        self.session.add(msg)
        self.session.commit()

        res = (
            self.session.query(biz.accounts.SMSMessage)
            .filter_by(id=msg.id)
            .first())

        nose.tools.assert_equal(res.recipient, "+15550000000")
        nose.tools.assert_equal(res.body, "body body body")
        nose.tools.assert_equal(type(res.role), module.SMSMessageRole)
        nose.tools.assert_equal(
            res.role,
            module.SMSMessageRole.CATCH_ALL)

    @nose.tools.raises(Exception)
    def test_init__with_bad_role_type__raises_fast(self):
        module.SMSMessage(
            recipient="+15550000000",
            body=unicode("body body body"),
            role=module.SMSMessageRole.CATCH_ALL.name)

    def test_update__state_provided__state_applied(self):
        message = module.SMSMessage(
            recipient="+15550000000",
            body=u"body body body",
            role=module.SMSMessageRole.HELP_GENERIC)
        state = module.SMSMessageState.IN_TRANSIT

        message.update(state)

        nose.tools.assert_equal(message.state, state.name)
        nose.tools.assert_is_none(message.error)
        nose.tools.assert_is_none(message.route_message_status)

    def test_update__all_values_provided__all_values_applied(self):
        message = module.SMSMessage(
            recipient="+15550000000",
            body=u"body body body",
            role=module.SMSMessageRole.HELP_GENERIC)
        state = module.SMSMessageState.IN_TRANSIT
        error = module.SMSMessageError.CALL_BARRED
        route_message_status = "route_status_xyz"

        message.update(state, error, route_message_status)

        nose.tools.assert_equal(message.state, state.name)
        nose.tools.assert_equal(message.error, error.name)
        nose.tools.assert_equal(
            message.route_message_status,
            route_message_status)


class TestRecordPayment(za.test.biz.FakeServiceFixture):
    def test_record_payment__airtel_za_to_valid_account__recorded(self):
        payment = biz.accounts.ManualPayment(
            phone="+15551234567",
            amount=decimal.Decimal(100.00))

        biz.accounts.record_payment(payment)

        messages = self.session.query(biz.accounts.SMSMessage).all()

        nose.tools.assert_equal(len(messages), 1)


class TestUser(za.test.biz.FakeServiceFixture):
    def fake_user(
            self,
            username="Alice",
            primary_phone="+15551234567",
            raw_password=None):
        user = biz.accounts.User(
            username=username,
            locale="en_KE",
            raw_password=unicode(username) if raw_password is None
            else raw_password,
            primary_phone=primary_phone)

        biz.g.session.add(user)

        return user

    def test_primary_phone__unique_constraint__raises(self):
        self.fake_user()

        biz.commit()

        # null primary-phone shouldn't raise
        self.fake_user(username="Bob", primary_phone=None)

        biz.commit()

        # duplicate phone should raise
        self.fake_user(username="Carol")

        nose.tools.assert_raises(
            sa.exc.IntegrityError,
            biz.commit)

    # TESTS: assign_password()

    def test_assign_password__some_password__password_matches(self):
        password = u"different→password"
        user = self.fake_user()

        user.assign_password(password)

        assert_true(user.password_matches(password))

    def test_assign_password__non_unicode__error_raised(self):
        user = self.fake_user()

        assert_raises(TypeError, user.assign_password, "not unicode")

    # TESTS: password_matches()

    def test_password_matches__various_passwords__same_password_matches(self):
        def assert_password_matches(password):
            user = self.fake_user(raw_password=password)

            assert_true(user.password_matches(password))

        passwords = [
            u"swordfish",
            u"special! !@#$&%*(^)\"chars",
            u"newlines\r\nand stuff",
            u"very ሴspecial 嘣characters"]

        for password in passwords:
            assert_password_matches(password)

    def test_password_matches__some_value__different_password_no_match(self):
        user = self.fake_user(raw_password=u"swordfish")

        assert_false(user.password_matches(u"sturgeon"))

    def test_password_matches__non_unicode__error_raised(self):
        user = self.fake_user()

        assert_raises(TypeError, user.password_matches, "not unicode")


class TestManualPayment(za.test.biz.FakeServiceFixture):
    # TESTS: ManualPayment.find_or_init()

    simple_kwargs = {
        "mpesa_transaction": "ABCDE1234",
        "amount": decimal.Decimal("444")}

    def test_find_or_init__match_exists__match_returned(self):
        xid = uuid.uuid4()
        payment = biz.accounts.ManualPayment(
            xid=xid,
            amount=10,
            recorded=times.now())

        biz.g.session.add(payment)
        biz.g.session.flush()

        (returned, new, reason) = module.ManualPayment.find_or_init(xid=xid)

        nose.tools.assert_is(returned, payment)
        nose.tools.assert_false(new)
        nose.tools.assert_equal(reason, PaymentCode.EXISTS)

    def test_find_or_init__no_match_exists__new_instance_returned(self):
        (returned, new, reason) = module.ManualPayment.find_or_init(
            amount=10,
            xid=uuid.uuid4())

        nose.tools.assert_is_instance(returned, module.ManualPayment)
        nose.tools.assert_true(new)
        nose.tools.assert_is_none(reason)
