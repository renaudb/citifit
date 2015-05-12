import sys

sys.path.append("./lib/python2.7/site-packages/")

import fitbit
import httplib2
import logging
import time

from apiclient.discovery import build
from datetime import datetime
from pytz import timezone

import citibike
import conf
import maps

from excepts import BadResponse

class Citifit:
    """
    Class linking Citibike and fitness logging services making it possible to
    update the latters with activities from the former.
    """
    MIN_TRIP_DURATION = 60

    def __init__(self, citibike_username, citibike_password):
        """
        Initializes the different services required to perform update operation.
        Connects to Citibike.
        """
        self.citibike = citibike.Citibike(citibike_username, citibike_password)
        self.maps = maps.Maps(conf.GOOGLE_API_KEY)
        self.services = []
        self.stations = self._get_stations()

    def add_google_fit(self, google_fit_credentials):
        """
        Adds Google Fit service.
        """
        self.services.append(GoogleFitService(google_fit_credentials,
                                              self.stations))

    def add_fitbit(self, fitbit_key, fitbit_secret):
        """
        Adds Fitbit service.
        """
        self.services.append(FitbitService(fitbit_key, fitbit_secret))

    def update(self, last_trip_id=0):
        """
        Updates linked services with all Citibike trip after last_trip_id.
        Returns the id of the last Citibike trip successfully added.
        """
        if len(self.services) == 0:
            logging.debug('No services to update')
            return last_trip_id

        for trip in self._get_trips(last_trip_id):
            try:
                logging.debug('Adding trip: %d' % trip.id)
                self._add_trip(trip)
            except:
                logging.exception('Failed to add trip: %s' % sys.exc_info()[0])
                logging.debug('Last trip id: %d' % last_trip_id)
                return last_trip_id
            last_trip_id = trip.id
            time.sleep(1)
        logging.debug('Last trip id: %d' % last_trip_id)
        return last_trip_id

    def _get_stations(self):
        return {s.id: s for s in self.citibike.stations()}

    def _get_trips(self, min_id):
        trips = []
        for trip in self.citibike.trips(min_id):
            if trip.id > min_id and self._is_valid_trip(trip):
                trips.append(trip)
        trips.sort(cmp=lambda t1,t2: cmp(t1.id, t2.id))
        return trips

    def _add_trip(self, trip):
        if not trip.start_station in self.stations:
            logging.warning("Invalid start station id: %d", trip.start_station)
            return
        if not trip.end_station in self.stations:
            logging.warning("Invalid end station id: %d", trip.start_station)
            return

        # Get distance between stations from Google Maps.
        orig = self.stations[trip.start_station]
        dest = self.stations[trip.end_station]
        directions = self.maps.directions((orig.lat, orig.lng),
                                          (dest.lat, dest.lng),
                                          maps.TravelMode.bicycling,
                                          maps.UnitSystem.metric)
        distance = directions['routes'][0]['legs'][0]['distance']['value']

        # Add trip to all services.
        for service in self.services:
            service.add_trip(trip, distance)

    def _is_valid_trip(self, trip):
        if trip.end_station == None:
            return False
        if trip.start_station == trip.end_station:
            return False
        if trip.duration < self.MIN_TRIP_DURATION:
            return False
        return True

class FitnessService:
    """
    FitnessService provides an interface to add Citibike trips to a service.
    """
    def add_trip(self, trip, distance):
        raise NotImplementedError("Subclass need implement add_trip.")

class GoogleFitService(FitnessService):
    """
    GoogleFitService is used to add Citibike trips to Google Fit.
    """
    ACTIVITY_BIKING_VALUE = 1  # Biking
    ACTIVITY_DATA_TYPE_NAME = 'com.google.activity.segment'
    APPLICATION_NAME = 'Citifit'
    APPLICATION_VERSION = '1.0'
    USER_ID = 'me'

    def __init__(self, credentials, stations):
        logging.debug("Credentials: %s" % credentials)
        http = credentials.authorize(httplib2.Http())
        self.service = build('fitness', 'v1', http=http)
        self.stations = stations
        self.activity_data_source = self._get_activity_data_source()
        if self.activity_data_source == None:
            self.activity_data_source = self._create_activity_data_source()

    def add_trip(self, trip, distance):
        self._add_activity(trip)
        self._add_session(trip)

    def _add_session(self, trip):
        def trip_time(trip):
            return trip.start_time.ctime()

        def trip_name(trip):
            return "Citbike Trip on %s" % trip_time(trip)

        def trip_description(trip):
            start_station_name = self.stations[trip.start_station].name
            end_station_name = self.stations[trip.end_station].name
            return "Citibike ride on %s from %s to %s." % (trip_time(trip),
                                                           start_station_name,
                                                           end_station_name)

        def timestamp_utc_millis(dt):
            epoch = datetime(1970, 1, 1, tzinfo=timezone('UTC'))
            return int((dt - epoch).total_seconds() * 1000)

        session_id = str(trip.id)
        body = {
            'id': session_id,
            'name': trip_name(trip),
            'description': trip_description(trip),
            'startTimeMillis': str(timestamp_utc_millis(trip.start_time)),
            'endTimeMillis': str(timestamp_utc_millis(trip.end_time)),
            'modifiedTimeMillis': str(int(time.time() * 1000)),
            'activityType': str(GoogleFitService.ACTIVITY_BIKING_VALUE),
            'application': {
                'version': GoogleFitService.APPLICATION_VERSION,
                'name': GoogleFitService.APPLICATION_NAME,
            },
        }
        logging.debug("Sending Google Fit session update request: %s" % body)
        request = self.service.users().sessions().update(
            userId=GoogleFitService.USER_ID, sessionId=session_id, body=body)
        response = request.execute()
        logging.debug("Received Google Fit session update response: %s"
                      % response)

    def _add_activity(self, trip):
        ACTIVITY_FIELD_NAME = 'activity'

        def timestamp_utc_nanos(dt):
            epoch = datetime(1970, 1, 1, tzinfo=timezone('UTC'))
            return int((dt - epoch).total_seconds() * 1000 * 1000 * 1000)

        activity_data_source_id = self.activity_data_source['dataStreamId']
        start_time = timestamp_utc_nanos(trip.start_time)
        end_time = timestamp_utc_nanos(trip.end_time)
        body = {
            'dataSourceId': self.activity_data_source['dataStreamId'],
            'maxEndTimeNs': str(end_time),
            'minStartTimeNs': str(start_time),
            'point': [{
                'dataTypeName': GoogleFitService.ACTIVITY_DATA_TYPE_NAME,
                'endTimeNanos': str(end_time),
                'originDataSourceId': '',
                'startTimeNanos': str(start_time),
                'value': [{
                    'intVal': str(GoogleFitService.ACTIVITY_BIKING_VALUE)
                }],
            }]
        }
        logging.debug("Sending Google Fit dataset patch request: %s" % body)
        request = self.service.users().dataSources().datasets().patch(
            userId=GoogleFitService.USER_ID,
            dataSourceId=activity_data_source_id,
            datasetId="%s-%s" % (start_time, end_time),
            body=body)
        response = request.execute()
        logging.debug("Received Google Fit dataset patch response: %s"
                      % response)

    def _get_activity_data_source(self):
        logging.debug("Sending Google Fit datasource list request")
        request = self.service.users().dataSources().list(
            userId=GoogleFitService.USER_ID,
            dataTypeName=GoogleFitService.ACTIVITY_DATA_TYPE_NAME)
        response = request.execute()
        logging.debug("Received Google Fit datasource list response: %s"
                      % response)

        for data_source in response['dataSource']:
            app = data_source['application']
            if 'name' in app:
                app_name = app['name']
                if app_name == GoogleFitService.APPLICATION_NAME:
                    return data_source
        return None

    def _create_activity_data_source(self):
        ACTIVITY_FIELD_NAME = 'activity'
        ACTIVITY_FIELD_FORMAT = 'integer'
        TYPE = 'derived'

        body = {
            'dataType': {
                'field': [
                    {
                        'name': ACTIVITY_FIELD_NAME,
                        'format': ACTIVITY_FIELD_FORMAT,
                    },
                ],
                'name': GoogleFitService.ACTIVITY_DATA_TYPE_NAME
            },
            'application': {
                'version': GoogleFitService.APPLICATION_VERSION,
                'name': GoogleFitService.APPLICATION_NAME,
            },
            'type': TYPE,
        }
        logging.debug("Sending Google Fit data source create request: %s"
                      % body)
        request = self.service.users().dataSources().create(
            userId=GoogleFitService.USER_ID, body=body)
        response = request.execute()
        logging.debug("Received Google Fit data source create response: %s"
                      % response)
        return response

class FitbitService(FitnessService):
    """
    FitbitService is used to add Citibike trips to Fibit.
    """
    def __init__(self, fitbit_key, fitbit_secret):
        self.fitbit = fitbit.Fitbit(conf.FITBIT_CLIENT_KEY,
                                    conf.FITBIT_CLIENT_SECRET,
                                    resource_owner_key=fitbit_key,
                                    resource_owner_secret=fitbit_secret)
        self.activity_id = self._get_biking_activity_id()

    def add_trip(self, trip, distance):
        self.fitbit.log_activity({
            'activityId' : self.activity_id,
            'startTime' : trip.start_time.strftime('%H:%M'),
            'durationMillis' : trip.duration * 1000,
            'date' : trip.start_time.strftime('%Y-%m-%d'),
            'distance' : distance,
            'distanceUnit' : 'Meter',
            })

    def _get_biking_activity_id(self):
        activities = self.fitbit.activities_list()
        for category in activities['categories']:
            if category['name'] == 'Sports and Workouts':
                for subcategory in category['subCategories']:
                    if subcategory['name'] == 'Bicycling':
                        for activity in subcategory['activities']:
                            if activity['name'] == 'Bike':
                                return int(activity['id'])
        raise Exception("Can't extract biking activity id.")
