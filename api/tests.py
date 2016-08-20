import json
import unittest

from api import models, utils, views


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
        self.assertEqual(
            self.response_to_json(response)['title'],
            "How I Met Your Mother"
        )

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
            self.response_to_json(response)['episode']
        )

    def test_last_view_invalid_show(self):
        response = self.app.get('/show/invalidshowtestrandomtext/last/')
        self.assertStatusCode(response, 404)

    def test_next_released_from_given_episode(self):
        response = self.app.get('/show/howimetyourmother/next/')
        self.assertStatusCode(response, 404)

    def test_next_view(self):
        response = self.app.get('/show/lastweektonightwithjohnoliver/next/')
        self.assertStatusCode(response, 200)
        self.assertValidEpisodeObject(
            self.response_to_json(response)['episode']
        )

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

    def test_parse_data_method(self):
        dates = [
            '2005-09-19',
            '2007-09-24',
            '2004-09-22',
            '2011-06-23',
            '2011-09-20',
            '2010-10-31',
            '2007-12-05',
            '2015-6-5'
        ]

        for date in dates:
            self.assertNotEqual(utils.parse_date(date), None)

        self.assertEqual(utils.parse_date("invalid date"), None)

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

            self.assertEqual(first_date, episode_json['release_date'])

    def test_discover_shows_url(self):
        response = self.app.get('/show/')
        self.assertStatusCode(response, 200)

    def test_overview(self):
        response = self.app.get('/')
        self.assertStatusCode(response, 200)

    def test_fetch_examples(self):
        response = self.app.get('/api/examples/')
        self.assertStatusCode(response, 200)

    def test_old_tvshows_dates(self):
        shows = ['ilovelucy', 'pattydukeshow', 'mred']
        for show in shows:
            self.assertStatusCode(
                self.app.get('/show/{0}/'.format(show)),
                200
            )
            self.assertStatusCode(
                self.app.get('/show/{0}/last/'.format(show)),
                200
            )

    def test_all_episodes_included_in_show_data(self):
        show_keys = [
            "greysanatomy", "bigbangtheory", "howimetyourmother",
            "lastweektonightwithjohnoliver", "vampirediaries",
            "chuck", "originals", "gameofthrones", "modernfamily"
        ]

        for show_key in show_keys:
            show = models.get_show_by_key(show_key)
            current_season = 1
            for season_key in show.seasons_keys():
                self.assertEqual(current_season, int(season_key))
                current_episode = 1
                for episode in show.season_episodes(season_key):
                    if episode.number == 0:
                        continue
                    self.assertEqual(current_episode, int(episode.number))
                    current_episode += 1
                current_season += 1

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
            self.assertEqual(
                episode_json_obj['number'],
                1,
                "wrong first episode for \'{0}\'".format(show)
            )

        for show in shows:
            response = self.app.get('/show/{0}/last/'.format(show))
            self.assertStatusCode(response, 200)
            episode_json_obj = self.response_to_json(response)['episode']
            self.assertNotEqual(
                episode_json_obj['season'] + episode_json_obj['number'],
                2
            )
            self.assertValidEpisodeObject(episode_json_obj)

    def test_parse_epguides_tvrage_csv_data(self):
        self.assertEqual(utils.parse_epguides_tvrage_csv_data(66), [])
        self.assertNotEqual(utils.parse_epguides_tvrage_csv_data(2445), [])

    def test_parse_epguides_maze_csv_data(self):
        self.assertEqual(utils.parse_epguides_maze_csv_data(53450), [])
        self.assertNotEqual(utils.parse_epguides_maze_csv_data(66), [])

    def test_parse_csv_file(self):
        url = 'http://epguides.com/common/exportToCSVmaze.asp?maze=66'
        row_map = {'season': 1, 'number': 2, 'release_date': 4, 'title': 5}
        returned_rows = 0

        for row in utils.parse_csv_file(url, row_map):
            returned_rows += 1

        self.assertGreater(returned_rows, 10)


if __name__ == '__main__':
    unittest.main()
