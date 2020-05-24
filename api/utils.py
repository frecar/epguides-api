import csv
import io
import json
import re
import random
from datetime import datetime

import requests
from flask import make_response
from redis import Redis

from app import cache

TWELVE_HOURS_SECONDS = 43200


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

    all_keys = list_all_epguides_keys_redis(redis_queue_key=redis_queue_key)

    if epguides_name not in all_keys:
        redis.lpush(redis_queue_key, epguides_name)


def list_all_epguides_keys_redis(redis_queue_key="epguides_api:keys"):
    redis = Redis()

    res = list(set([
        x.decode("utf-8")
        for x in redis.lrange(redis_queue_key, 0, redis.llen(redis_queue_key))
    ]))
    random.shuffle(res)
    return res


def format_title(title):
    pattern = "[<a\s\w\=\'\"\:\/\.\-]*>(.*)</a>"

    if title.startswith("<a"):
        parsed_title_groups = re.findall(pattern, title)
        if len(parsed_title_groups) == 1:
            title = parsed_title_groups[0]

    return title.strip()


def parse_date(date):
    strptime = datetime.strptime

    valid_date_formats = ["%d %b %y", "%d/%b/%y", "%Y-%m-%d"]

    for date_format in valid_date_formats:
        try:
            dd = strptime(date, date_format)
            # Hack to support old tv shows
            if dd.year > datetime.now().year + 2:
                dd = dd.replace(year=dd.year - 100)
            return dd.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def csv_reader_from_url(url):
    data = requests.get(url).text
    csvio = io.StringIO(data, newline="")
    return csv.reader(csvio)


def parse_csv_file(url, row_map):
    result = []

    for row in csv_reader_from_url(url):
        episode = {}
        if row:
            try:
                for key, val in row_map.items():
                    episode[key] = row[val]
                result.append(episode)
            except IndexError:
                continue
    return result


def parse_epguides_tvrage_csv_data(id):
    url = 'http://epguides.com/common/exportToCSV.asp?rage={0}'.format(id)
    row_map = {'season': 1, 'number': 2, 'release_date': 4, 'title': 5}
    return parse_csv_file(url, row_map)


def parse_epguides_maze_csv_data(id):
    url = 'http://epguides.com/common/exportToCSVmaze.asp?maze={0}'.format(id)
    row_map = {'season': 1, 'number': 2, 'release_date': 3, 'title': 4}
    return parse_csv_file(url, row_map)


@cache.memoize(timeout=TWELVE_HOURS_SECONDS)
def parse_epguides_data(url):
    data = requests.get("http://epguides.com/" + url).text
    if 'exportToCSV.asp' in data:
        rage_ids = re.findall("exportToCSV\.asp\?rage=([\d+]*)", data)
        if rage_ids:
            return parse_epguides_tvrage_csv_data(rage_ids[0])
    elif 'exportToCSVmaze' in data:
        maze_ids = re.findall("exportToCSVmaze\.asp\?maze=([\d]*)", data)
        if maze_ids:
            return parse_epguides_maze_csv_data(maze_ids[0])

    return []


@cache.memoize(timeout=TWELVE_HOURS_SECONDS)
def parse_epguides_info(url):
    try:
        data = requests.get("http://epguides.com/" + url).text
        return re.findall('<h2><a href="[\w\:\/\/.]*title\/(.*)">(.*)<\/a>',
                          data)[0]

    except IndexError:
        return
