import json
import re

import requests
from redis import Redis


class EpisodeNotFoundException(Exception):
    pass


class SimpleEncoder(json.JSONEncoder):
    def default(self, o):
        return o.__dict__

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


def parse_epguides_data(url):
    try:
        data = requests.get("http://epguides.com/" + url).text
        episodes = re.findall("([\d]+)\s*([\d]*)-([\d]+)"
                              "\s*[\w\-]*\s*([0-9][0-9]\/"
                              "\w*\/[0-9][0-9])[\s&\-#-<"
                              "\w='.;:\/]*>([)(:\w\s-]*)", data)
    except IndexError:
        return

    return episodes


def parse_epguides_info(url):
    try:
        print("http://epguides.com/{0}".format(url.decode("utf-8")))
        data = requests.get("http://epguides.com/" + url).text
        return re.findall('<h1><a href="[\w:\/\/.]*title\/([\w.:]*)">'
                          '([\w\s.&:\']*)[\w:\s)(]*<\/a>',
                          data)[0]

    except IndexError:
        return
