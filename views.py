import ConfigParser
from flask import Flask
from flask.ext.cache import Cache

from models import EpisodeNotFoundException, Show
from utils import json_response

config = ConfigParser.ConfigParser()
config.read(['defaults.cfg', 'local.cfg'])
CONFIG = {
    'DEBUG': config.getboolean('flask', 'debug'),
    'CACHE_TYPE': config.get('flask', 'cache_type')
}

app = Flask(__name__)
app.config.update(CONFIG)
cache = Cache(app)


@app.route('/show/<show>/')
def view_show(show):
    return json_response(Show(show).get_episodes())


@app.route('/show/<show>/<season>/<episode>/released/')
def released(show, season, episode):
    try:
        return json_response({
            'status': Show(show).episode_released(int(season), int(episode))
        })
    except EpisodeNotFoundException:
        return json_response({
            'error': 'Episode not found'
        }, 404)


@app.route('/show/<show>/<season>/<episode>/next/')
def next_from_given_episode(show, season, episode):
    try:
        return json_response({
            'episode': Show(show).get_episode(int(season), int(episode)).next()
        })
    except EpisodeNotFoundException:
        return json_response({
            'error': 'Episode not found'
        }, 404)


@app.route('/show/<show>/<season>/<episode>/next/released/')
def next_released_from_given_episode(show, season, episode):
    try:
        return json_response({
            'status': Show(show).get_episode(int(season), int(episode)).next().released()
        })
    except EpisodeNotFoundException:
        return json_response({
            'error': 'Episode not found'
        }, 404)


@app.route('/show/<show>/next/')
def next(show):
    try:
        return json_response({
            'episode': Show(show).next_episode()
        })

    except EpisodeNotFoundException:
        return json_response({
            'error': 'Episode not found'
        }, 404)


@app.route('/show/<show>/last/')
def last(show):
    try:
        return json_response({
            'episode': Show(show).last_episode()
        })

    except EpisodeNotFoundException:
        return json_response({
            'error': 'Episode not found'
        }, 404)

if __name__ == "__main__":
    app.run()
