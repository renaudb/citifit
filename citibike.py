import Cookie
import cookielib
import json
import logging
import re
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
    LOGIN_FORM_URL = 'https://member.citibikenyc.com/profile/login_check'

    LOGIN_URL = 'https://member.citibikenyc.com/profile/login'

    PROFILE_URL = 'https://member.citibikenyc.com/profile/'

    TRIP_URL = 'https://member.citibikenyc.com/profile/trips/'

    STATION_URL = 'http://www.citibikenyc.com/stations/json'

    NUM_RETRY = 5

    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password
        self.fetcher = UrllibFetcher()

        if self.username != None and self.password != None:
            self._login(self.username, self.password)

    def trips(self, min_id=-1):
        """
        Fetches all the trips for the logged in user.
        """
        if self.username == None or self.password == None:
            raise LogoutException()

        station_ids = {s.name: s.id for s in self.stations()}
        if len(station_ids) == 0:
            raise BadResponse('Trips Request Failed',
                              'Could not fetch stations.')

        member_id = self._member_id()
        last = self._last_trip_page_number(member_id)
        trips = []
        for page in range(last + 1):
            page_trips = self._page_trips(member_id, page, station_ids)
            for trip in page_trips:
                if trip.id <= min_id:
                    logging.debug("Retrieved %d trips" % len(trips))
                    return trips
                trips.append(trip)
        logging.debug("Retrieved %d trips" % len(trips))
        return trips

    def stations(self):
        """
        Fetches all the stations and their status as of the time of the request.
        """
        stations = []
        f = self._fetch(Citibike.STATION_URL)
        data = json.load(f)
        if 'stationBeanList' not in data or len(data['stationBeanList']) == 0:
            raise BadResponse('Station Fetch Failed', data)
        for station in data['stationBeanList']:
            stations.append(Station._from_json(station))
        logging.debug("Retrieved %d stations" % len(stations))
        return stations

    def _fetch(self, uri, data={}):
        return self.fetcher.fetch(uri, data)

    def _login(self, username, password):
        for retry in range(Citibike.NUM_RETRY):
            token = self._token()
            if token is None:
                time.sleep(2**retry)
                continue
            f = self._fetch(Citibike.LOGIN_FORM_URL, {
                '_username' : username,
                '_password' : password,
                '_failure_path' : 'eightd_bike_profile__login',
                'ed_from_login_popup' : 'true',
                '_login_csrf_security_token' : token,
            })
            if f.geturl() != Citibike.PROFILE_URL:
                time.sleep(2**retry)
                continue
            logging.debug("Login successful")
            return
        raise BadResponse('Login Failed', 'Could not log into Citibike.')

    def _token(self):
        CSRF_TOKEN_XPATH = '//input[@name="_login_csrf_security_token"]/@value'
        for retry in range(Citibike.NUM_RETRY):
            f = self._fetch(Citibike.LOGIN_URL)
            if f.geturl() != Citibike.LOGIN_URL:
                time.sleep(2**retry)
                continue
            html = etree.parse(f, etree.HTMLParser())
            value = html.xpath(CSRF_TOKEN_XPATH)
            if len(value) > 0:
                token = value[0]
                logging.debug("Retrieved token: %s" % token)
                return token
        raise BadResponse('Token Request Failed', 'Could not fetch token.')

    def _member_id(self):
        MEMBER_ID_XPATH = '//a[contains(@href, "memberId")]/@href'
        MEMBER_ID_REGEXP = r'memberId=([^&]+)'
        for retry in range(Citibike.NUM_RETRY):
            f = self._fetch(Citibike.PROFILE_URL)
            if f.geturl() == Citibike.LOGIN_URL:
                self._login(self.username, self.password)
                continue
            if f.geturl() != Citibike.PROFILE_URL:
                time.sleep(2**retry)
                continue
            html = etree.parse(f, etree.HTMLParser())
            href = html.xpath(MEMBER_ID_XPATH)
            if len(href) > 0:
                match = re.search(MEMBER_ID_REGEXP, href[0])
                if match:
                    member_id = match.group(1)
                    logging.debug("Retrieved member id: %s" % member_id)
                    return member_id
        raise BadResponse('Member Id Request Failed',
                          'Could not fetch member id.')

    def _last_trip_page_number(self, member_id):
        LAST_TRIP_PAGE_XPATH = '//a[text()="Oldest"]/@href'
        LAST_TRIP_PAGE_REGEXP = r'pageNumber=([\d]+)'
        trip_url = Citibike.TRIP_URL + member_id
        for retry in range(Citibike.NUM_RETRY):
            f = self._fetch(trip_url)
            if f.geturl() == Citibike.LOGIN_URL:
                self._login(self.username, self.password)
                continue
            if f.geturl() != trip_url:
                time.sleep(2**retry)
                continue
            html = etree.parse(f, etree.HTMLParser())
            href = html.xpath(LAST_TRIP_PAGE_XPATH)
            member_id = None
            if len(href) > 0:
                match = re.search(LAST_TRIP_PAGE_REGEXP, href[0])
                if match:
                    page_number = int(match.group(1))
                    logging.debug("Retrieved last trip page number: %d"
                                  % page_number)
                    return page_number
        raise BadResponse('Last Trip Page Number Request Failed',
                          'Could not fetch last trip page for %s.' % member_id)

    def _page_trips(self, member_id, page, station_ids):
        TRIP_XPATH = '//div[contains(@class, "ed-table__item_trip")]'
        trip_url = Citibike.TRIP_URL + member_id + '?pageNumber=' + str(page)
        for retry in range(Citibike.NUM_RETRY):
            f = self._fetch(trip_url)
            if f.geturl() == Citibike.LOGIN_URL:
                self._login(self.username, self.password)
                continue
            if f.geturl() != trip_url:
                time.sleep(2**retry)
                continue
            html = etree.parse(f, etree.HTMLParser())
            elems = html.xpath(TRIP_XPATH)
            if (len(elems) > 0):
                trips = filter(None, [Trip._from_element(e, station_ids)
                                      for e in elems])
                logging.debug("Retrieved %d trips from page: %d"
                              % (len(trips), page))
                return trips
        raise BadResponse('Page Trips Request Failed',
                          'Could not fetch trips for page %d.' % page)

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
    def _from_element(e, station_ids):
        START_STATION_XPATH = ('.//div[contains(@class, ' +
                               '"trip-start-station")]/text()')
        END_STATION_XPATH = ('.//div[contains(@class, ' +
                             '"trip-end-station")]/text()')
        START_TIME_XPATH = './/div[contains(@class, "trip-start-date")]/text()'
        END_TIME_XPATH = './/div[contains(@class, "trip-end-date")]/text()'
        DURATION_XPATH = './/div[contains(@class, "trip-duration")]/text()'

        def parse_date(s):
            TIME_FORMAT = '%m/%d/%Y %I:%M:%S %p'
            dt = datetime.strptime(s, TIME_FORMAT)
            dt = timezone('US/Eastern').localize(dt)
            return dt

        def parse_duration(s):
            DURATION_REGEXP = r'(?:(\d+) h )?(\d+) min (\d+) s'
            match = re.match(DURATION_REGEXP, s)
            hours = int(match.group(1)) if match.group(1) is not None else 0
            mins = int(match.group(2))
            secs = int(match.group(3))
            return hours * 3600 + mins * 60 + secs

        def timestamp_utc(dt):
            epoch = datetime(1970, 1, 1, tzinfo=timezone('UTC'))
            return (dt - epoch).total_seconds()

        duration_text = e.xpath(DURATION_XPATH)[0].strip()
        if (duration_text == '-'):
            return None
        duration = parse_duration(duration_text)

        start_station = station_ids[e.xpath(START_STATION_XPATH)[0].strip()]
        start_time = parse_date(e.xpath(START_TIME_XPATH)[0].strip())

        end_station = station_ids[e.xpath(END_STATION_XPATH)[0].strip()]
        end_time = parse_date(e.xpath(END_TIME_XPATH)[0].strip())

        id = timestamp_utc(start_time)

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
