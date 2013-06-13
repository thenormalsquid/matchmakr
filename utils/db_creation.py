import redis

r = redis.Redis(host='localhost', port=6379, db=0)

def create_categories():
    pipe = r.pipeline()
    #loops through categories and sets them as hashes in redis
    #the key is represented by a single int
    #the key is stored in the db as a set: "categories" 
    categories = ["movies", "sports", "books", "music", "television", "political", "games",
    "religion", "education", "interests", "favorite_athletes", "favorite_teams"]
    for cat in categories:
        c = cat.split("_")
        name = " ".join(c)
        pipe.hset(cat, "name", name).sadd("categories", cat)
    pipe.execute()


if __name__ == "__main__":
    create_categories()

