import sys

sys.path.append("./lib/python2.7/site-packages/")

import fitbit
import jinja2
import logging
import os
import urllib
import webapp2

from google.appengine.api import app_identity as app
from google.appengine.api import users
from google.appengine.ext import ndb
from webapp2_extras import sessions

import citibike
import citifit
import conf

class UserSettings(ndb.Model):
    """
    Settings for a given user including citibike and fitibit credentials.
    """
    userid = ndb.StringProperty(required=True)
    fitbit_key = ndb.StringProperty()
    fitbit_secret = ndb.StringProperty()
    citibike_username = ndb.StringProperty()
    citibike_password = ndb.StringProperty()
    last_trip_id = ndb.IntegerProperty(default=0)

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

class Main(Handler):
    """
    Main handler responsible for the main landing page.
    """
    def is_logged_in_fitbit(self):
        return self.settings.fitbit_key != None and \
          self.settings.fitbit_secret != None

    def is_logged_in_citibike(self):
        return self.settings.citibike_username != None and \
          self.settings.citibike_password != None

    def get(self):
        if not self.is_logged_in_citibike():
            self.redirect('/citibike')
            return

        if not self.is_logged_in_fitbit():
            self.redirect('/fitbit')
            return

        print self.settings.fitbit_key
        print self.settings.fitbit_secret

        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render({
            'last_trip_id': self.settings.last_trip_id
        }))

class Update(webapp2.RequestHandler):
    def get(self):
        q = UserSettings.query()
        users = q.fetch()
        for user in users:
            try:
                cf = citifit.Citifit(user.citibike_username,
                                     user.citibike_password,
                                     user.fitbit_key,
                                     user.fitbit_secret)
                user.last_trip_id = cf.update(last_trip_id)
                user.put()
            except:
                e = sys.exc_info()[0]
                logging.exception('Update exception: %s' % e)

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
    ('/update', Update),
], debug=True, config=config)
