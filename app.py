import sys

sys.path.append("./lib/python2.7/site-packages/")

import fitbit
import jinja2
import logging
import os
import urllib
import webapp2

from google.appengine.api import app_identity as app
from google.appengine.ext import ndb
from google.appengine.api import taskqueue
from google.appengine.api import users
from oauth2client.appengine import OAuth2Decorator
from oauth2client.appengine import CredentialsNDBProperty
from webapp2_extras import sessions

import citibike
import citifit
import conf

oauth_decorator = OAuth2Decorator(
    client_id=conf.GOOGLE_FIT_CLIENT_KEY,
    client_secret=conf.GOOGLE_FIT_CLIENT_SECRET,
    scope='https://www.googleapis.com/auth/fitness.activity.write')

class UserSettings(ndb.Model):
    """
    Settings for a given user including citibike and fitibit credentials.
    """
    userid = ndb.StringProperty(required=True)
    citibike_username = ndb.StringProperty()
    citibike_password = ndb.StringProperty()
    fitbit_key = ndb.StringProperty()
    fitbit_secret = ndb.StringProperty()
    google_fit_credentials = CredentialsNDBProperty()
    last_trip_id = ndb.IntegerProperty(default=0)

    def is_logged_in_citibike(self):
        return self.citibike_username != None and self.citibike_password != None

    def is_logged_in_fitbit(self):
        return self.fitbit_key != None and self.fitbit_secret != None

    def is_logged_in_google_fit(self):
        return self.google_fit_credentials != None

class UserUpdateLock(ndb.Model):
    """
    Lock used to prevent overlapping updates for a same user.
    """
    userid = ndb.StringProperty(required=True)
    lock = ndb.BooleanProperty(default=False)

class Update(webapp2.RequestHandler):
    """
    Update handler. Called through cron to update all users with their latest
    Citibike trips.
    """
    def get(self):
        """
        Updates all users, enqueuing one task per user in the default task
        queue. Called by the cron job.
        """
        q = UserSettings.query()
        users = q.fetch()
        for user in users:
            self._enqueue(user)

    def post(self):
        """
        Updates user with userid passed as param. Release the update lock for
        that user if successful.
        """
        userid = self.request.get('userid')
        user = UserSettings.query(UserSettings.userid == userid).get()
        if not user:
            logging.debug("Invalid user: %s" % userid)
            return

        logging.debug("Updating user: %s" % userid)
        cf = citifit.Citifit(user.citibike_username,
                             user.citibike_password)
        if user.is_logged_in_fitbit():
            cf.add_fitbit(user.fitbit_key, user.fitbit_secret)
        if user.is_logged_in_google_fit():
            cf.add_google_fit(user.google_fit_credentials)
        user.last_trip_id = cf.update(user.last_trip_id)
        user.put()

        logging.debug("Releasing user update lock for user: %s" % userid)
        lock = UserUpdateLock.query(ancestor=user.key).get()
        lock.lock = False
        lock.put()

    @ndb.transactional
    def _enqueue(self, user):
        """
        Enqueues an update task for the user if the update lock for the user is
        free. Grabs the update lock.
        """
        lock = UserUpdateLock.query(ancestor=user.key).get()
        if not lock:
            lock = UserUpdateLock(userid=user.userid, parent=user.key)
        if lock.lock == False:
            lock.lock = True
            lock.put()
            taskqueue.add(url='/update', params={'userid': user.userid},
                          transactional=True)
            logging.debug("User update task enqueued for user: %s"
                          % user.userid)
        else:
            logging.debug("User update is locked for user: %s" % user.userid)

class Handler(webapp2.RequestHandler):
    """
    Base handler from which other handlers inherit. Includes login logic as well
    as session handling.
    """
    def dispatch(self):
        self.user = users.get_current_user()
        if not self.user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        self.session_store = sessions.get_store(request=self.request)
        try:
            super(Handler, self).dispatch()
        except:
            e = sys.exc_info()[0]
            logging.exception('Unhandled exception: %s' % e)
        finally:
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def settings(self):
        q = UserSettings.query(UserSettings.userid == self.user.user_id())
        settings = q.get()
        if not settings:
            settings = UserSettings(userid=self.user.user_id())
            settings.put()
        return settings

    @webapp2.cached_property
    def session(self):
        return self.session_store.get_session()

class Citibike(Handler):
    """
    Handler responsible for the management of Citibike credentials.
    """
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('citibike.html')
        self.response.write(template.render({}))

    def post(self):
        self.settings.citibike_username = self.request.get('username')
        self.settings.citibike_password = self.request.get('password')
        self.settings.put()

        self.redirect('/')

class Fitbit(Handler):
    """
    Handler responsible for the management of Fibit credentials.
    """
    def get(self):
        fb = fitbit.Fitbit(conf.FITBIT_CLIENT_KEY,
                           conf.FITBIT_CLIENT_SECRET,
                           callback_uri=self.request.url)

        verifier = self.request.get('oauth_verifier')
        if not verifier:
            token = fb.client.fetch_request_token()
            self.session['oauth_token'] = token['oauth_token']
            self.session['oauth_token_secret'] = token['oauth_token_secret']

            self.redirect(fb.client.authorize_token_url().encode('ascii'))
        else:
            token = {}
            token['oauth_token'] = self.session.get('oauth_token')
            token['oauth_token_secret'] = self.session.get('oauth_token_secret')
            fb.client.fetch_access_token(verifier, token)

            self.settings.fitbit_key = fb.client.resource_owner_key
            self.settings.fitbit_secret = fb.client.resource_owner_secret
            self.settings.put()

            self.redirect('/')

class GoogleFit(Handler):
    """
    Handler responsible for the management of Google Fit credentials.
    """
    @oauth_decorator.oauth_required
    def get(self):
        self.settings.google_fit_credentials = oauth_decorator.get_credentials()
        self.settings.put()

        self.redirect('/')

class Main(Handler):
    """
    Main handler responsible for the main landing page.
    """
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render({
            'last_trip_id': self.settings.last_trip_id,
            'has_citibike': self.settings.is_logged_in_citibike(),
            'has_fitbit': self.settings.is_logged_in_fitbit(),
            'has_google_fit': self.settings.is_logged_in_google_fit()
        }))

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

config = {}
config['webapp2_extras.sessions'] = {
    'secret_key': conf.SESSION_SECRET,
}

application = webapp2.WSGIApplication([
    ('/', Main),
    ('/citibike', Citibike),
    ('/fitbit', Fitbit),
    ('/google-fit', GoogleFit),
    ('/update', Update),
    (oauth_decorator.callback_path, oauth_decorator.callback_handler()),
], debug=True, config=config)
