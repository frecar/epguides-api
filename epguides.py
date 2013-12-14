import re
import urllib
from contextlib import closing

from views import cache


@cache.memoize(60 * 60 * 24 * 7)
def get_seriedata(url):
    with closing(urllib.urlopen("http://epguides.com/" + url)) as x:
        episodes = re.findall("([\d]*)\s*([\d]*)-([\d]*)\s*[\w\-]*"
                              "\s*([0-9][0-9]\/\w*\/[0-9][0-9])[\s"
                              "&\-#<\w='.;:\/]*>([\w\s]*)", x.read())

    return episodes
