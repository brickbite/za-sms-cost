import za.blueprints.biz_api
import za.blueprints.twilio_hooks

named_blueprint_factories = {
    "biz_api": za.blueprints.biz_api.create_blueprint,
    "twilio_hooks": za.blueprints.twilio_hooks.create_blueprint}
