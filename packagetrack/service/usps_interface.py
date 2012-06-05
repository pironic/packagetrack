import urllib
from datetime import datetime, time

import packagetrack
from ..data import TrackingInfo
from ..service import BaseInterface, TrackFailed
from ..xml_dict import xml_to_dict

class USPSInterface(BaseInterface):
    api_url = {
        'secure_test': 'https://secure.shippingapis.com/ShippingAPITest.dll?API=TrackV2&XML=',
        'test':        'http://testing.shippingapis.com/ShippingAPITest.dll?API=TrackV2&XML=',
        'production':  'http://production.shippingapis.com/ShippingAPI.dll?API=TrackV2&XML=',
        'secure':      'https://secure.shippingapis.com/ShippingAPI.dll?API=TrackV2&XML=',
    }

    service_types = {
        'EA': 'express mail',
        'EC': 'express mail international',
        'CP': 'priority mail international',
        'RA': 'registered mail',
        'RF': 'registered foreign',
#        'EJ': 'something?',
    }

    def identify(self, num):
        return {
            13: lambda x: \
                x[0:2].isalpha() and x[2:9].isdigit() and x[11:13].isalpha(),
            20: lambda x: \
                x.isdigit() and x.startswith('0'),
            22: lambda x: \
                x.isdigit() and x.startswith('9') and not x.startswith('96'),
        }.get(len(num), lambda x: False)(num)

    def track(self, tracking_number):
        resp = self._send_request(tracking_number)
        return self._parse_response(resp, tracking_number)


    def _build_request(self, tracking_number):
        config = packagetrack.config

        return '<TrackFieldRequest USERID="%s"><TrackID ID="%s"/></TrackFieldRequest>' % (
                config.get('USPS', 'userid'), tracking_number)

    def _parse_response(self, raw, tracking_number):
        rsp = xml_to_dict(raw)

        # this is a system error
        if 'Error' in rsp:
            error = rsp['Error']['Description']
            raise TrackFailed(error)

        # this is a result with an error, like "no such package"
        if 'Error' in rsp['TrackResponse']['TrackInfo']:
            error = rsp['TrackResponse']['TrackInfo']['Error']['Description']
            raise TrackFailed(error)

        # make sure the events list is a list
        try:
            events = rsp['TrackResponse']['TrackInfo']['TrackDetail']
        except KeyError:
            events = []
        else:
            if type(events) != list:
                events = [events]

        summary = rsp['TrackResponse']['TrackInfo']['TrackSummary']
        last_update = self._getTrackingDate(summary)
        last_location = self._getTrackingLocation(summary)

        # status is the first event's status
        status = summary['Event']

        # USPS doesn't return this, so we work it out from the tracking number
        service_code = tracking_number[0:2]
        service_description = self.service_types.get(service_code, 'USPS')

        trackinfo = TrackingInfo(
                            tracking_number = tracking_number,
                            last_update     = last_update,
                            delivery_date   = last_update,
                            status          = status,
                            location        = last_location,
                            delivery_detail = None,
                            service         = service_description,
                            )

        # add the last event if delivered, USPS doesn't duplicate
        # the final event in the event log, but we want it there
        if status == 'DELIVERED':
            trackinfo.addEvent(
                location = last_location,
                detail = status,
                date = last_update,
            )

        for e in events:
            location = self._getTrackingLocation(e)
            location = self._getTrackingLocation(e)

            trackinfo.addEvent(
                location = self._getTrackingLocation(e),
                date     = self._getTrackingDate(e),
                detail   = e['Event'],
            )

        return trackinfo

    def _send_request(self, tracking_number):
        config = packagetrack.config

        # pick the USPS API server
        if config.has_option('USPS', 'server'):
            server_type = config.get('USPS','server')
        else:
            server_type = 'production'

        url = "%s%s" % (self.api_url[server_type],
                        urllib.quote(self._build_request(tracking_number)))
        webf = urllib.urlopen(url)
        resp = webf.read()
        webf.close()
        return resp

    def url(self, tracking_number):
        return ('http://trkcnfrm1.smi.usps.com/PTSInternetWeb/'
                'InterLabelInquiry.do?origTrackNum=%s' % tracking_number)

    def validate(self, tracking_number):
        "Return True if this is a valid USPS tracking number."

        return True
#        tracking_num = tracking_number[2:11]
#        odd_total = 0
#        even_total = 0
#        for ii, digit in enumerate(tracking_num):
#            if ii % 2:
#                odd_total += int(digit)
#            else:
#                even_total += int(digit)
#        total = odd_total + even_total * 3
#        check = ((total - (total % 10) + 10) - total) % 10
#        return (check == int(tracking_num[-1:]))


    def _getTrackingDate(self, node):
        """Returns a datetime object for the given node's
        <EventTime> and <EventDate> elements"""
        date = datetime.strptime(node['EventDate'], '%B %d, %Y').date()
        if node['EventTime']:
            time_ = datetime.strptime(node['EventTime'], '%I:%M %p').time()
        else:
            time_ = time(0,0,0)
        return datetime.combine(date, time_)


    def _getTrackingLocation(self, node):
        """Returns a location given a node that has
            EventCity, EventState, EventCountry elements"""

        return ','.join((
                node['EventCity'],
                node['EventState'],
                node['EventCountry'] or 'US'
            ))

