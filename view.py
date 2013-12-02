import web
import json

from epguides import get_seriedata, episode_released

urls = (
    '/show/(\w*)/?', 'view.index',
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

if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()
