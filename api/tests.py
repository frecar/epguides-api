import unittest
import json
import views


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
        self.assertEquals(response._status_code, expected)

    def assertCorrectEpisodeObject(self, data):
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
                self.assertCorrectEpisodeObject(episode)

    def test_metadata_info(self):
        response = self.app.get('/show/howimetyourmother/info/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['title'],
                         "How I Met Your Mother")

    def test_released_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/released/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['status'], True)

    def test_given_episode_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(self.response_to_json(response)['episode'])

    def test_next_from_current_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/next/')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(self.response_to_json(response)['episode'])

    def test_next_from_current_view_does_not_exist(self):
        response = self.app.get('/show/howimetyourmother/15/1/next/')
        self.assertStatusCode(response, 404)

    def test_released_next_from_current_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/next/released/')
        self.assertStatusCode(response, 200)
        self.assertEqual(self.response_to_json(response)['status'], True)

    def test_last_view(self):
        response = self.app.get('/show/howimetyourmother/last/')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(self.response_to_json(response)['episode'])

        response = self.app.get('/show/gameofthrones/last/')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(self.response_to_json(response)['episode'])

    def test_next_released_from_given_episode(self):
        response = self.app.get('/show/howimetyourmother/next/')
        self.assertStatusCode(response, 404)

    def test_next_view(self):
        # test a show that is running, this might need to be updated some day
        response = self.app.get('/show/haltandcatchfire/next/')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(self.response_to_json(response)['episode'])

        response = self.app.get('/show/chuck/next//')
        self.assertStatusCode(response, 404)

    def test_discover_shows_url(self):
        response = self.app.get('/show/')
        self.assertStatusCode(response, 200)

    def test_redirect_to_docs(self):
        response = self.app.get('/')
        self.assertStatusCode(response, 302)

if __name__ == '__main__':
    unittest.main()
