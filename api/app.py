import ConfigParser

from flask import Flask
from flask.ext.cache import Cache

config = ConfigParser.ConfigParser()
config.read(['defaults.cfg', 'local.cfg'])
CONFIG = {
    'DEBUG': config.getboolean('flask', 'debug'),
    'CACHE_TYPE': config.get('flask', 'cache_type')
}

app = Flask(__name__)
app.config.update(CONFIG)
cache = Cache(app)
