"""Timetable fixtures derive their structure from the inspected Agenda; values are fictional."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from automation.agents.portal_timetable import (PortalError, validate_dates, read_timetable, parse_snapshot,
                                                timetable_result, fingerprint, period_dates)


def row(day='14', time='11:00-11:55', course='Example Systems', **values):
    return {'date_label':f'Monday, {day} September 2026, 11:00 am–11:55, {time}',
            'time':time,'course':course,'room':'Example Room','teachers':['Example Instructor'],
            'cohorts':['Example Cohort'],'extra_cohorts':'2+',
            'meeting_link':None,'raw_text':'Example displayed row', **values}


def snapshot(rows=None, period='13/09/2026 - 19/09/2026'):
    rows = [row()] if rows is None else rows
    return {'heading':'Academic Timetable','period':period,'agenda':True,'row_count':len(rows),'rows':rows}


@pytest.mark.parametrize('values', [{'start_date':'2026-02-30'}, {'start_date':'20260914'},
    {'start_date':'2026-09-14','end_date':'2026-09-13'}, {'start_date':'2026-09-14','end_date':'2026-09-21'}])
def test_invalid_dates_rejected_before_execution(values):
    with pytest.raises(PortalError): validate_dates(**values)


def test_observed_long_date_header_and_numeric_header_are_equivalent():
    assert period_dates('Sunday, 13 September 2026 - Saturday, 19 September 2026') == period_dates('13/09/2026 - 19/09/2026')


def test_daily_brief_includes_only_requested_date_and_real_fields():
    result = timetable_result([snapshot([row(),row('15',course='Tomorrow Class')])],'2026-09-14')
    assert len(result['records']) == 1
    assert result['records'][0]['course'] == 'Example Systems'
    assert result['records'][0]['additional_cohorts_display'] == '2+'
    assert '11:00–11:55' in result['text'] and 'Example Room' in result['text']
    assert 'Tomorrow Class' not in result['text']
    assert result['term'] is None and result['account_id'] is None


def test_empty_day_inside_verified_week_is_different_from_empty_unloaded_week():
    result = timetable_result([snapshot()], '2026-09-13')
    assert result['records'] == [] and 'No classes are displayed' in result['text']
    with pytest.raises(PortalError, match='no verifiable rows'):
        timetable_result([snapshot([])], '2026-09-13')


def test_overlapping_entries_are_retained():
    result = timetable_result([snapshot([row(), row(time='11:30-12:25',course='Other Systems')])], '2026-09-14')
    assert len(result['records']) == 2
    assert result['overlaps'] == [{'first_record':0,'second_record':1}]
    assert 'Overlapping' in result['text']


@pytest.mark.parametrize('change', [{'course':''}, {'time':'25:00-26:00'}, {'time':'23:00-00:00'},
    {'date_label':'not a date'}, {'date_label':'Monday, 21 September 2026, 11:00'},
    {'meeting_link':'javascript:alert(1)'}])
def test_unreadable_or_out_of_period_row_fails_entire_snapshot(change):
    with pytest.raises(PortalError): parse_snapshot(snapshot([row(**change)]))


def test_missing_and_duplicate_periods_are_not_complete():
    with pytest.raises(PortalError, match='every requested date'):
        timetable_result([snapshot()], '2026-09-19','2026-09-20')
    with pytest.raises(PortalError, match='twice'):
        timetable_result([snapshot(),snapshot()], '2026-09-14')


def test_two_periods_cover_a_week_crossing_sunday():
    result = timetable_result([snapshot(),snapshot([row('21')],'20/09/2026 - 26/09/2026')], '2026-09-18','2026-09-24')
    assert [r['date'] for r in result['records']] == ['2026-09-21']


def test_comparison_ignores_row_order_and_cosmetic_text_but_detects_room_change():
    records = timetable_result([snapshot([row(),row(time='13:00-13:55')])], '2026-09-14')['records']
    changed = copy.deepcopy(list(reversed(records)))
    changed[0]['source_row'] = 100
    changed[0]['raw_text'] = 'different spacing'
    assert fingerprint(records) == fingerprint(changed)
    changed[0]['room'] = 'New room'
    assert fingerprint(records) != fingerprint(changed)


def test_row_limit_is_not_silent_truncation():
    value = snapshot()
    value['row_count'] = 201
    with pytest.raises(PortalError, match='incomplete'): parse_snapshot(value)


class Page:
    """Small UI fixture: real reader must navigate periods and inspect fresh rows."""
    def __init__(self, weeks, mobile=False):
        self.weeks, self.index, self.mobile = weeks, 0, mobile
        self.moves = []
        self.url = 'https://myupes-beta.upes.ac.in/connectportal/user/student/curriculum-scheduling'
    def evaluate(self, js, path): self.url = 'https://myupes-beta.upes.ac.in' + path
    def wait_for_timeout(self, ms): pass
    def locator(self, selector):
        if selector=='main': return NS(evaluate=lambda script:copy.deepcopy(self.weeks[self.index]))
        if selector=='button.k-nav-current': return NS(inner_text=lambda:self.weeks[self.index]['period'])
        if selector=='select[aria-label="Select View"]':
            return NS(count=lambda:1,is_visible=lambda:self.mobile,select_option=lambda value:self.moves.append(value))
        raise AssertionError(selector)
    def get_by_role(self, role, name, exact):
        if role=='heading': return NS(wait_for=lambda **k:None)
        def click():
            self.moves.append(name)
            if name=='Next': self.index+=1
            elif name=='Previous': self.index-=1
        return NS(click=click)


@pytest.mark.parametrize('mobile', [False, True])
def test_reader_navigates_across_periods(mobile):
    page = Page([snapshot(),snapshot([row('21')],'20/09/2026 - 26/09/2026')], mobile=mobile)
    result = read_timetable(page, '2026-09-18','2026-09-24')
    assert page.moves == [('agenda' if mobile else 'Agenda'),'Next']
    assert [r['date'] for r in result['records']] == ['2026-09-21']


def test_read_timetable_rejects_bad_range_before_touching_page():
    with pytest.raises(PortalError): read_timetable(None, '2026-09-14', '2026-09-21')


@pytest.mark.parametrize('filename,expected_rows', [('myupes-agenda-redacted.json',16),('myupes-agenda-next-week-redacted.json',15)])
def test_redacted_live_capture_parses_every_observed_row(filename, expected_rows):
    captured=json.loads((Path(__file__).parent/'fixtures'/filename).read_text(encoding='utf-8'))
    first,last,records=parse_snapshot(captured)
    assert len(records)==expected_rows
    assert all(first.isoformat() <= record['date'] <= last.isoformat() for record in records)
    assert all(record['course'].startswith('Fixture ') for record in records)
    assert all(not record['meeting_link'] or record['meeting_link'].startswith('https://example.org/') for record in records)


def test_live_capture_week_boundary_and_overlap_are_preserved():
    captures=[json.loads((Path(__file__).parent/'fixtures'/name).read_text(encoding='utf-8'))
              for name in ('myupes-agenda-redacted.json','myupes-agenda-next-week-redacted.json')]
    monday=timetable_result(captures[:1],'2026-09-14')
    assert len(monday['records'])==1
    assert monday['records'][0]['start_time']=='11:00'
    assert monday['records'][0]['end_time']=='11:55'
    week=timetable_result(captures[:1],'2026-09-13','2026-09-19')
    assert len(week['overlaps'])==1
    crossing=timetable_result(captures,'2026-09-18','2026-09-24')
    assert len(crossing['records'])==16
    assert set(record['date'] for record in crossing['records'])=={'2026-09-18','2026-09-19','2026-09-21','2026-09-22','2026-09-23','2026-09-24'}
