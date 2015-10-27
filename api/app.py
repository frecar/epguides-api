import configparser
import os

from flask import Flask
from flask.ext.cache import Cache
from raven.contrib.flask import Sentry

config = configparser.ConfigParser()
config.read(["defaults.cfg", os.path.expanduser('~/epguidesapi.cfg')])
CONFIG = {
    'SENTRY_DSN': config.get('flask', 'sentry_dsn'),
    'BASE_URL': config.get('flask', 'base_url'),
    'DEBUG': config.getboolean('flask', 'debug')
}

app = Flask(__name__)
app.config.update(CONFIG)
cache = Cache(app, config={'CACHE_TYPE': 'redis',
                           'CACHE_KEY_PREFIX': 'epguides_cache:',
                           'CACHE_DEFAULT_TIMEOUT': 3600})

if CONFIG['SENTRY_DSN']:
    sentry = Sentry(app, dsn=CONFIG['SENTRY_DSN'])
