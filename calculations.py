import redis
import facebook
import ast
from celery import Celery

config = {}
execfile("configs/settings.conf", config)

celery = Celery("calculations", broker="amqp://guest@localhost:5672//")
celery.conf.CELERY_RESULT_BACKEND = "amqp" 
celery.conf.CELERY_IMPORTS = ("calculations", )

r = redis.Redis(host="localhost", port=6379, db=2)
pipe = r.pipeline()
#pass user access token here through arg

@celery.task
def add(x, y):
    print x,y
    return int(x) + int(y)

@celery.task
def calculate(token, uid):
    groupsize = 30
    req_list = []
    graph = facebook.GraphAPI(token)
    friends = get_friends(graph)
    for friend in friends["friends"]["data"]:
        batched_req = {"method": "GET", "relative_url" : "%s?fields=movies,name,gender,sports,books,music,relationship_status,television,political,games,religion,education,interests,favorite_athletes,favorite_teams" % str(friend["id"])}
        req_list.append(batched_req)
    requests =(req_list[i:i+groupsize] for i in xrange(0,len(req_list),groupsize))
    for req in requests:
        response = graph.request("", post_args = {"batch":str(req)})  
    #response = [graph.request("", post_args = {"batch":str(req)}) for req in requests]
        response_munger(response)
    r.setex("calc_det:%s" % uid, 172800, "True")
    r.setex("friend_calculated:%s" % uid, 518400, "True")

#makes batched requests to facebook -> post req? 
def get_friends(graph):
    res = graph.request("me", {"fields": "friends.fields(id,name,interested_in,relationship_status,gender,birthday)"})
    create_person(res)
    return res

def create_person(friends):
    data = friends["friends"]["data"]
    for friend in data:
        pipe.hmset("users:%s" % friend["id"], friend)
    pipe.execute()



def response_munger(response):
    for res in response:
        if "body" in res:
            body = ast.literal_eval(res["body"])
            if "gender" in body:
                data_scraper(body, "movies","sports","books","music","television",
                    "political","games","religion","education","interests","favorite_athletes","favorite_teams")



def data_scraper(body, *args):
    for keyword in args:
        if keyword in body:
            key = body[keyword]
            if isinstance(key, list):
                if "school" in key[0]:
                    pipe.sadd("%s:%s:%s" % (keyword, key[0]["school"]["id"], 
                        body["gender"]), body["id"])
                else:
                    for k in key:
                        pipe.sadd("%s:%s:%s" % (keyword, k["id"], body["gender"]), body["id"])
            elif isinstance(key, dict):
                for d in key["data"]:
                    pipe.sadd("%s:%s:%s" % (keyword, d["id"], body["gender"]), body["id"])
    pipe.execute()


if __name__ == "__main__":
    celery.start()