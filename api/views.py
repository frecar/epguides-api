import random

from flask import render_template

from api.app import app
from api.exceptions import EpisodeNotFoundException, SeasonNotFoundException, ShowNotFoundException
from api.models import get_show_by_key
from api.utils import list_all_epguides_keys_redis
from flask import jsonify


@app.route("/")
def overview():
    return render_template(
        'index.html',
        base_url=app.config['BASE_URL'],
        ga_enabled=app.config['GA_ENABLED'],
        ga_tracker_id=app.config['GA_TRACKER_ID'],
        web_ssl=app.config['WEB_SSL'],
        num_total_shows=len(list_all_epguides_keys_redis())
    )


@app.route('/debug-sentry')
def trigger_error():
    division_by_zero = 1 / 0


@app.route("/api/examples/")
def examples():
    base_url = app.config['BASE_URL']
    show = list_all_epguides_keys_redis()[0]
    return jsonify([
        {
            'title': 'All tv shows',
            'path': '{0}show/'.format(base_url),
            'limit': 3,
        }, {
            'title': 'Next episode of show',
            'path': '{0}show/{1}/next/'.format(base_url, show)
        }, {
            'title': 'Last episode of show',
            'path': '{0}show/{1}/last/'.format(base_url, show)
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
            'path': '{0}show/{1}/1/1/next/'.format(base_url, show)
        }, {
            'title': 'Lookup next episode from given episode (new season)',
            'path': '{0}show/{1}/1/1/next/'.format(base_url, show)
        }, {
            'title': 'Check if next episode from given episode is released',
            'path': '{0}show/{1}/1/1/next/released/'.format(
                base_url, show)
        }
    ])


@app.route('/show/')
def discover_shows():
    result = []

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

    return jsonify(result)


@app.route('/random-show/')
def view_random_show():
    show = list_all_epguides_keys_redis()[0]
    return view_show(show)


@app.route('/show/<string:show>/')
def view_show(show):
    return jsonify(get_show_by_key(show).episodes_as_json())


@app.route('/show/<string:show>/info/')
def view_show_info(show):
    return jsonify(get_show_by_key(show).as_dict())


@app.route('/show/<string:show>/<int:season>/<int:episode>/')
def episode(show, season, episode):
    return jsonify({'episode': get_show_by_key(show).get_episode(int(season), int(episode)).as_dict()})


@app.route('/show/<string:show>/<int:season>/<int:episode>/released/')
def released(show, season, episode):
    return jsonify({'status': get_show_by_key(show).episode_released(int(season), int(episode))})


@app.route('/show/<string:show>/<int:season>/<int:episode>/next/')
def next_from_given_episode(show, season, episode):
    show = get_show_by_key(show)
    next_episode = show.get_episode(season, episode).next()
    if not next_episode:
        raise EpisodeNotFoundException
    return jsonify({'episode': get_show_by_key(show).get_episode(int(season), int(episode)).next().as_dict()})

@app.route('/show/<string:show>/<int:season>/<int:episode>/next/released/')
def next_released_from_given_episode(show, season, episode):
    show = get_show_by_key(show)
    next_episode = show.get_episode(season, episode).next()
    if not next_episode:
        raise EpisodeNotFoundException
    return jsonify({'status': next_episode.released()})


@app.route('/show/<string:show>/next/')
def next(show):
    return jsonify({'episode': get_show_by_key(show).next_episode().as_dict()})


@app.route('/show/<string:show>/last/')
def last(show):
    return jsonify({'episode': get_show_by_key(show).last_episode().as_dict()})


@app.route('/show/<string:show>/first/')
def first(show):
    return jsonify({'episode': get_show_by_key(show).first_episode().as_dict()})
