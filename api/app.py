import configparser
import os

from flask import Flask
from flask_caching import Cache
from raven.contrib.flask import Sentry

config = configparser.ConfigParser()
config.read(["defaults.cfg", os.path.expanduser('~/epguidesapi.cfg')])
CONFIG = {
    'SENTRY_DSN': config.get('flask', 'sentry_dsn'),
    'BASE_URL': config.get('flask', 'base_url'),
    'DEBUG': config.getboolean('flask', 'debug'),
    'FB_MY_APP_ID': config.get('flask', 'fb_my_app_id'),
    'FB_MY_APP_SECRET': config.get('flask', 'fb_my_app_secret'),
    'FB_MY_ACCESS_TOKEN': config.get('flask', 'fb_my_access_token'),
    'GA_TRACKER_ID': config.get('flask', 'ga_tracker_id'),
    'GA_ENABLED': config.get('flask', 'ga_enabled'),
}

app = Flask(__name__)
app.config.update(CONFIG)
app.fb_enabled = False

if config.getboolean('flask', 'fb_enabled'):
    app.fb_enabled = True

cache = Cache(app, config={'CACHE_TYPE': 'redis',
                           'CACHE_KEY_PREFIX': 'epguides_cache:',
                           'CACHE_DEFAULT_TIMEOUT': 3600})

if CONFIG['SENTRY_DSN']:
    sentry = Sentry(app, dsn=CONFIG['SENTRY_DSN'])
