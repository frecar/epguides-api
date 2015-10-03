import json
from django.http import HttpResponse
from .models import get_show_by_name
from .utils import list_all_epguides_keys_redis, EpisodeNotFoundException


def shows(request):
    result = []

    for epguides_name in list_all_epguides_keys_redis():
        try:
            show = get_show_by_name(epguides_name)

            if not show:
                continue

            host = "epguides.frecar.no"

            show.episodes = "{0}show/{1}/".format(host, epguides_name)
            show.next_episode = "{0}show/{1}/next".format(host, epguides_name)
            show.last_episode = "{0}show/{1}/last".format(host, epguides_name)
            show.imdb_url = "http://www.imdb.com/title/{0}".format(show.imdb_id)
            show.epguides_url = "http://www.epguides.com/{0}".format(epguides_name)
            result.append(show)
        except EpisodeNotFoundException:
            continue

    return HttpResponse(json.dumps(result), content_type="application/json")


def show(request, key):
    return HttpResponse(key)
