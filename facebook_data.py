#facebook data module
from tornado import ioloop
from facebook import GraphAPI
from tornado.escape import to_unicode, json_decode, native_str, json_encode
from tornado import gen
import tornadoredis

ioloop = ioloop.IOLoop.instance()

class GetFBLikes(object):
    def __init__(self, access_token):
        self.graph = GraphAPI(access_token)

    def set_movies(self):
        self.graph.get_object("/me", query={"fields":"friends.fields(movies)"},callback=self.get_movies)
        ioloop.start()

    def set_books_games(self):
        self.graph.get_object("/me", query={"fields":"friends.fields(games,books)"},callback=self.get_books_games)
        ioloop.start()

    def set_interests(self):
        self.graph.get_object("/me", query={"fields":"friends.fields(interests)"},callback=self.get_interests)
        ioloop.start()

    def set_music(self):
        self.graph.get_object("/me", query={"fields":"friends.fields(music)"},callback=self.get_music)
        ioloop.start()

    def set_tv(self):
        self.graph.get_object("/me", query={"fields":"friends.fields(television)"},callback=self.get_tv)
        ioloop.start()

    def get_tv(self,d):
        self.get_data(d,"television")
        print "got tv"

    def get_music(self,d):
        self.get_data(d,"music")
        print "got music"

    def get_interests(self,d):
        self.get_data(d,"interests")
        print "got interests"

    def get_books_games(self,d):
        self.get_data(d,"books","games")
        print "got book"

    def get_movies(self,d):
        self.get_data(d,"movies")
        print "got movies"

    def get_data(self,d,*args):
        for i in args:
            self.set_connect_data(d, i)

    @gen.engine
    def set_connect_data(self,d, *args):
        print type(d)
        c = tornadoredis.Client()
        c.connect()
        with c.pipeline() as pipe:
            for f in d["friends"]["data"]:
                for key in args:
                    if key in f:
                        user_gender = yield gen.Task(c.hget,"people:%s" % f["id"], "gender")
                        for i in f[key]["data"]:
                            #print "likes:%s:%s:%s" %(i["id"],user_gender,i["name"])
                            pipe.sadd("likes:%s:%s:%s" %(i["id"],user_gender,i["name"]), f["id"])
            yield gen.Task(pipe.execute)
        print "added connect likes to redis"
        ioloop.stop()


if __name__=="__main__":
    g = GetFBLikes("AAACEdEose0cBAHZANZBSsAK5TrRc3wIa0bWciI7lQrhSkVgXT9OOkKgW0OEmCoMOqSUnDyxOKrkE7UDBigjJvZCG47OYixKc5P8a7TIjgZDZD")
    print g.set_interests()

