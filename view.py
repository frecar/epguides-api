import web
import json

from encoders import EpisodeEncoder
from models import EpisodeNotFoundException, Show

urls = (
    '/show/(\w*)/?', 'view.index',
    '/show/(\w+)/next/?', 'view.next',
    '/show/(\w+)/last/?', 'view.last',
    '/show/(\w+)/(\d+)/(\d+)/released/?', 'view.released'
)


class index:
    def GET(self, show):
        return json.dumps(Show(show).get_episodes(), cls=EpisodeEncoder, indent=4)


class released:
    def GET(self, show, season, episode):
        return json.dumps({
            'status': Show(show).episode_released(int(season), int(episode))
        })


class next:
    def GET(self, show):
        try:
            return json.dumps(Show(show).next_episode(), cls=EpisodeEncoder, indent=4)
        except EpisodeNotFoundException:
            return json.dumps({
                'status': 'Episode not found'
            })


class last:
    def GET(self, show):
        try:
            return json.dumps(Show(show).last_episode(), cls=EpisodeEncoder, indent=4)
        except EpisodeNotFoundException:
            return json.dumps({
                'status': 'Episode not found'
            })


if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()