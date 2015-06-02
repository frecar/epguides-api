import json
import re
import urllib

from flask import make_response
from json import JSONEncoder
from contextlib import closing

from app import cache
from redis import Redis


class EpisodeNotFoundException(Exception):
    pass


class SimpleEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__


def json_response(data, status=200):
    response = make_response(json.dumps(data, cls=SimpleEncoder), status)
    response.mimetype = 'application/json'
    return response


def add_epguides_key_to_redis(epguides_name):
    redis = Redis()

    redis_queue_key = "epguides_api:keys"
    all_keys = redis.lrange(redis_queue_key, 0, redis.llen(redis_queue_key))

    if epguides_name not in all_keys:
        redis.lpush(redis_queue_key, epguides_name)


def list_all_epguides_keys_redis():
    redis = Redis()
    redis_queue_key = "epguides_api:keys"
    return redis.lrange(redis_queue_key, 0, redis.llen(redis_queue_key))


@cache.memoize(60 * 60 * 24 * 7)
def parse_epguides_data(url):

    try:
        with closing(urllib.urlopen("http://epguides.com/" + url)) as x:
            episodes = re.findall("([\d]+)\s*([\d]*)-([\d]+)"
                                  "\s*[\w\-]*\s*([0-9][0-9]\/"
                                  "\w*\/[0-9][0-9])[\s&\-#-<"
                                  "\w='.;:\/]*>([)(:\w\s-]*)", x.read())

    except IndexError:
        return

    return episodes


@cache.memoize(60 * 60 * 24 * 7)
def parse_epguides_info(url):

    try:
        with closing(urllib.urlopen("http://epguides.com/" + url)) as x:
            return re.findall('<h1><a href="[\w:\/\/.]*title\/([\w.:]*)">'
                              '([\w\s.&:\']*)[\w:\s)(]*<\/a>',
                              x.read())[0]

    except IndexError:
        return
