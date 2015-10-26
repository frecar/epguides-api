import json
import re

import requests
from flask import make_response
from redis import Redis

from .app import cache


class EpisodeNotFoundException(Exception):
    pass


class SimpleEncoder(json.JSONEncoder):
    def default(self, o):
        return o.__dict__


def json_response(data, status=200):
    response = make_response(json.dumps(data, cls=SimpleEncoder), status)
    response.mimetype = 'application/json'
    return response


def add_epguides_key_to_redis(epguides_name):
    redis = Redis()
    redis_queue_key = "epguides_api:keys"

    if epguides_name not in list_all_epguides_keys_redis(redis_queue_key=redis_queue_key):
        redis.lpush(redis_queue_key, epguides_name)


def list_all_epguides_keys_redis(redis_queue_key="epguides_api:keys"):
    redis = Redis()

    return [x.decode("utf-8") for x in
            redis.lrange(redis_queue_key, 0, redis.llen(redis_queue_key))]


@cache.memoize(60 * 60 * 24 * 7)
def parse_epguides_data(url):
    try:
        data = requests.get("http://epguides.com/" + url).text
        episodes = re.findall(
            "([\d]+)[.]\s*([\d]*)-([\d]*)\s*([\d]+\s[\w]*\s[\d]*)"
            "\s*[\s&\-#\"\'\-\<\w='.;:\/]*>([\)\(\:\w\'\"\_\s\-]*)",
            data)

    except IndexError:
        return

    return episodes


@cache.memoize(60 * 60 * 24 * 7)
def parse_epguides_info(url):
    try:
        data = requests.get("http://epguides.com/" + url).text
        return re.findall('<h1><a href="[\w:\/\/.]*title\/([\w.:]*)">'
                          '([\w\s.&:\']*)[\w:\s)(]*<\/a>',
                          data)[0]

    except IndexError:
        return
