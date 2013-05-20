from view import urls
import web

wsgi_app = web.application(urls, globals()).wsgifunc()