
class ShowNotFoundException(Exception):
    """
    Exception thrown when the api is not able to
    find or parse show data from epguides.com
    """
    pass

class EpisodeNotFoundException(Exception):
    """
    Exception thrown when the api is not able to
    find or parse episode data from epguides.com
    """
    pass


class SeasonNotFoundException(Exception):
    """
    Exception thrown when the api is not able to
    find or parse episode data from epguides.com
    """
    pass
