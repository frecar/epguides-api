import web
import json

from epguides import get_seriedata, episode_released, next_episode, last_episode

urls = (
    '/show/(\w*)/?', 'view.index',
    '/show/(\w+)/next/?', 'view.next',
    '/show/(\w+)/last/?', 'view.last',
    '/show/(\w+)/(\d+)/(\d+)/released/?', 'view.released'
)


class index:
    def GET(self, show):
        return json.dumps(get_seriedata(show))


class released:
    def GET(self, show, season, episode):
        return json.dumps({
            'status': episode_released(show, int(season), int(episode))
        })


class next:
    def GET(self, show):
        return json.dumps(next_episode(show))


class last:
    def GET(self, show):
        return json.dumps(last_episode(show))


if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()
