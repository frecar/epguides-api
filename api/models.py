from datetime import datetime, timedelta

from .app import cache
from .exceptions import EpisodeNotFoundException
from .utils import (add_epguides_key_to_redis, parse_epguides_data,
                    parse_epguides_info)


class Episode(object):

    def __init__(self, show, season_number, episode_data):
        self.show = show
        self.season = int(season_number)
        self.number = int(episode_data['number'])
        self.title = episode_data['title']
        self.release_date = episode_data['release_date']

    def __serialize__(self):
        return self.__dict__

    def valid(self):
        if not self.show:
            return False

        if not self.season > 0:
            return False

        if not self.number > 0:
            return False

        if self.title == '':
            return False

        if not self.release_date:
            return False

        return True

    def released(self):

        if not self.valid():
            return False

        release_date = datetime.strptime(
            self.release_date, "%Y-%m-%d")

        if datetime.now() - timedelta(hours=32) > release_date:
            return True

        return False

    def next(self):
        episodes = self.show.get_show_data()

        for ep in episodes[self.season]:
            if ep.number == self.number + 1:
                return ep

        if self.season + 1 in episodes:
            for ep in episodes[self.season + 1]:
                if ep.number == 1:
                    return ep

        return None


@cache.memoize(timeout=60 * 60 * 24)
def get_show_by_name(epguides_name):
    epguides_name = str(epguides_name).lower().replace(" ", "")
    if epguides_name.startswith("the"):
        epguides_name = epguides_name[3:]

    show = Show(epguides_name)
    add_epguides_key_to_redis(epguides_name)
    return show


class Show(object):

    def __init__(self, epguide_name):
        self.epguide_name = epguide_name
        self.title = self.get_title()
        self.imdb_id = self.get_imdb_id()

    def get_title(self):
        try:
            return parse_epguides_info(self.epguide_name)[1]

        except (IndexError, TypeError):
            raise EpisodeNotFoundException()

    def get_imdb_id(self):
        try:
            imdb_id_raw = parse_epguides_info(self.epguide_name)[0]
            imdb_id_prefix = imdb_id_raw[:2]
            imdb_id_number = int(imdb_id_raw[2:])
            return imdb_id_prefix + "%07d" % imdb_id_number

        except (IndexError, TypeError):
            raise EpisodeNotFoundException()

    def first_episode(self):
        data = self.get_show_data()
        first_season_number = sorted(data.keys(), key=int)[0]

        for episode in data[first_season_number]:
            if episode.released():
                return episode

        raise EpisodeNotFoundException()

    def next_episode(self):
        data = self.get_show_data()

        for season in sorted(data.keys(), key=int):
            for episode in data[season]:
                if episode.valid() and not episode.released():
                    return episode

        raise EpisodeNotFoundException()

    def last_episode(self):
        show_data = self.get_show_data()
        season_keys = show_data.keys()

        season_number = 0
        second_season_number = 0

        if len(season_keys) > 0:
            season_number = sorted(show_data.keys(), key=int)[-1]

        if len(season_keys) > 1:
            second_season_number = sorted(show_data.keys(), key=int)[-2]

        last_episode_released = None

        # Check if the latest season has episodes and if the first is released
        if len(show_data[season_number]) > 0 and show_data[season_number][0].released():
            for episode in show_data[season_number]:
                if episode.released():
                    last_episode_released = episode

        # If not, check if the previous season has released episodes
        else:
            if second_season_number > 0:
                for episode in show_data[second_season_number]:
                    if episode.released():
                        last_episode_released = episode

        if last_episode_released:
            return last_episode_released

        raise EpisodeNotFoundException()

    def get_episode(self, season_number, episode_number):
        show_data = self.get_show_data()

        if season_number in show_data:
            for episode in show_data[season_number]:
                if episode.number == episode_number:
                    return episode

        raise EpisodeNotFoundException()

    def episode_released(self, season_number, episode_number):
        return self.get_episode(season_number, episode_number).released()

    def get_show_data(self):
        episodes = {}

        def parse_date(date):
            strptime = datetime.strptime

            try:
                return strptime(date, "%d %b %y").strftime("%Y-%m-%d")
            except:
                try:
                    return strptime(date, "%d/%b/%y").strftime("%Y-%m-%d")
                except:
                    return None

            return None

        for episode_data in parse_epguides_data(self.epguide_name):

            try:
                season_number = int(episode_data[1])

                if season_number not in episodes:
                    episodes[season_number] = []

                parsed_date = parse_date(episode_data[3])

                if not parsed_date:
                    continue

                episode = Episode(self, season_number, {
                    'number': episode_data[2],
                    'title': episode_data[4],
                    'release_date': parsed_date
                })

                episodes[season_number].append(episode)

            except ValueError:
                pass

        return episodes
