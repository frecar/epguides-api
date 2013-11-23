import urllib
import datetime
import re
import json

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
                datetime.datetime.strptime(episode_info[3], "%d/%b/%y").strftime("%Y-%m-%d")
            ])

        except Exception, e:
            print url + ": " + str(e)

    f.close()

    return json.dumps(show)


def episode_released(show_name, season, episode):
    status = False
    data = json.loads(get_seriedata(show_name))

    episode = int(episode)

    if season in data or len(data[season]) >= episode:
        release_date = datetime.datetime.strptime(data[season][episode - 1][2], "%Y-%m-%d")

        if datetime.datetime.now() - datetime.timedelta(hours=32) > release_date:
            status = True

    return json.dumps({'status': status})
