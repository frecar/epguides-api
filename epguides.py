import urllib
import datetime
import re
import json
import web
import redis

def get_seriedata(url):
    f = urllib.urlopen("http://epguides.com/" + url)

    episodes = re.findall("([\d]*)\s*([\d]*)-([\d]*)\s*[\w\-]*\s*([0-9][0-9]\/\w*\/[0-9][0-9])[\s&\-#<\w='.;:\/]*>([\w\s]*)", f.read())

    show = {}

    for episode_info in episodes:

        season = int(episode_info[1])

        if season not in show:
            show[season] = []

        show[season].append([
            int(episode_info[2]),
            episode_info[4],
            datetime.datetime.strptime(episode_info[3], "%d/%b/%y").strftime("%Y-%m-%d")
        ])

    f.close()


    return json.dumps(show)


def episode_released(show_name, season, episode):

    data = json.loads(urllib.urlopen(web.ctx.home + "/show/" + show_name).read())
    
    response = {'status': False}

    episode = int(episode)

    if season not in data or len(data[season]) < episode:
        return json.dumps(response)

    release_date = datetime.datetime.strptime(data[season][episode - 1][2], "%Y-%m-%d")

    if datetime.datetime.now() - datetime.timedelta(hours=32) > release_date:
        response['status'] = True

    return json.dumps(response)
