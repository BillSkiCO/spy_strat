#!/bin/python

# Code for reversal strat based on the following sheet
# https://docs.google.com/spreadsheets/d/1W4urh_UTyEB5Ml4bpCbVwWwiHO6rCV8MMD-Tp67PV0U/edit#gid=45461717

# imports
import datetime
from lxml import html
from twython import Twython
from time import sleep
import api
import requests
from typing import List

# Public Globals
INVESTING_URL = 'https://robinhood.com/stocks/SPY'
OPEN_PRICE_XPATH = '/html/body/div[1]/main/div[2]/div/div/div/div/main/div[2]/div[1]/div/section[3]/div[2]/div[7]/div[3]'
SPY_CURRENT = '/html/body/div[1]/main/div[2]/div/div/div/div/main/div[2]/div[2]/div/div[1]/div/div/div[1]/div[2]/span[2]'
FIRST_MIN = '09:31:00'
PRICE_THRESHOLD = .0075
VIX_THRESHOLD = 30.0
SLEEP_SEC = 60


class NotifyException(Exception):
    def __init__(self, notif_object):
        self.notif_object = notif_object
        self.twitter = Twython(app_key=api.TW_CUSTOMER_API,
                               app_secret=api.TW_PRIV_API,
                               oauth_token=api.TW_OAUTH_TOKEN,
                               oauth_token_secret=api.TW_OAUTH_TOKEN_SECRET,
                               client_args=api.CLIENT_ARGS)

        # Calculate opening trend
        if self.notif_object.open_price > self.notif_object.target_price:
            self.trend = 'Bear'
        else:
            self.trend = 'Bull'

        self.notify()

    def notify(self):

        # Send Yo
        requests.post("http://api.justyo.co/yo/",
                      data={'api_token': api.YO_API,
                            'username': api.BILL_UN,
                            'link': INVESTING_URL,
                            'text': self.notif_object.message},
                      proxies=api.PROXIES)

        now = datetime.datetime.now(tz=EST5EDT())
        now = now.strftime("%c")

        self.twitter.update_status(status=self.notif_object.message)


class NotifyObject:
    def __init__(self, message=None, open_price=None, target_price=None):
        self.message = message
        self.open_price = open_price
        self.target_price = target_price


# Custom EST or EDT timezone class
class EST5EDT(datetime.tzinfo):

    def utcoffset(self, dt):
        return datetime.timedelta(hours=-5) + self.dst(dt)

    def dst(self, dt):

        #2nd Sunday in March
        d = datetime.datetime(dt.year, 3, 8)
        self.dston = d + datetime.timedelta(days=6-d.weekday())

        # 1st Sunday in Nov
        d = datetime.datetime(dt.year, 11, 1)
        self.dstoff = d + datetime.timedelta(days=6-d.weekday())

        if self.dston <= dt.replace(tzinfo=None) < self.dstoff:
            return datetime.timedelta(hours=1)
        else:
            return datetime.timedelta(0)

    def tzname(self, dt):
        return 'EST5EDT'


def trading_open():
    hour = datetime.datetime.now(tz=EST5EDT()).hour

    # Only get times if before noon for strat
    # Program stops at noon everyday and restarts with cron job at 9:33
    if hour < 12:
        return True

    if hour >= 12:
        return False


def get_vix() -> float:
    resp = requests.get(api.VIX_API_URL, proxies=api.PROXIES)
    d = resp.json()
    d = d['Time Series (1min)']
    vix_avg = (float(d[list(d.keys())[0]]['2. high']) + float(d[list(d.keys())[0]]['3. low'])) / 2.0
    return vix_avg


def main() -> None:

    bear_open = False
    nobj = NotifyObject()
    rev_list = []
    open_price = None
    first_min_close = None

    twitter = Twython(app_key=api.TW_CUSTOMER_API,
                      app_secret=api.TW_PRIV_API,
                      oauth_token=api.TW_OAUTH_TOKEN,
                      oauth_token_secret=api.TW_OAUTH_TOKEN_SECRET,
                      client_args=api.CLIENT_ARGS)

    current_date = datetime.datetime.now(tz=EST5EDT()).date().isoformat()

    # Get open price, trend, threshold value
    try:
        page = requests.get(INVESTING_URL, proxies=api.PROXIES)
        tree = html.fromstring(page.content)

        # Pull open price from Robinhood's SPY page via XPATH
        open_div = tree.xpath(OPEN_PRICE_XPATH)

        # Get closing price of 09:30 from the open price of 09:31
        resp = requests.get(api.SPY_API_URL, proxies=api.PROXIES)
        d = resp.json()
        d = d['Time Series (1min)']

        # API Response starts with most recent times first
        # Invert API response into a LIFO tuple list. Start of trading day first
        # Tuple list rev_list = [(time, open price), (time, open price)..]
        for key in d:
            tmp_tuple = (key, d[key]['1. open'])
            rev_list.insert(0, tmp_tuple)

        # rev_list = [('2015-10-21 16:29:00', '1.21'),....]
        for i in rev_list:
            if current_date in i[0]:
                if FIRST_MIN in i[0]:
                    first_min_close = float(i[1])

        # Error Check
        if first_min_close is None:
            requests.post("http://api.justyo.co/yo/",
                          data={'api_token': api.YO_API,
                                'username': api.BILL_UN,
                                'link': INVESTING_URL,
                                'text': 'Error: Could not get open pricing'},
                          proxies=api.PROXIES)
            exit(1)

        open_price: float = float(open_div[0].text[1:])

        trend= first_min_close - open_price
        threshold_delta = open_price * PRICE_THRESHOLD
        nobj.open_price = open_price

        if trend <= 0.0:
            bear_open = True
            threshold_target = open_price - threshold_delta
            threshold_target = round(threshold_target, 2)
            nobj.target_price = threshold_target
            twitter.update_status(status='[' + str(current_date) + ']'
                                  + ' Bear Open Detected'
                                  + ' Open Price: $' + str(open_price)
                                  + ' Target Price: $' + str(threshold_target))

        else:
            bear_open = False
            threshold_target = open_price + threshold_delta
            threshold_target = round(threshold_target, 2)
            nobj.target_price = threshold_target
            twitter.update_status(status='[' + str(current_date) + ']'
                                         + ' Bull Open Detected'
                                         + ' Open Price: $' + str(open_price)
                                         + ' Target Price: $' + str(threshold_target))

    except Exception:
        requests.post("http://api.justyo.co/yo/",
                      data={'api_token': api.YO_API,
                            'username': api.BILL_UN,
                            'link': INVESTING_URL,
                            'text': 'Error: Could not get pricing'},
                      proxies=api.PROXIES)
        open_price = 0.0
        threshold_target = None
        exit(1)

    while trading_open():

        # Pull JSON response from API
        resp = requests.get(api.SPY_API_URL, proxies=api.PROXIES)
        d = resp.json()
        d = d['Time Series (1min)']

        # Invert API response into a FIFO tuple list. Start of trading day first
        # Tuple list rev_list = [(time, high, low), (time, high, low)..]
        for key in d:
                tmp_tuple = (key, d[key]['2. high'], d[key]['3. low'])
                rev_list.insert(0, tmp_tuple)

        for i in rev_list:

            # if current date is part of the key
            if current_date in i[0]:
                high = float(i[1])
                low = float(i[2])
                try:
                    if bear_open:
                        if low <= threshold_target:
                            tmp_vix = get_vix()
                            if tmp_vix >= VIX_THRESHOLD:
                                nobj.message = "Threshold Hit VIX OK Trade ON"
                                raise NotifyException(nobj)
                            else:
                                nobj.message = "Threshold Hit VIX LOW "\
                                               + str(tmp_vix)
                                raise NotifyException(nobj)
                        if high >= open_price:
                            nobj.message = "Open Crossed. Do not Trade"
                            raise NotifyException(nobj)
                    if not bear_open:
                        if high >= threshold_target:
                            tmp_vix = get_vix()
                            if tmp_vix >= VIX_THRESHOLD:
                                nobj.message = "Threshold Hit VIX OK Trade ON"
                                raise NotifyException(nobj)
                            else:
                                nobj.message = "Threshold Hit VIX LOW "\
                                               + str(tmp_vix)
                                raise NotifyException(nobj)
                        if high <= open_price:
                            nobj.message = "Open Crossed. Do not Trade"
                            raise NotifyException(nobj)
                except Exception:
                    print(nobj.message)
                    exit(1)

        # Sleep for a minute
        print("No trigger for: "
              + str(datetime.datetime.now(tz=EST5EDT()).strftime("%H:%M:00"))
              + " sleeping for 1 min")
        sleep(SLEEP_SEC)

    try:
        if not trading_open():
            nobj.message = "Trading closed. Did not cross"
            raise NotifyException(nobj)
    except Exception:
        print(nobj.message)


if __name__ == "__main__":
    main()
