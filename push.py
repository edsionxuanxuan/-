import logging
import signal
from dataclasses import dataclass
from datetime import datetime


from apscheduler.schedulers.blocking import BlockingScheduler
from BarkNotificator import BarkNotificator
from redis import Redis
from requests import sessions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("__name__")

# 线报酷url
IXBK_URL = "http://new.ixbk.net"
IXBK_PLUS = IXBK_URL + "/plus/json/push.json"

# BARK
BARK_DEVICE_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# redis
REDIS_URL="127.0.0.1"
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=""

#数据id
IXBK_ID = "xbk_1"
IXBK_ID_EX = 600  # 10分钟左右重新清空数据库
IXBK_IDS = "xbk_ids"

# scheduler
SCHEDULER_SECONDS = 30


@dataclass
class Content:
    id: int
    title: str
    content: str
    datetime: datetime
    catename: str
    louzhu: str
    url: str


@dataclass
class RedisServer:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __post_init__(self):
        self.client = self._connection()
        logger.info("【redis】连接成功!!!")

    def _connection(self):
        client = Redis(
            host=REDIS_URL,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD
        )
        return client

    def set_ttl(self):
        self.client.setex(IXBK_ID, IXBK_ID_EX, 1)

    def get_ttl(self):
        return self.client.get(IXBK_ID)


# 请求线报酷
def request_xbk():
    with sessions.Session() as session:
        logger.info("【线报酷】获取数据")
        return session.request(method="GET", url=IXBK_PLUS).json()


# 处理数据
def handle_data(data):
    # 返回列表嵌套的对象
    contents = []
    for dic in data:
        con = Content(
            id=dic["id"],
            title=dic["title"],
            content=dic["content"],
            url=IXBK_URL + dic["url"],
            datetime=dic["datetime"],
            catename=dic["catename"],
            louzhu=dic["louzhu"]
        )
        contents.append(con)
    return contents


# 判断id是否已经发送过
def check_id_is_exists(rs, contents, ids):
    new_ids = []
    new_contents = []
    for con in contents:
        if str(con.id) not in ids:
            rs.client.sadd(IXBK_IDS, con.id)
            new_ids.append(con.id)
            new_contents.append(con)
    logger.info("【最新要发送的id】, ", new_ids)
    return new_contents


# 从redis中获取id
def get_or_set_ids(rs, contents):
    if rs.get_ttl():
        res = rs.client.smembers(IXBK_IDS)
        rds_ids = [s.decode() for s in res]
        logger.info("【redis】中已存在id: ", rds_ids)
        # 返回不在redis中的数据
        return check_id_is_exists(rs, contents, rds_ids)
    else:
        logger.info("【redis】初始化集合,准备要发送的id")
        # 清空集合
        rs.client.delete(IXBK_IDS)
        rs.set_ttl()
        # 将当前要请求的所有id存放到redis中
        for con in contents:
            rs.client.sadd(IXBK_IDS, con.id)
        return contents


# 推送到iphone上
def push_bark(contents):
    if contents:
        # with sessions.Session() as session:
        #     for content in contents:
        #         session.request(method="POST", url=BARK_URL, json={
        #             "title": content.title,
        #             "body": content.content
        #             # "url": content.url,
        #         })

        bark = BarkNotificator(device_token=BARK_DEVICE_TOKEN)
        for content in contents:
            bark.send(title=content.title, content=content.content, target_url=content.url)


def signal_handler(Signal, Frame):
    import sys
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def main():
    # redis
    client = RedisServer()
    # 请求线报酷
    json_ = request_xbk()
    # 将json数据传入处理后得到是列表嵌套对象
    contents = handle_data(json_)
    # 获取或设置最新id
    new_contents = get_or_set_ids(client, contents)
    # 推送消息到iphone
    push_bark(new_contents)


if __name__ == '__main__':
    try:
        scheduler = BlockingScheduler()
        scheduler.add_job(main, 'interval', seconds=SCHEDULER_SECONDS)  # 每30秒执行一次
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("捕获到 Ctrl+C 异常，准备退出")
    finally:
        logger.info("【redis】退出并清空redis中的缓存数据")
        rs = RedisServer()
        rs.client.delete("xbk_1")
        rs.client.delete("xbk_ids")


