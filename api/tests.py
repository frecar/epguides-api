import json
import unittest

from api import views


class TestViews(unittest.TestCase):

    def setUp(self):
        app = views.app
        app.config['CACHE_TYPE'] = 'simple'
        self.app = app.test_client()

    def tearDown(self):
        pass

    def response_to_json(self, response):
        return json.loads(response.data.decode("utf-8"))

    def assertStatusCode(self, response, expected):
        self.assertEqual(response._status_code, expected)

    def assertValidEpisodeObject(self, data):
        self.assertTrue('number' in data)
        self.assertTrue('season' in data)
        self.assertTrue('release_date' in data)
        self.assertTrue('title' in data)

    def test_show_view(self):
        response = self.app.get('/show/howimetyourmother/')
        self.assertStatusCode(response, 200)

        data = self.response_to_json(response)
        for season in data:
            for episode in data[season]:
                self.assertValidEpisodeObject(episode)

    def test_metadata_info(self):
        response = self.app.get('/show/howimetyourmother/info/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['title'],
                         "How I Met Your Mother")

    def test_metadata_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/info/')
        self.assertStatusCode(response, 404)

    def test_released_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/released/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['status'], True)

    def test_released_view_invalid_show(self):
        response = self.app.get(
            '/show/invalidshowtestrandomtext/1/1/released/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['status'], False)

    def test_given_episode_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

    def test_given_episode_view_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/1/1/')
        self.assertStatusCode(response, 404)

    def test_next_from_current_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/next/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

    def test_next_from_current_view_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/1/1/next/')
        self.assertStatusCode(response, 404)

    def test_next_from_current_view_does_not_exist(self):
        response = self.app.get('/show/howimetyourmother/15/1/next/')
        self.assertStatusCode(response, 404)

    def test_first_episode_query(self):
        response = self.app.get('/show/howimetyourmother/first/')
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

    def test_last_episode_query(self):
        response = self.app.get('/show/howimetyourmother/last/')
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

    def test_released_next_from_current_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/next/released/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['status'], True)

    def test_released_next_from_current_view_invalid_show(self):
        response = self.app.get(
            '/show/invalidshowtestrandomtext/1/1/next/released/')
        self.assertStatusCode(response, 404)

    def test_last_view(self):
        response = self.app.get('/show/howimetyourmother/last/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

        response = self.app.get('/show/gameofthrones/last/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

    def test_last_view_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/last/')
        self.assertStatusCode(response, 404)

    def test_next_released_from_given_episode(self):
        response = self.app.get('/show/howimetyourmother/next/')
        self.assertStatusCode(response, 404)

    def test_next_view(self):
        # test a show that is running, this might need to be updated some day
        response = self.app.get('/show/bigbangtheory/next/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

        response = self.app.get('/show/chuck/next/')
        self.assertStatusCode(response, 404)

    def test_next_view_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/next/')
        self.assertStatusCode(response, 404)

    def test_last_correct_show(self):
        response = self.app.get('/show/howimetyourmother/last/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode'])

        episode = self.response_to_json(response)['episode']
        self.assertEqual(episode['season'], 9)
        self.assertEqual(episode['number'], 24)

    def test_parse_date_correctly(self):

        shows_first_dates = [
            ('howimetyourmother', '2005-09-19'),
            ('bigbangtheory', '2007-09-24'),
            ('lost', '2004-09-22'),
            ('suits', '2011-06-23'),
            ('unforgettable', '2011-09-20'),
            ('walkingdead', '2010-10-31'),
            ('satisfaction', '2007-12-05')
        ]

        for show, first_date in shows_first_dates:
            response = self.app.get('/show/{0}/first/'.format(show))
            episode_json = self.response_to_json(response)['episode']

            self.assertEquals(first_date, episode_json['release_date'])

    def test_discover_shows_url(self):
        response = self.app.get('/show/')
        self.assertStatusCode(response, 200)

    def test_overview(self):
        response = self.app.get('/')
        self.assertStatusCode(response, 302)

    def test_first_last_valid_episodes(self):

        shows = ['howimetyourmother', 'persona4',
                 'bob', 'bobthebuilder', 'chuck', 'bigbangtheory',
                 'gameofthrones', 'screamqueens', 'brink', 'stateofaffairs',
                 'chicagofire', 'originals', 'sense8', 'modernfamily',
                 'affair', 'lastweektonightwithjohnoliver', 'vampirediaries',
                 'tonightshowstarringjimmyfallon', 'unforgettable',
                 'dailyshow', 'latelateshowwithjamescorden', '8outof10cats',
                 'doctorwho_2005', '24', 'aliensinamerica']

        for show in shows:
            response = self.app.get('/show/{0}/first/'.format(show))
            self.assertStatusCode(response, 200)

            episode_json_obj = self.response_to_json(response)['episode']

            self.assertValidEpisodeObject(episode_json_obj)
            self.assertEquals(episode_json_obj['number'], 1,
                              "wrong first episode for \'{0}\'".format(show))

        for show in shows:
            response = self.app.get('/show/{0}/last/'.format(show))
            self.assertStatusCode(response, 200)

            episode_json_obj = self.response_to_json(response)['episode']

            season = episode_json_obj['season']
            number = episode_json_obj['number']

            self.assertNotEquals(season + number, 2)
            self.assertValidEpisodeObject(episode_json_obj)

if __name__ == '__main__':
    unittest.main()
