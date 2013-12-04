import unittest
import json
import views


class TestViews(unittest.TestCase):

    def setUp(self):
        self.app = views.app.test_client()

    def tearDown(self):
        pass

    def assertStatusCode(self, response, expected):
        self.assertEquals(response._status_code, expected)

    def assertCorrectEpisodeObject(self, data):
        self.assertTrue('number' in data)
        self.assertTrue('season' in data)
        self.assertTrue('release_date' in data)
        self.assertTrue('title' in data)

    def test_show_view(self):
        response = self.app.get('/show/howimetyourmother')
        self.assertStatusCode(response, 200)

        data = json.loads(response.data)
        for season in data:
            for episode in data[season]:
                self.assertCorrectEpisodeObject(episode)

    def test_released_view(self):
        response = self.app.get('/show/howimetyourmother/1/1/released')
        self.assertStatusCode(response, 200)
        self.assertEqual(json.loads(response.data)['status'], True)

    def test_last_view(self):
        response = self.app.get('/show/howimetyourmother/last')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(json.loads(response.data)['episode'])

    def test_next_view(self):
        # test a show that is running, this might need to be updated some day
        response = self.app.get('/show/howimetyourmother/next')
        self.assertStatusCode(response, 200)
        self.assertCorrectEpisodeObject(json.loads(response.data)['episode'])

        response = self.app.get('/show/chuck/next/')
        self.assertStatusCode(response, 404)


if __name__ == '__main__':
    unittest.main()
