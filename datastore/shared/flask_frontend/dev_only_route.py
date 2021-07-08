from flask import abort

from datastore.shared.di import injector
from datastore.shared.services import EnvironmentService


def dev_only_route(fn):
    def wrapper(*args, **kwargs):
        env_service = injector.get(EnvironmentService)
        if not env_service.is_dev_mode():
            abort(404)

        return fn(*args, **kwargs)

    return wrapper
