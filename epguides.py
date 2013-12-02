import urllib
from datetime import datetime, timedelta
import re

from beaker.cache import CacheManager
from beaker.util import parse_cache_config_options

cache_opts = {
    'cache.type': 'memory',
    'cache.expire': 604800,
}

cache = CacheManager(**parse_cache_config_options(cache_opts))


@cache.cache('get_seriedata')
def get_seriedata(url):

    f = urllib.urlopen("http://epguides.com/" + url)

    episodes = re.findall("([\d]*)\s*([\d]*)-([\d]*)\s*[\w\-]*\s*([0-9][0-9]\/\w*\/[0-9][0-9])[\s&\-#<\w='.;:\/]*>([\w\s]*)", f.read())

    show = {}

    for episode_info in episodes:

        try:
            season = int(episode_info[1])

            if season not in show:
                show[season] = []

            show[season].append([
                int(episode_info[2]),
                episode_info[4],
                datetime.strptime(episode_info[3], "%d/%b/%y").strftime("%Y-%m-%d")
            ])

        except Exception, e:
            print url + ": " + str(e)

    f.close()

    return show


def is_released(episode):
    release_date = datetime.strptime(episode[2], "%Y-%m-%d")

    if datetime.now() - timedelta(hours=32) > release_date:
        return True

    return False


def episode_released(show_name, season, episode):
    data = get_seriedata(show_name)
    if season in data or len(data[season]) >= episode:
        return is_released(data[season][episode - 1])

    return False


def next_episode(show_name):
    data = get_seriedata(show_name)
    season_number = len(data.keys())
    for episode in data[season_number]:
        if not is_released(episode):
            return {'episode': {
                'number': episode[0],
                'season': season_number,
                'title': episode[1],
                'release_date': episode[2]
            }}
