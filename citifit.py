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
    Class linking Citibike and Fitbit account making it possible to update the
    latter with activities from the former.
    """
    MIN_TRIP_DURATION = 60

    def __init__(self, citibike_username, citibike_password, fitbit_key,
                 fitbit_secret):
        """
        Initializes the different services required to perform update operation.
        Connects to Citibike and Fitbit.
        """
        self.citibike = citibike.Citibike(citibike_username, citibike_password)
        self.fitbit = fitbit.Fitbit(conf.FITBIT_CLIENT_KEY,
                                    conf.FITBIT_CLIENT_SECRET,
                                    resource_owner_key=fitbit_key,
                                    resource_owner_secret=fitbit_secret)
        self.maps = maps.Maps(conf.GOOGLE_API_KEY)

    def update(self, last_trip_id=0):
        """
        Updates Fitbit with all Citibike trip after last_trip_id. Returns the id
        of the last Citibike trip added to Fitbit.
        """
        activity_id = self._get_biking_activity_id()
        stations = self._get_stations()
        for trip in self._get_trips(last_trip_id):
            try:
                self._add_trip(activity_id, trip, stations)
            except:
                logging.exception('Failed to add trip: %s' % sys.exc_info()[0])
                return last_trip_id
            last_trip_id = trip.id
            time.sleep(1)
        return last_trip_id

    def _get_biking_activity_id(self):
        activities = self.fitbit.activities_list()
        for category in activities['categories']:
            if category['name'] == 'Sports and Workouts':
                for subcategory in category['subCategories']:
                    if subcategory['name'] == 'Bicycling':
                        for activity in subcategory['activities']:
                            if activity['name'] == 'Bike':
                                return int(activity['id'])
        raise Exception("Can't extract biking activiy.")

    def _get_stations(self):
        return {s.id: s for s in self.citibike.stations()}

    def _get_trips(self, min_id):
        trips = []
        for trip in self.citibike.trips():
            if trip.id > min_id and self._is_valid_trip(trip):
                trips.append(trip)
        trips.sort(cmp=lambda t1,t2: cmp(t1.id, t2.id))
        return trips

    def _add_trip(self, activity_id, trip, stations):
        if not trip.start_station in stations:
            logging.warning("Invalid start station id: %d", trip.start_station)
            return
        if not trip.end_station in stations:
            logging.warning("Invalid end station id: %d", trip.start_station)
            return

        orig = stations[trip.start_station]
        dest = stations[trip.end_station]
        directions = self.maps.directions((orig.lat, orig.lng),
                                          (dest.lat, dest.lng),
                                          maps.TravelMode.bicycling,
                                          maps.UnitSystem.metric)
        distance = directions['routes'][0]['legs'][0]['distance']['value']
        duration = trip.duration

        resp = self.fitbit.log_activity({
            'activityId' : activity_id,
            'startTime' : trip.start_time.strftime('%H:%M'),
            'durationMillis' : duration * 1000,
            'date' : trip.start_time.strftime('%Y-%m-%d'),
            'distance' : distance,
            'distanceUnit' : 'Meter',
            })

    def _is_valid_trip(self, trip):
        if trip.end_station == None:
            return False
        if trip.start_station == trip.end_station:
            return False
        if trip.duration < self.MIN_TRIP_DURATION:
            return False
        return True
