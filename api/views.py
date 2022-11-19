import random

from flask import render_template, request

from api.app import app
from api.exceptions import EpisodeNotFoundException, SeasonNotFoundException, ShowNotFoundException
from api.metrics import create_fb_pixel, log_event
from api.models import get_show_by_key
from api.utils import add_epguides_key_to_redis, remove_epguides_key_to_redis, json_response, list_all_epguides_keys_redis


@app.route("/")
def overview():
    log_event(request, "ViewFrontPage")
    return render_template('index.html',
                           base_url=app.config['BASE_URL'],
                           fb_pixel=create_fb_pixel()['code'],
                           ga_enabled=app.config['GA_ENABLED'],
                           ga_tracker_id=app.config['GA_TRACKER_ID'])


@app.route("/api/examples/")
def examples():
    base_url = app.config['BASE_URL']
    show = list_all_epguides_keys_redis()[0]
    return json_response([
        {
            'title': 'All tv shows',
            'path': '{0}show/'.format(base_url),
            'limit': 3,
        }, {
            'title': 'Next episode of show',
            'path': '{0}show/{1}/next/'.format(base_url,show)
        }, {
            'title': 'Last episode of show',
            'path': '{0}show/{1}/last/'.format(base_url,show)
        }, {
            'title': 'First episode of show',
            'path': '{0}show/{1}/first/'.format(base_url, show)
        }, {
            'title': 'Lookup specific episode',
            'path': '{0}show/{1}/1/1/'.format(base_url, show)
        }, {
            'title': 'Meta data for show',
            'path': '{0}show/{1}/info/'.format(base_url, show)
        }, {
            'title': 'Check if specific episode is released',
            'path': '{0}show/{1}/1/1/released/'.format(base_url, show)
        }, {
            'title': 'Lookup next episode from given episode',
            'path': '{0}show/{1}/1/1/next/'.format(base_url,show)
        }, {
            'title': 'Lookup next episode from given episode (new season)',
            'path': '{0}show/{1}/1/1/next/'.format(base_url,show)
        }, {
            'title': 'Check if next episode from given episode is released',
            'path': '{0}show/{1}/1/1/next/released/'.format(
                base_url,show)
        }
    ])


@app.route('/show/')
def discover_shows():
    result = []
    log_event(request, "ViewShowsOverview")

    for epguides_name in list_all_epguides_keys_redis():
        try:
            show = {
                'epguides_name': epguides_name,
                'episodes': "{0}show/{1}/".format(app.config['BASE_URL'], epguides_name),
                'first_episode': "{0}show/{1}/first/".format(app.config['BASE_URL'], epguides_name),
                'next_episode': "{0}show/{1}/next/".format(app.config['BASE_URL'], epguides_name),
                'last_episode': "{0}show/{1}/last/".format(app.config['BASE_URL'], epguides_name),
                'epguides_url': "http://www.epguides.com/{0}".format(epguides_name)
            }
            result.append(show)
        except EpisodeNotFoundException:
            continue

    return json_response(result)

@app.route('/random-show/')
def view_random_show():
    log_event(request, "ViewShowRandom")
    show = list_all_epguides_keys_redis()[0]
    return view_show(show)


@app.route('/show/<string:show>/')
def view_show(show):
    log_event(request, "ViewShow")
    add_epguides_key_to_redis(show)
    try:
        return json_response(get_show_by_key(show).get_show_data())
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/info/')
def view_show_info(show):
    log_event(request, "ViewShowInfo")
    add_epguides_key_to_redis(show)
    try:
        return json_response(get_show_by_key(show))
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/<int:season>/<int:episode>/')
def episode(show, season, episode):
    log_event(request, "ViewEpisode")
    add_epguides_key_to_redis(show)
    try:
        return json_response({
            'episode': get_show_by_key(show).get_episode(int(season), int(episode))
        })
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/<int:season>/<int:episode>/released/')
def released(show, season, episode):
    log_event(request, "ViewReleased")
    add_epguides_key_to_redis(show)
    try:
        show = get_show_by_key(show)
        return json_response({
            'status': show.episode_released(
                int(season), int(episode))
        })
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/<int:season>/<int:episode>/next/')
def next_from_given_episode(show, season, episode):
    log_event(request, "ViewNextFromGivenEpisode")
    add_epguides_key_to_redis(show)
    try:
        show = get_show_by_key(show)
        return json_response({
            'episode': show.get_episode(
                int(season), int(episode)).next()
        })
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/<int:season>/<int:episode>/next/released/')
def next_released_from_given_episode(show, season, episode):
    log_event(request, "ViewNextReleasedFromGivenEpisode")
    add_epguides_key_to_redis(show)
    try:
        show = get_show_by_key(show)
        next_episode = show.get_episode(season, episode).next()
        if not next_episode:
            raise EpisodeNotFoundException
        return json_response({'status': next_episode.released()})
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/next/')
def next(show):
    log_event(request, "ViewShowNextEpisode")
    add_epguides_key_to_redis(show)
    try:
        return json_response({'episode': get_show_by_key(show).next_episode()})
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/last/')
def last(show):
    log_event(request, "ViewShowLastEpisode")
    add_epguides_key_to_redis(show)
    try:
        return json_response({'episode': get_show_by_key(show).last_episode()})
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)


@app.route('/show/<string:show>/first/')
def first(show):
    log_event(request, "ViewShowFirstEpisode")
    add_epguides_key_to_redis(show)
    try:
        return json_response({
            'episode': get_show_by_key(show).first_episode()
        })
    except ShowNotFoundException:
        remove_epguides_key_to_redis(show)
        return json_response({'error': 'Show not found'}, 404)
    except SeasonNotFoundException:
        return json_response({'error': 'Season not found'}, 404)
    except EpisodeNotFoundException:
        return json_response({'error': 'Episode not found'}, 404)
