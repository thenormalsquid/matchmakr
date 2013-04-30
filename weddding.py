import os.path
import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.log
import tornado.gen
import tornadoredis
from facebook import GraphAPI
import logging

from tornado.escape import to_unicode, json_decode, native_str, json_encode
import random

from tornado.options import define, options, parse_command_line

define("port", default=1935, help="run on the given port", type=int)
define("facebook_api_key", help="API key",
       default="no")
define("facebook_secret", help="Facebook application secret",
       default="no")


#should get object from mainhandler and store to redis, but for test purposes, we'll just use minehandler for that now

class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", IndexHandler),
	        (r"/main", MainHandler),
            (r"/love", PartnerHandler),
            (r"/lovebirds", CalculatedHandler),
            (r"/auth/login", AuthLoginHandler),
            (r"/auth/logout", AuthLogoutHandler),
        ]
        settings = dict(
            cookie_secret="no",
            login_url="/auth/login",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            xsrf_cookies=True,
            facebook_api_key=options.facebook_api_key,
            facebook_secret=options.facebook_secret,
            ui_modules={"Partner":PartnerModule},
            debug=True,
            autoescape=None,
        )
        tornado.web.Application.__init__(self, handlers, **settings)

#remove get_likes and use in mainhandler


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html")


class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        user_json = self.get_secure_cookie("fbdemo_user")
        if not user_json: return None
        return tornado.escape.json_decode(user_json)

    @tornado.gen.coroutine
    def user_exists(self, curr):
        c = tornadoredis.Client()
        c.connect()
        yield tornado.gen.Task(c.hget, "users:%s" % str(curr["id"]), "name")


class TestReq(tornado.auth.FacebookGraphMixin):
    def test(self):
        self.facebook_request("/me", self.get_user,
                                    access_token=access_token)

    def get_user(self,d):
        print "hahaha",d

# class User(object):
#     @tornado.gen.coroutine
#     def make_user(self, d):
#         print "inside make_user"
#         new = {"name":d["name"]}
#         if 'interested_in' and 'gender' in d:
#             new["gender"] = d["gender"]
#             new["interested_in"] = d["interested_in"]
#             self.create_user(d, new)
#             print "exit make_user"
#         elif 'interested_in' in d and 'gender' not in d:
#             new["gender"] = None
#             new["interested_in"] = d["interested_in"]
#             self.create_user(d, new)
#             print "exit make_user"
#         elif 'gender' in d and 'interested_in' not in d:
#             new["gender"] = d["gender"]
#             new["interested_in"] = None
#             self.create_user(d, new)
#             print "exit make_user"
#         else:
#             new["gender"] = None
#             new["interested_in"] = None
#             self.create_user(d, new)
#             print "exit make_user"

#     @tornado.gen.coroutine
#     def create_user(self, d, n):
#         print "inside create_user"
#         c = tornadoredis.Client()
#         c.connect()
#         with c.pipeline() as pipe:
#             pipe.hmset("users:%s" % (d["id"]), n)
#             yield tornado.gen.Task(pipe.execute)
#         print "Posted to redis, exit create_user"



class AuthLoginHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    @tornado.web.asynchronous
    def get(self):
        my_url = (self.request.protocol + "://" + self.request.host +
                  "/auth/login?next=" +
                  tornado.escape.url_escape(self.get_argument("next", "/")))
        if self.get_argument("code", False):
            self.get_authenticated_user(
                redirect_uri=my_url,
                client_id=self.settings["facebook_api_key"],
                client_secret=self.settings["facebook_secret"],
                code=self.get_argument("code"),
                callback=self._on_auth)
            return
        self.authorize_redirect(redirect_uri=my_url,
                                client_id=self.settings["facebook_api_key"],
                                extra_params={"scope": "read_stream, user_about_me,user_interests,friends_activities,friends_birthday,friends_education_history,friends_interests,friends_likes,friends_relationships,friends_relationship_details,friends_religion_politics,friends_subscriptions,friends_events,friends_status friends_about_me, offline_access,read_friendlists,user_likes,user_activities,user_relationships,user_relationship_details, friends_photos,user_photos"})

    def _on_auth(self, user):
        if not user:
            raise tornado.web.HTTPError(500, "Facebook auth failed")
        self.set_secure_cookie("fbdemo_user", tornado.escape.json_encode(user))
        self.redirect(self.get_argument("next", "/"))


class AuthLogoutHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    def get(self):
        self.clear_cookie("fbdemo_user")
        self.redirect(self.get_argument("next", "/"))


#all user based magic happens here
#separate scrape logic from calculate and render pages
class MainHandler(BaseHandler,tornado.auth.FacebookGraphMixin):
    """
        Version 1 is completed
        Scrapes your likes and your information to help determine eligibility
    """

    @tornado.web.asynchronous
    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self):
        c = tornadoredis.Client()
        c.connect()
        pipe = c.pipeline()
        t = TestReq()
        t.test()
        access_token = self.current_user["access_token"]
        print "%s connected" % self.current_user["name"]
        pipe.hexists("users:%s" % self.current_user["id"], "attracted_to")
        pipe.exists("users:%s" % self.current_user["id"])
        pipe.exists("user:%s" % self.current_user["id"])
        attracted_to, user, likes = yield tornado.gen.Task(pipe.execute)
        if user == 0:
            self.facebook_request("/me", self.get_user,
                                    access_token=access_token)

        if likes == 0:
            self.facebook_request("/me", self.get_likes, access_token=self.current_user["access_token"], fields="movies.fields(id),music.fields(id),favorite_athletes,favorite_teams,religion,political,sports,books.fields(id),games.fields(id),interests.fields(id),television.fields(id),activities.fields(id)")

        if attracted_to == 1:
            self.display(False)
        else:
            self.display(True)


    def get_friends(self,d):
        print d

    def get_user(self, d):
        print "inside get_user"
        # self.get_likes()
        self.make_user(d)
        # self.get_likes()
        #self.render("index.html", form=False)
        print "exit get_user"

    #render form, or not to render form
    @tornado.web.asynchronous
    def display(self, b):
        self.render("index.html", form=b)

    @tornado.web.asynchronous
    def get_likes(self, d):
        self.parse_likes(d)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        self.interested_in = self.get_argument('optionsRadios')
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            pipe.hset("users:%s" % self.current_user["id"], "attracted_to", self.interested_in)
            yield tornado.gen.Task(pipe.execute)
        print "updated interested in"
        self.render("index.html", form=False)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def make_user(self, d):
        print "inside make_user"
        new = {"name":d["name"]}
        if 'interested_in' not in d:
            new["gender"] = d["gender"]
            self.create_user(d, new)
            print "exit make_user"
        elif 'gender' not in d:
            new["gender"] = None
            self.create_user(d, new)
        else:
            new["gender"] = d["gender"]
            new["interested_in"] = d["interested_in"]
            self.create_user(d, new)
            print "exit make_user"

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def create_user(self, d, n):
        print "inside create_user"
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            pipe.hmset("users:%s" % (d["id"]), n)
            yield tornado.gen.Task(pipe.execute)
        print "Posted %s to redis" % (self.current_user["name"])

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def parse_likes(self, d):
        c = tornadoredis.Client()
        c.connect()
        i = d.itervalues()
        with c.pipeline() as pipe:
            for e in i:
                if 'data' in e:
                    for j in e["data"]:
                        pipe.lpush("user:%s" % d["id"], j["id"])
                elif type(e) == list:
                    for h in e:
                        pipe.lpush("user:%s" % d["id"], h["id"])
            print "posted %s \'s likes to redis" % self.current_user["name"]
            yield tornado.gen.Task(pipe.execute)



class PartnerHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    """
    Handles all logic... from scraping friends to calculating results
    """
    @tornado.web.asynchronous
    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self):
        access_token = self.current_user["access_token"]
        c = tornadoredis.Client()
        c.connect()
        #don't forget to call execute
        pipe = c.pipeline()
        pipe.hexists("users:%s" % self.current_user["id"], "checked")
        #sentinel for scraped friends
        pipe.hexists("users:%s" % self.current_user["id"], "f_check")
        check, f_check = yield tornado.gen.Task(pipe.execute)
        if check == 1:
            print "already calculated friends for %s " % self.current_user["name"]
            self.render("partner.html")
        else:
            self.facebook_request("/me", self.get_friends, 
                   access_token=access_token, fields="friends.fields(id,name,interested_in,relationship_status,gender)")
            self.facebook_request("/me",self.get_sports, access_token = self.current_user["access_token"], fields="friends.fields(favorite_teams,favorite_athletes,sports)")
            self.facebook_request("/me",self.get_books_games, access_token = self.current_user["access_token"], fields="friends.fields(games,books)")
            self.facebook_request("/me",self.get_interests, access_token = self.current_user["access_token"], fields="friends.fields(interests)")
            self.facebook_request("/me",self.get_music, access_token = self.current_user["access_token"], fields="friends.fields(music)")
            self.facebook_request("/me", self.get_tv, access_token = self.current_user["access_token"], fields="friends.fields(television)")
            self.display()


    @tornado.web.asynchronous
    def display(self):
        self.render("mine.html")

    @tornado.web.asynchronous
    def on_finish(self):
        print "done"

    def get_friends(self,data):
        self.create_person(data)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def filter_friends(self,data):
        d = data.itervalues()
        for j in d:
            print j
            for i in j["data"]:
                if "relationship_status" not in i:
                    print i
                    self.create_person(i)
                else:
                    rel = i["relationship_status"]
                    if rel == "Married" or rel == "In a Relationship":
                        continue
                    elif rel == "Single" or rel == "It's Complicated":
                        self.create_person(i)


    def get_sports(self,d):
        self.set_base_data(d, "favorite_teams", "favorite_athletes", "sports")
        print "sports fired"

    def get_books_games(self,d):
        self.set_connect_data(d, "games", "books")
        print "books fired"

    def get_interests(self,d):
        self.set_connect_data(d,  "interests")
        print "interests"

    def get_music(self,d):
        self.set_connect_data(d, "music")
        print "music fired"

    def get_tv(self,d):
        self.set_connect_data(d, "television")
        print "tv fired"

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def create_person(self, data):
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            d = data["friends"]["data"]
            for i in d:
                if "relationship_status" not in i:
                    pipe.hmset("people:%s" % i["id"], i)
                else:
                    rel = i["relationship_status"]
                    if rel == "Married" or rel == "In a Relationship":
                        continue
                    elif rel == "Single" or rel == "It's Complicated":
                        pipe.hmset("people:%s" % i["id"], i)
            pipe.hset("users:%s" % self.current_user["id"], "f_check", "True")
            yield tornado.gen.Task(pipe.execute)
        print "collected friends"

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def set_base_data(self, d, *args):
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            for e in d["friends"]["data"]:
                for key in args:
                    if key in e:
                        user_gender = yield tornado.gen.Task(c.hget,"people:%s" % e["id"], "gender")
                        for s in e[key]:
                            #print "likes:%s:%s:%s" %(s["id"],user_gender,s["name"])
                            pipe.sadd("likes:%s:%s:%s" %(s["id"],user_gender,s["name"]), e["id"])
            yield tornado.gen.Task(pipe.execute)
        print "added likes to redis"

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def set_connect_data(self, d, *args):
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            for f in d["friends"]["data"]:
                for key in args:
                    if key in f:
                        user_gender = yield tornado.gen.Task(c.hget,"people:%s" % f["id"], "gender")
                        for i in f[key]["data"]:
                            #print "likes:%s:%s:%s" %(i["id"],user_gender,i["name"])
                            pipe.sadd("likes:%s:%s:%s" %(i["id"],user_gender,i["name"]), f["id"])
            yield tornado.gen.Task(pipe.execute)
        print "added connect likes to redis"

    #get top 50 people add to rank
    @tornado.gen.coroutine
    def ready_data(self):
        c = tornadoredis.Client()
        c.connect()
        interest = yield tornado.gen.Task(c.hget,"users:%s" % self.current_user["id"], "interested_in")
        u_likes = yield tornado.gen.Task(c.lrange,"user:%s" % self.current_user["id"], 0, -1)
        print u_likes, type(interest)

    def calculate_data(self, likes, *interests):
        pass

    def return_data(self, c):
        self.finish()
        pass


class PartnerModule(tornado.web.UIModule):
    def render(self, partner):
        return self.render_string("modules/partner.html", partner=partner)


class CalculatedHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    def get(self):
        self.render("partner.html")



def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    logging.info("listening on :%s" % options.port)
    tornado.ioloop.IOLoop.instance().start()



if __name__ == "__main__":
    main()
 