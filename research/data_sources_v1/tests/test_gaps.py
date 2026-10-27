import unittest

from research.data_sources_v1.gaps import link_motor, link_tide, parse_hourly, parse_preinspection


class GapContracts(unittest.TestCase):
    def line(self, values=None, station='TK'):
        values=values or [100]*24
        return (''.join('   ' if v is None else f'{v:3}' for v in values)+'2610 1'+station).encode()

    def test_hourly_zero_negative_and_missing_are_distinct(self):
        r=parse_hourly(self.line([0,-12,None]+[100]*21),2026,10,'TK')
        self.assertEqual(r['2026-10-01T00:00:00+09:00'],0)
        self.assertEqual(r['2026-10-01T01:00:00+09:00'],-12)
        self.assertIsNone(r['2026-10-01T02:00:00+09:00'])
        self.assertEqual(len(r),24)

    def test_station_and_month_identity_are_required(self):
        with self.assertRaises(ValueError):parse_hourly(self.line(),2026,9,'TK')
        with self.assertRaises(ValueError):parse_hourly(self.line(),2026,10,'UN')
        with self.assertRaises(ValueError):parse_hourly(self.line()+b'wrong',2026,10,'TK')

    def test_duplicate_hour_is_rejected(self):
        with self.assertRaises(ValueError):parse_hourly(self.line()+b'\n'+self.line(),2026,10,'TK')

    def test_proxy_uses_prior_hour_without_future_interpolation(self):
        race={'venue_code':'03','day':'2026-10-01','closed_at':'2026-10-01 12:55:00'}
        observations={'TK':{'2026-10-01T12:00:00+09:00':{'height_cm':10},
                            '2026-10-01T13:00:00+09:00':{'height_cm':90}}}
        linked,status=link_tide(race,observations)
        self.assertEqual(linked['height_cm'],10)
        self.assertEqual(linked['age_minutes'],55)
        self.assertFalse(linked['prospective_verified'])
        self.assertTrue(linked['release_delayed_until_following_day_or_later'])

    def test_missing_hour_is_not_replaced_by_later_hour(self):
        race={'venue_code':'03','day':'2026-10-01','closed_at':'2026-10-01 12:55:00'}
        linked,status=link_tide(race,{'TK':{'2026-10-01T13:00:00+09:00':{'height_cm':90}}})
        self.assertIsNone(linked)
        self.assertEqual(status,'station_hour_missing_or_not_yet_published')

    def test_freshwater_venue_is_not_a_missing_tidal_station(self):
        linked,status=link_tide({'venue_code':'23'}, {})
        self.assertIsNone(linked)
        self.assertEqual(status,'freshwater_tide_not_applicable')

    def test_engine_number_gets_distinct_cycle_identity(self):
        r={'venue_code':'03','day':'2026-05-11','boats':[{'motor_number':10}]}
        facts=[{'venue_code':'03','cycle_id':'2026','valid_from':'2026-05-11','valid_through':'2026-10-19'}]
        self.assertEqual(link_motor(r,facts)['motor_keys'],['03:2026:10'])
        r['day']='2026-05-10'
        self.assertIsNone(link_motor(r,facts))

    def test_wait_page_is_not_replaced_with_previous_series(self):
        self.assertEqual(parse_preinspection('次節開催までしばらくお待ちください'.encode(),'06'),[])
        with self.assertRaises(ValueError):parse_preinspection(b'<html>system error</html>','03')


if __name__=='__main__':unittest.main()
