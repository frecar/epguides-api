from werkzeug.exceptions import HTTPException

class ShowNotFoundException(HTTPException):
    """
    Exception thrown when the api is not able to
    find or parse show data from epguides.com
    """
    code = 404
    description = 'Show not found'

class EpisodeNotFoundException(HTTPException):
    """
    Exception thrown when the api is not able to
    find or parse episode data from epguides.com
    """
    code = 404
    description = 'Episode not found'


class SeasonNotFoundException(HTTPException):
    """
    Exception thrown when the api is not able to
    find or parse episode data from epguides.com
    """
    code = 404
    description = 'Season not found'
