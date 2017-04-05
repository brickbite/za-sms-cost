import time
import decimal
import datetime as dt
import pytz
import times
import nose.tools
import za.util
import za.util as module
import za.test.biz

from jinja2 import UndefinedError

biz = za.biz


class TestModule(object):
    def test_time_is_polite__various_times__correct_results(self):
        def assert_right_polite(local_str, tz_name, polite):
            utc = times.to_universal(local_str, tz_name)

            nose.tools.assert_equal(
                module.time_is_polite(utc, tz_name=tz_name),
                polite)

        cases = [
            ("2014-04-11T00:01:02", "America/Juneau", False),
            ("2014-04-11T04:22:53", "America/Juneau", False),
            ("2014-04-11T10:22:53", "America/Juneau", True),
            ("2014-04-11T21:22:53", "America/Juneau", True),
            ("2014-04-11T22:22:53", "America/Juneau", False),
            ("2014-04-11T23:59:53", "America/Juneau", False)]

        for case in cases:
            yield (assert_right_polite,) + case

    def test_localized_date_str__various_dates__correct_results(self):
        def assert_right_str(utc, locale, expected):
            nose.tools.assert_equal(
                module.localized_date_str(utc, locale),
                expected)

        cases = [
            (dt.datetime(2014, 1, 1, 23, 59, 0), 'en_US', u'Jan 1, 2014'),
            (dt.datetime(2014, 1, 1, 23, 59, 0), 'en_IN', u'02-Jan-2014'),
            (dt.datetime(2014, 1, 1, 1, 0, 0), 'en_US', u'Dec 31, 2013')]

        for case in cases:
            yield (assert_right_str,) + case

    def test_reformat_sql__simple_expression__correct_result(self):
        reformatted = module.reformat_sql("select * from foo where bar")

        nose.tools.assert_in("select", reformatted.lower())
        nose.tools.assert_equal(len(reformatted.splitlines()), 3)

    # TESTS: za.util.parse_time()

    def test_parse_time__bad_string__value_error_raised(self):
        nose.tools.assert_raises(ValueError, za.util.parse_time, "sdf")

    def test_parse_time__string_without_tz__return_correct(self):
        nose.tools.assert_equal(
            za.util.parse_time("2014-10-31T15:52:56"),
            dt.datetime(2014, 10, 31, 15, 52, 56))

    def test_parse_time__string_with_utc_tz__return_correct(self):
        nose.tools.assert_equal(
            za.util.parse_time("2014-10-31T15:52:56+00:00"),
            dt.datetime(2014, 10, 31, 15, 52, 56))

    def test_parse_time__string_with_non_utc_tz__return_correct(self):
        nose.tools.assert_equal(
            za.util.parse_time("2014-10-31T15:52:56+01:00"),
            dt.datetime(2014, 10, 31, 14, 52, 56))

    def test_parse_time__various_strings__round_trips_equal(self):
        # verify an invariant using a poor man's QuickCheck
        strings = [
            "1998-10-31T15:52:56",
            "1998-10-31 15:52:56-02:00",
            "2014-10-31T15:52:56",
            "2014-10-31T15:52:56+00:00",
            "2014-10-31T15:52:56+01:00"]

        def assert_round_trip_ok(string):
            nose.tools.assert_equal(
                za.util.parse_time(string),
                za.util.parse_time(za.util.parse_time(string).isoformat()))

        for string in strings:
            yield assert_round_trip_ok, string

    # TESTS: za.util.memoize()

    @module.memoize()
    def memoized(self, *args, **kwargs):
        return object()

    def test_memoize__same_args_kwargs__same_values_returned(self):
        nose.tools.assert_equal(
            len({self.memoized(1, "sdf", x="yz") for _ in xrange(8)}),
            1)

    def test_memoize__different_args__different_values_returned(self):
        nose.tools.assert_equal(
            len({self.memoized(1, "sdf" + str(i), x="y") for i in xrange(8)}),
            8)

    def test_memoize__different_kwargs__different_values_returned(self):
        nose.tools.assert_equal(
            len({self.memoized(1, "sdf", x=str(i)) for i in xrange(8)}),
            8)


class TestCustomJSONEncoder(object):
    input_output_pairs = [
        ({"a": 42, "b": {}}, '{"a": 42, "b": {}}'),
        (
            dt.datetime(2005, 11, 4, 15, 55, 42),
            '{"_type": "iso8601", "value": "2005-11-04T15:55:42"}'),
        (
            dt.datetime(2005, 11, 4, 15, 55, 42, 1234),
            '{"_type": "iso8601", "value": "2005-11-04T15:55:42.001234"}'),
        (
            decimal.Decimal("523.42"),
            '{"_type": "decimal", "value": "523.42"}'),
        (
            {"qwe": decimal.Decimal("523.42")},
            '{"qwe": {"_type": "decimal", "value": "523.42"}}')]

    def assert_jsonified_matches(self, input_, expected):
        output = za.util.jsonify(input_, sort_keys=True, indent=None)

        nose.tools.assert_equal(output, expected)

    def assert_dejsonified_matches(self, input_, expected):
        output = za.util.dejsonify(input_)

        nose.tools.assert_equal(output, expected)

    def test_jsonify__valid_value__correct_string_returned(self):
        for (value, string) in self.input_output_pairs:
            yield (self.assert_jsonified_matches, value, string)

    def test_jsonify__datetime_with_timezone__value_error_raised(self):
        pacific_time = pytz.timezone("US/Pacific")

        nose.tools.assert_raises(
            ValueError,
            za.util.jsonify,
            dt.datetime(2005, 11, 4, 15, 55, 42, tzinfo=pacific_time))

    def test_dejsonify__valid_string__correct_value_returned(self):
        for (value, string) in self.input_output_pairs:
            yield (self.assert_dejsonified_matches, string, value)


def test_forever__function_raises_value_error__function_called_again():
    calls = []

    def should_raise_interrupt():
        @za.util.forever(rest=4.0)
        def do():
            calls.append(time.time())

            if len(calls) == 1:
                raise ValueError()
            elif len(calls) == 2:
                raise KeyboardInterrupt()
            else:
                assert False

    nose.tools.assert_raises(KeyboardInterrupt, should_raise_interrupt)
    nose.tools.assert_equal(len(calls), 2)
    nose.tools.assert_greater(calls[1] - calls[0], 3.0)


class TestTemplates(za.test.biz.FakeServiceFixture):
    def test_render_sms_template_string__all_supported__render_ok(self):
        template = "\
            Payment received: {{ payment_amount }}\
            Explanation: {{ explanation }}\
            Keycode: {{ keycode }}"

        payment = biz.accounts.ManualPayment(
            phone="+11110000000",
            amount=15000,
            recorded=times.now())

        biz.accounts.record_payment(payment)

        body = za.render_sms_template_string(
            template,
            payment=payment,
            explanation="Saul Goodman",
            keycode="*123-456-789#")

        nose.tools.assert_in(str(payment.amount), body)
        nose.tools.assert_in("Saul Goodman", body)
        nose.tools.assert_in("*123-456-789#", body)

    def test_render_sms_template_string__none_obj__raises_undefined(self):
        template = "Account number: {{ account_number }}"

        nose.tools.assert_raises(UndefinedError,
                                 za.render_sms_template_string,
                                 template)

    def test_render_sms_template_string__math_with_None__raises_type_err(self):
        template = "{{ 42 - payment_amount }}"

        nose.tools.assert_raises(TypeError,
                                 za.render_sms_template_string,
                                 template,
                                 payment=None)

    def test_render_sms_template_string__unsupported__raises_undefined(self):
        template = "Unsupported {{ unsupported }}"

        nose.tools.assert_raises(UndefinedError,
                                 za.render_sms_template_string,
                                 template)
