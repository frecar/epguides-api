import configparser
import os

from flask import Flask
from flask_caching import Cache
from raven.contrib.flask import Sentry

config = configparser.ConfigParser()
config.read(["defaults.cfg", os.path.expanduser('~/epguidesapi.cfg')])

def get_base_url():
    url = config.get('flask', 'web_domain')

    if config.get('flask', 'web_port') not in ['80', '443']:
        url = url + ':' + config.get('flask', 'web_port')

    if config.get('flask', 'web_ssl') == 'true':
        url = 'https://' + url
    else:
        url = 'http://' + url

    return url + '/'

CONFIG = {
    'SENTRY_DSN': config.get('flask', 'sentry_dsn'),
    'DEBUG': config.getboolean('flask', 'debug'),
    'GA_TRACKER_ID': config.get('flask', 'ga_tracker_id'),
    'GA_ENABLED': config.get('flask', 'ga_enabled'),
    'REDIS_HOST': config.get('flask', 'redis_host'),
    'REDIS_PORT': config.get('flask', 'redis_port'),
    'REDIS_DB': config.get('flask', 'redis_db'),
    'REDIS_PASS': config.get('flask', 'redis_pass'),
    'WEB_CACHE_TTL': config.get('flask', 'web_cache_ttl'),
    'WEB_DOMAIN': config.get('flask', 'web_domain'),
    'WEB_HOST': config.get('flask', 'web_host'),
    'WEB_PORT': config.get('flask', 'web_port'),
    'WEB_SSL': config.get('flask', 'web_ssl') == 'true',
    'BASE_URL': get_base_url(),
}

app = Flask(__name__)
app.config.update(CONFIG)

cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_KEY_PREFIX': 'epguides_cache:',
    'CACHE_REDIS_PASSWORD': app.config['REDIS_PASS'],
    'CACHE_DEFAULT_TIMEOUT': 3600
})

sentry = app

if CONFIG['SENTRY_DSN']:
    sentry = Sentry(cache, dsn=CONFIG['SENTRY_DSN'])

app = sentry