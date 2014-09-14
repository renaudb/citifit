import cookielib
import json
import urllib
import urllib2

from datetime import datetime
from lxml import etree
from pytz import timezone

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
        self.cookies = cookielib.LWPCookieJar()
        handlers = [
            urllib2.HTTPHandler(),
            urllib2.HTTPSHandler(),
            urllib2.HTTPCookieProcessor(self.cookies)
        ]
        self.opener = urllib2.build_opener(*handlers)

        if self.username != None and self.password != None:
            self._login(self.username, self.password)

    def trips(self):
        """
        Fetches all the trips for the logged in user.
        """
        if self.username == None or self.password == None:
            raise LogoutException()

        trips = []
        last = 0
        page = 0
        while page <= last:
            f = self._fetch('https://www.citibikenyc.com/member/trips/%d'
                            % page)
            html = etree.parse(f, etree.HTMLParser())

            if last == 0:
                elem = html.xpath("//a[@data-ci-pagination-page]")[-1]
                last = int(elem.attrib['data-ci-pagination-page'])

            for trip in html.xpath("//tr[@class='trip']"):
                trips.append(Trip._from_element(trip))

            page += 1

        return trips

    def stations(self):
        """
        Fetches all the stations and their status as of the time of the request.
        """
        stations = []

        f = self._fetch('http://www.citibikenyc.com/stations/json')
        data = json.load(f)

        for station in data['stationBeanList']:
            stations.append(Station._from_json(station))

        return stations

    def _login(self, username, password):
        f = self._fetch('https://www.citibikenyc.com/login')
        for cookie in self.cookies:
            if cookie.name == 'ci_csrf_token':
                self.token = cookie.value

        f = self._fetch('https://www.citibikenyc.com/login', {
            'ci_csrf_token' : self.token,
            'subscriberUsername' : username,
            'subscriberPassword' : password,
            'login_submit' : 'Login'
        })

    def _fetch(self, uri, data={}):
        req = None
        if (len(data) > 0):
            data = urllib.urlencode(data)
            req = urllib2.Request(uri, data)
        else:
            req = urllib2.Request(uri)
        return self.opener.open(req)

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
