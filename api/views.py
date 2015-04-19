import csv
import io
from flask import request

from app import app

from models import Show
from utils import json_response, EpisodeNotFoundException, add_epguides_key_to_redis, \
    list_all_epguides_keys_redis
from werkzeug.utils import redirect


@app.route("/")
def redirect_to_docs():
    return redirect("http://epguides-api.readthedocs.org/en/latest/")

@app.route('/show/')
def discover_shows():
    result = []

    for epguides_name in list_all_epguides_keys_redis():

        show = Show(epguides_name)
        show.episodes = "{0}{1}/".format(request.base_url, epguides_name)
        show.next_episode = "{0}{1}/next".format(request.base_url, epguides_name)
        show.last_episode = "{0}{1}/last".format(request.base_url, epguides_name)
        show.imdb_url = "http://www.imdb.com/title/{0}".format(show.imdb_id)
        show.epguides_url = "http://www.epguides.com/{0}".format(epguides_name)
        result.append(show)

    return json_response(result)


@app.route('/show/<show>/')
def view_show(show):
    try:
        result_show = json_response(Show(show).get_episodes())
        add_epguides_key_to_redis(show)
        return result_show
    except EpisodeNotFoundException:
        return json_response({'error': 'Show not found'}, 404)


@app.route('/show/<show>/info/')
def view_show_info(show):
    try:
        return json_response(Show(show))

    except EpisodeNotFoundException:
        return json_response({'error': 'Show not found'}, 404)


@app.route('/show/<show>/<season>/<episode>/')
def episode(show, season, episode):
    try:
        return json_response({
            'episode': Show(show).get_episode(int(season), int(episode))
        })
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<show>/<season>/<episode>/released/')
def released(show, season, episode):
    try:
        return json_response({
            'status': Show(show).episode_released(int(season), int(episode))
        })
    except EpisodeNotFoundException:
        return json_response({
            'status': False
        })


@app.route('/show/<show>/<season>/<episode>/next/')
def next_from_given_episode(show, season, episode):
    try:
        return json_response({
            'episode': Show(show).get_episode(int(season), int(episode)).next()
        })
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<show>/<season>/<episode>/next/released/')
def next_released_from_given_episode(show, season, episode):
    try:

        next_episode = Show(show).get_episode(int(season), int(episode)).next()

        if not next_episode:
            raise EpisodeNotFoundException

        return json_response({
            'status': Show(show).get_episode(int(season), int(episode)).next().released()
        })

    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<show>/next/')
def next(show):
    try:
        return json_response({
            'episode': Show(show).next_episode()
        })

    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<show>/last/')
def last(show):
    try:
        return json_response({
            'episode': Show(show).last_episode()
        })

    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


if __name__ == '__main__':
    app.run(debug=True)
