"""Attendance fixtures; values are fictional, not live qualification."""
import pytest
from automation.agents.portal_attendance import PortalError, parse_snapshot, validate_inputs, read_attendance

REQUEST = {'program': 'Fixture Program', 'term': 'Semester 7', 'course': 'Fixture Course',
           'start_date': '2026-09-01', 'end_date': '2026-09-14'}


def snapshot():
    return {'control_count': 5, 'values': ['Fixture Program', 'Semester 7', 'Fixture Course', '01-09-2026', '14-09-2026'],
            'detail_count': 1, 'table_count': 1, 'busy': False,
            'overall': ['Total Attendance Summary : 66.67%'],
            'cells': ['Total Present', '5', 'Attendances Condoned', '0', 'Number of Sessions Held', '5', 'Datewise Percentage', '100%'],
            'result_courses': [' Fixture Course ']}


def test_overall_percentage_is_never_substituted_for_dated_percentage():
    result = parse_snapshot(snapshot(), REQUEST)
    assert result['datewise_percentage'] == 100 and result['overall_course_percentage'] == 66.67
    assert result['present'] == result['sessions_held'] == 5 and result['condoned'] == 0
    assert 'selected date range' in result['text'] and result['account_id'] is None


@pytest.mark.parametrize('change', [
    {'detail_count': 0}, {'table_count': 0}, {'table_count': 2}, {'busy': True},
    {'control_count': 4}, {'values': ['wrong']}, {'overall': []},
    {'overall': ['Total Attendance Summary : 101%']}, {'result_courses': ['Other Course']},
    {'cells': ['Total Present', '5']},
])
def test_form_loading_ambiguous_results_and_changed_scope_fail_closed(change):
    with pytest.raises(PortalError):
        parse_snapshot({**snapshot(), **change}, REQUEST)


@pytest.mark.parametrize('index,value', [(1, '-1'), (1, 'six'), (1, '6'), (3, '6'), (5, 'unknown'), (7, 'NaN%'), (7, '75%')])
def test_unreadable_and_contradictory_counts_fail(index, value):
    captured = snapshot()
    captured['cells'][index] = value
    with pytest.raises(PortalError):
        parse_snapshot(captured, REQUEST)


def test_condoned_count_does_not_invent_portal_weighting():
    captured = snapshot()
    captured['cells'][1] = '4'
    captured['cells'][3] = '1'
    result = parse_snapshot(captured, REQUEST)
    assert result['present'] == 4 and result['condoned'] == 1 and result['datewise_percentage'] == 100
    assert '1 condoned' in result['text']


def test_zero_session_result_does_not_infer_a_rate():
    captured = snapshot()
    captured['cells'][1] = captured['cells'][5] = '0'
    captured['cells'][7] = '0%'
    assert 'no attendance rate is inferred' in parse_snapshot(captured, REQUEST)['text']


@pytest.mark.parametrize('change', [{'start_date': '2026-02-30'}, {'end_date': '2026-08-31'}, {'end_date': '2028-01-01'},
                                    {'start_date': '20260901'}, {'term': ' '}, {'course': None}, {'program': 'x' * 201},
                                    {'start_date': None}])
def test_request_scope_validation(change):
    with pytest.raises(PortalError):
        validate_inputs(**{**REQUEST, **change})


def test_valid_range_limits_are_inclusive():
    validate_inputs(**{**REQUEST, 'end_date': '2026-09-01'})
    validate_inputs(**{**REQUEST, 'start_date': '2026-01-01', 'end_date': '2027-01-02'})  # 367 dates


def test_read_attendance_rejects_bad_request_before_touching_page():
    with pytest.raises(PortalError):
        read_attendance(None, 'Fixture Program')
