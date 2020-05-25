import requests
from redis import Redis

from api.app import app


def create_fb_pixel():
    if app.fb_enabled:
        def request_new_fb_pixel():
            from facebookads.api import FacebookAdsApi
            from facebookads.objects import AdsPixel, AdUser

            FacebookAdsApi.init(
                app.config['FB_MY_APP_ID'],
                app.config['FB_MY_APP_SECRET'],
                app.config['FB_MY_ACCESS_TOKEN']
            )

            me = AdUser(fbid='me')
            account = me.get_ad_accounts()[0]
            pixel = account.get_ads_pixels([AdsPixel.Field.code])
            return pixel.get_id(), pixel['code'].decode("utf-8")

        redis = Redis()
        pixel_id_key = 'epguides_fb_pixel_id'
        pixel_code_key = 'epguides_fb_pixel_code'
        if redis.get(pixel_id_key) and redis.get(pixel_code_key):
            return {
                'id': redis.get(pixel_id_key),
                'code': redis.get(pixel_code_key).decode("utf-8")
            }
        new_pixel = request_new_fb_pixel()
        redis.set(pixel_id_key, new_pixel[0])
        redis.set(pixel_code_key, new_pixel[1])
        return {'id': new_pixel[0], 'code': new_pixel[1].decode("utf-8")}
    else:
        return {'id': 0, 'code': ''}


def log_event(request, event):
    try:
        source_url = request.path
        if 'ignore_tracking' in request.url:
            return
        if app.fb_enabled:
            pixel = create_fb_pixel()
            requests.get(
                '{0}/tr?id={1}&ev={2}&{3}&noscript=1'.format(
                    'https://www.facebook.com',
                    pixel['id'],
                    event,
                    source_url
                ),
                cookies=request.cookies
            )
    except:
        pass
