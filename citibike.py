import Cookie
import cookielib
import json
import logging
import time
import urllib
import urllib2

from datetime import datetime
from lxml import etree
from pytz import timezone

from excepts import BadResponse
from excepts import LogoutException

class Citibike:
    """
    Wrapper around the Citibike API. Includes methods to access user and system
    wide data. This API is not official and is unsupported by Citibike.
    """
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password
        self.token = None
        self.fetcher = UrllibFetcher()

        if self.username != None and self.password != None:
            self._login(self.username, self.password)

    def trips(self, min_id=-1):
        """
        Fetches all the trips for the logged in user.
        """
        if self.username == None or self.password == None:
            raise LogoutException()

        trips = []
        last = 0
        page = 0
        while page <= last:
            uri = 'https://www.citibikenyc.com/member/trips/%d' % page
            for retry in range(5):
                f = self._fetch(uri)
                if f.geturl() == uri:
                    break
                self._login(self.username, self.password)

            html = etree.parse(f, etree.HTMLParser())
            if last == 0:
                elem = html.xpath("//a[@data-ci-pagination-page]")[-1]
                last = int(elem.attrib['data-ci-pagination-page'])
            for t in html.xpath("//tr[@class='trip']"):
                trip = Trip._from_element(t)
                if trip.id <= min_id:
                    return trips
                trips.append(trip)

            page += 1

        return trips

    def stations(self):
        """
        Fetches all the stations and their status as of the time of the request.
        """
        stations = []

        f = self._fetch('http://www.citibikenyc.com/stations/json')
        data = json.load(f)

        if 'stationBeanList' not in data or len(data['stationBeanList']) == 0:
            raise BadResponse('Station Fetch Failed', data)

        for station in data['stationBeanList']:
            stations.append(Station._from_json(station))

        return stations

    def _fetch(self, uri, data={}):
        return self.fetcher.fetch(uri, data)

    def _login(self, username, password):
        for retry in range(5):
            f = self._fetch('https://www.citibikenyc.com/login')
            self.token = self.fetcher.token()
            f = self._fetch('https://www.citibikenyc.com/login', {
                'ci_csrf_token' : self.token,
                'subscriberUsername' : username,
                'subscriberPassword' : password,
                'login_submit' : 'Login'
            })
            if f.geturl() == 'https://www.citibikenyc.com/member/profile':
                return
            time.sleep(2**retry)
        raise BadResponse('Login Failed', 'Could not log into citibike.')

class Trip:
    """
    User trip from one station to another.
    """
    def __init__(self, id, start_station, start_time, end_station, end_time,
                 duration):
        self.id = id
        self.start_station = start_station
        self.start_time = start_time
        self.end_station = end_station
        self.end_time = end_time
        self.duration = duration

    @staticmethod
    def _from_element(e):
        id = int(e.attrib['id'].split('-')[-1])
        start_station = int(e.attrib['data-start-station-id'])
        start_timestamp = int(e.attrib['data-start-timestamp'])
        start_time = datetime.fromtimestamp(start_timestamp,
                                            timezone('US/Eastern'))

        if e.attrib['data-end-station-id'] == 'Station Id - null : null':
            return Trip(id, start_station, start_time, None, None, None)

        end_station = int(e.attrib['data-end-station-id'])
        duration = int(e.attrib['data-duration-seconds'])

        end_timestamp = 0
        if len(e.attrib['data-end-timestamp']) > 0:
            end_timestamp = int(e.attrib['data-end-timestamp'])
        else:
            end_timestamp = start_timestamp + duration
        end_time = datetime.fromtimestamp(end_timestamp,
                                          timezone('US/Eastern'))

        return Trip(id, start_station, start_time, end_station, end_time,
                    duration)

class Station:
    """
    Citibike station and its status.
    """
    def __init__(self, id, name, lat, lng, total_docks, available_bikes,
                 available_docks):
        self.id = id
        self.name = name
        self.lat = lat
        self.lng = lng
        self.total_docks = total_docks
        self.available_bikes = available_bikes
        self.available_docks = available_docks

    @staticmethod
    def _from_json(j):
        id = int(j['id'])
        name = j['stationName']
        lat = float(j['latitude'])
        lng = float(j['longitude'])
        total_docks = j['totalDocks']
        available_bikes = j['availableBikes']
        available_docks = j['availableDocks']

        return Station(id, name, lat, lng, total_docks, available_bikes,
                       available_docks)

class Fetcher:
    def fetch(self, uri, data={}):
        raise NotImplementedError("Subclass need implement fetch.")

    def token(self):
        raise NotImplementedError("Subclass need implement token.")

class UrllibFetcher(Fetcher):
    def __init__(self):
        self.cookies = cookielib.LWPCookieJar()
        handlers = [
            urllib2.HTTPCookieProcessor(self.cookies),
        ]
        self.opener = urllib2.build_opener(*handlers)

    def fetch(self, uri, data={}):
        logging.debug('Fetching %s', uri)
        if (len(data) > 0):
            data = urllib.urlencode(data)
            req = urllib2.Request(uri, data)
        else:
            req = urllib2.Request(uri)
        return self.opener.open(req)

    def token(self):
        token = None
        for c in self.cookies:
            if c.name == 'ci_csrf_token':
                token = c.value
        logging.debug('Found token %s', token)
        return token
