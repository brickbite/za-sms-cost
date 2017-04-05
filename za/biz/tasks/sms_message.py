import datetime as dt
import times
import za.sms
import za.biz.tasks

from za.celery import celery as za_celery
from za.biz.accounts import (
    SMSMessageState,
    SMSMessage)

biz = za.biz
logger = za.get_logger(__name__)

# various constants
EXPIRATION_PERIOD = dt.timedelta(hours=72)


@za_celery.task
def generate_send_tasks():
    """Generate refresh tasks for SMS message scheduling."""

    # fetch candidate calls
    messages = (
        biz.g.session.query(SMSMessage)
        .filter(
            SMSMessage.state == SMSMessageState.SCHEDULED.name,
            SMSMessage.created_when > times.now() - EXPIRATION_PERIOD)
        .all())

    logger.info("retrieved %i candidate messages", len(messages))

    # generate associated asynchronous calls
    for message in messages:
        sms_message_rule = SendSMSMessageRule()
        sms_message_rule.delay(message.id)


@za_celery.task
def generate_expire_tasks():
    """Generate refresh tasks for SMS message expiration."""

    # fetch candidate calls
    messages = (
        biz.g.session.query(SMSMessage)
        .filter(
            SMSMessage.state.in_([
                SMSMessageState.SCHEDULED.name,
                SMSMessageState.IN_TRANSIT.name]),
            SMSMessage.created_when <= times.now() - EXPIRATION_PERIOD)
        .all())

    logger.info("retrieved %i candidate messages", len(messages))

    # generate associated asynchronous calls
    for message in messages:
        sms_message_rule = ExpireSMSMessageRule()
        sms_message_rule.delay(message.id)


class SendSMSMessageRule(biz.tasks.Rule):
    """ECA rule: send SMS messages when scheduled."""

    # XXX avoid multiple handlers executing the same call

    def __init__(self, router=None):
        if router is None:
            router = za.sms.get_default_router()

        self._router = router

    def check(self, message):
        return (
            message.state == SMSMessageState.SCHEDULED.name
            and message.age < EXPIRATION_PERIOD)

    def execute(self, message):
        try:
            message_body = message.body

            if len(message_body) > 160:
                logger.warning("outgoing SMS message truncated at 160 chars")

                message_body = message_body[:160]

            logger.info(
                "sending SMS message to %s with body %s",
                message.recipient,
                message_body)
            route_info = self._router.send_sms(
                message.recipient,
                message_body)
        except:
            logger.exception("error while sending SMS")

            message.update(state=SMSMessageState.FINAL_FAILED)
        else:
            logger.info("sent SMS; route_info: %s", route_info)

            message.route_key = route_info["route_key"]
            message.route_message_key = route_info["route_message_key"]
            message.sent_when = times.now()
            message.update(state=route_info["state"], force_report=False)

        biz.g.session.flush()


class ExpireSMSMessageRule(biz.tasks.Rule):
    """ECA rule: eventually expire SMS messages."""

    # XXX doesn't handle concurrency

    def __init__(self, router=None):
        if router is None:
            router = za.sms.get_default_router()

        self._router = router

    def check(self, message):
        return (
            message.state in [
                SMSMessageState.SCHEDULED.name,
                SMSMessageState.IN_TRANSIT.name]
            and message.age >= EXPIRATION_PERIOD)

    def execute(self, message):
        logger.info("expiring message %r after %s", message, message.age)

        expiration_states = {
            SMSMessageState.SCHEDULED.name: SMSMessageState.FINAL_NOT_SENT,
            SMSMessageState.IN_TRANSIT.name: SMSMessageState.FINAL_UNCONFIRMED}

        message.update(state=expiration_states[message.state])
