from __future__ import absolute_import

from celery import Celery

import datetime as dt
import celery.utils.log
import za

# immediately patch logging to handle billiard process names, etc.;
# must happen before loggers are created, and this module is imported first
# (really a bug that this is necessary, but not fixed as of 2013-09-28)
celery.utils.log.ensure_process_aware_logger()

# remaing celery configuration
celery = Celery(
    __name__,
    broker=za.config.get("ZA_CELERY_BROKER_URL", za.DEFAULT_CELERY_BROKER_URL),
    include=["za.biz.tasks", "za.biz.tasks.sms_message"])

celery.conf.BROKER_HEARTBEAT = 30
celery.conf.BROKER_CONNECTION_TIMEOUT = 30
celery.conf.CELERYD_LOG_COLOR = False
celery.conf.CELERYD_TASK_TIME_LIMIT = 35 * 60
celery.conf.CELERYD_TASK_SOFT_TIME_LIMIT = 30 * 60
celery.conf.CELERY_ACCEPT_CONTENT = ["pickle"]
celery.conf.CELERYBEAT_SCHEDULE = {
    # SMS message tasks
    "generate-sms-message-send-tasks": {
        "task": "za.biz.tasks.sms_message.generate_send_tasks",
        "schedule": dt.timedelta(hours=1),
        "args": ()},
    "generate-sms-message-expire-tasks": {
        "task": "za.biz.tasks.sms_message.generate_expire_tasks",
        "schedule": dt.timedelta(minutes=1),
        "args": ()}}
    "generate-sms-message-retrieve-tasks": {
        "task": "za.biz.tasks.sms_message.generate_retrieve_tasks",
        "schedule": dt.timedelta(hours=1),
        "args": ()},
