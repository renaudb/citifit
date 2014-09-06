class BadResponse(Exception):
    """
    Raised if an API response contains an error.
    """
    def __init__(self, status='', msg=''):
        self.status = status
        self.msg = msg

    def __str__(self):
        return "%s: %s" % (self.status, self.msg)

class LogoutException(Exception):
    """
    Raised if an API request is made to a logged in method while logged out.
    """
    pass
