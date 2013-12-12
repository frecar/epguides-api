from contextlib import closing
import urllib
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
    with closing(urllib.urlopen("http://epguides.com/" + url)) as x:
        episodes = re.findall("([\d]*)\s*([\d]*)-([\d]*)\s*[\w\-]*"
                              "\s*([0-9][0-9]\/\w*\/[0-9][0-9])[\s"
                              "&\-#<\w='.;:\/]*>([\w\s]*)", x.read())

    return episodes