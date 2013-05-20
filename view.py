from epguides import get_seriedata, episode_released
import web

urls = (
    '/show/(\w*)/?', 'view.index',
    '/released/(\w+)/(\d+)/(\d+)/?', 'view.released'
)


class index:
    def GET(self, show):
        return get_seriedata(show)


class released:
    def GET(self, show, season, episode):
        return episode_released(show, season, episode)


if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()