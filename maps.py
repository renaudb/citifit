import sys

sys.path.append("./lib/python2.7/site-packages/")

import json
import urllib

from enum import Enum
try:
    from google.appengine.api import urlfetch
    found_urlfetch = True
except ImportError:
    found_urlfetch = False

from excepts import BadResponse

class TravelMode(Enum):
    """
    Mode of transport to use when calculating directions.
    """
    driving = 0
    walking = 1
    bicycling = 2
    transit = 3

class UnitSystem(Enum):
    """
    Unit system to use when calculating directions.
    """
    metric = 0
    imperial = 1

class Maps:
    """
    Wrapper around the Google Maps Directions API. Details about the API can be
    found at https://developers.google.com/maps/documentation/directions/.
    """
    ENDPOINT = 'https://maps.googleapis.com/maps/api/directions/json?'

    def __init__(self, api_key):
        """
        Initializes wrapper with Google API key required to make requests.
        """
        self.api_key = api_key

    def directions(self, origin, destination, mode=None, units=None):
        """
        Gets directions from origin to destination. Uses mode if provided and
        returns response in units if provided.
        """
        if (isinstance(origin, tuple)):
            origin = "%f,%f" % origin
        if (isinstance(destination, tuple)):
            destination = "%f,%f" % destination

        data = {}
        data['key'] = self.api_key
        data['origin'] = origin
        data['destination'] = destination

        if mode != None:
            data['mode'] = mode.name

        if units != None:
            data['units'] = units.name

        return self._fetch(data)

    def _fetch(self, data):
        url = self.ENDPOINT + urllib.urlencode(data)
        if found_urlfetch:
            resp = json.loads(urlfetch.fetch(url).content)
        else:
            resp = json.load(urllib.urlopen(url))

        status = resp['status']
        if status != 'OK':
            msg = resp['error_message'] if 'error_message' in resp else ''
            raise BadResponse(status, msg)

        return resp
