import sys

sys.path.append("./lib/python2.7/site-packages/")

import datetime
import fitbit
import logging
import time

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
