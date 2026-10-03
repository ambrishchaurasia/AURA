"""MyUPES Agenda (timetable) reader. DOM reads only: no cookies, storage, framework state or network payloads.
Takes the signed-in work tab from portal_session.open_portal."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

from automation.agents import portal_session

PORTAL_URL = 'https://myupes-beta.upes.ac.in/connectportal/user/student/curriculum-scheduling'
MAX_ROWS = 200
MAX_WEEK_MOVES = 26
MONTHS = {name: index for index, name in enumerate(('January', 'February', 'March', 'April', 'May',
          'June', 'July', 'August', 'September', 'October', 'November', 'December'), 1)}


class PortalError(Exception):
    pass


def validate_dates(start_date, end_date=None):
    """Return (first, last) dates; same limits as the source: ISO strings, ordered, at most seven days."""
    for value in (start_date, end_date):
        if value is not None and not (isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise PortalError('Dates must be YYYY-MM-DD strings.')
    try:
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date or start_date)
    except ValueError:
        raise PortalError('Dates must be real calendar dates in YYYY-MM-DD form.') from None
    if not 0 <= (last - first).days <= 6:
        raise PortalError('Choose an ordered date range of at most seven days.')
    return first, last


# DOM reads only: do not access framework state, endpoints, storage or cookies.
# These classes and aria labels were observed in the live Agenda view.
SNAPSHOT_JS = r'''(root) => {
  const text = n => n ? n.innerText.trim() : '';
  const content = root.querySelector('.k-scheduler-agendaview .k-scheduler-content');
  const rows = content ? Array.from(content.querySelectorAll('table.k-scheduler-table > tbody > tr')) : [];
  return {
    heading: text(root.querySelector('h3')),
    period: text(root.querySelector('button.k-nav-current')),
    agenda: !!content,
    row_count: rows.length,
    rows: rows.slice(0,201).map(row => ({
      date_label: row.querySelector('td[data-task-index]')?.getAttribute('aria-label') || '',
      time: text(row.querySelector('.k-scheduler-timecolumn')),
      course: text(row.querySelector('.day-month-agenda-view > p')),
      room: text(row.querySelector('.event-room-details p > span')),
      teachers: Array.from(row.querySelectorAll('.all-teacher-list-container li')).map(text),
      cohorts: Array.from(row.querySelectorAll('.all-cohort-list-container li')).map(text),
      extra_cohorts: text(row.querySelector('.all-cohort-list-container .k-avatar-text')),
      meeting_link: row.querySelector('a.meeting-link')?.getAttribute('href') || null,
      raw_text: text(row)
    }))
  };
}'''


def period_dates(label):
    match = re.fullmatch(r'\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\s*', label)
    try:
        if match:
            first, last = [datetime.strptime(value, '%d/%m/%Y').date() for value in match.groups()]
        else:
            # The same live Agenda also exposes a long English date label.
            dates = re.findall(r'[A-Za-z]+,\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', label)
            if len(dates) != 2:
                raise ValueError()
            first, last = [date(int(year), MONTHS[month], int(day)) for day, month, year in dates]
    except (KeyError, ValueError):
        raise PortalError('The timetable date range could not be read.') from None
    if (last - first).days != 6:
        raise PortalError('The timetable is not showing the expected seven-day Agenda view.')
    return first, last


def _normal(value):
    return ' '.join(value.split())


def parse_snapshot(snapshot):
    if snapshot.get('heading') != 'Academic Timetable' or snapshot.get('agenda') is not True:
        raise PortalError('The authenticated Academic Timetable Agenda is not available.')
    first, last = period_dates(snapshot.get('period', ''))
    rows = snapshot.get('rows', [])
    if not rows:
        # An empty DOM before the request completes is not evidence of no classes.
        raise PortalError('The Agenda has no verifiable rows. It may still be loading or contain no published timetable; no empty-schedule claim was made.')
    if len(rows) != snapshot.get('row_count') or len(rows) > MAX_ROWS:
        raise PortalError('The timetable is incomplete or exceeds the 200-row limit.')
    records = []
    for index, row in enumerate(rows):
        match = re.match(r'^[A-Za-z]+,\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}),', row.get('date_label', ''))
        times = re.fullmatch(r'\s*([0-2]\d:[0-5]\d)\s*[-–]\s*([0-2]\d:[0-5]\d)\s*', row.get('time', ''))
        if not match or not times or not row.get('course', '').strip():
            raise PortalError('A timetable row has an unreadable date, time or course; no rows were silently skipped.')
        try:
            day = date(int(match[3]), MONTHS[match[2]], int(match[1]))
            start, end = [datetime.strptime(value, '%H:%M').time() for value in times.groups()]
        except (KeyError, ValueError):
            raise PortalError('A timetable row contains an invalid date or time.') from None
        if not first <= day <= last or end <= start:
            raise PortalError('A timetable row does not match the selected period or has unsupported overnight timing.')
        link = row.get('meeting_link')
        if link and (urlsplit(link).scheme != 'https' or not urlsplit(link).hostname or urlsplit(link).username):
            raise PortalError('A timetable meeting link is not a valid HTTPS link.')
        records.append({'date': day.isoformat(), 'start_time': start.strftime('%H:%M'), 'end_time': end.strftime('%H:%M'),
                        'course': _normal(row['course']), 'room': _normal(row.get('room', '')) or None,
                        'instructors': [_normal(value) for value in row.get('teachers', [])],
                        'cohorts': [_normal(value) for value in row.get('cohorts', [])],
                        'additional_cohorts_display': row.get('extra_cohorts') or None,
                        'meeting_link': link, 'source_row': index + 1,
                        'raw_text': row.get('raw_text', ''), 'source_event_id': None,
                        'status': 'as_displayed'})
    return first, last, records


def fingerprint(records):
    # Row order, fetch time and visual formatting are not schedule changes.
    values = [{k: v for k, v in r.items() if k not in ('source_row', 'raw_text')} for r in records]
    canonical = sorted(json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()


def timetable_result(snapshots, start_date, end_date=None):
    first, last = date.fromisoformat(start_date), date.fromisoformat(end_date or start_date)
    covered = set()
    records = []
    periods = set()
    for snapshot in snapshots:
        start, end, rows = parse_snapshot(snapshot)
        if (start, end) in periods:
            raise PortalError('The same Agenda period was captured twice.')
        periods.add((start, end))
        covered.update(start + timedelta(days=i) for i in range(7))
        records.extend(row for row in rows if first.isoformat() <= row['date'] <= last.isoformat())
    if any(first + timedelta(days=i) not in covered for i in range((last - first).days + 1)):
        raise PortalError('The captured Agenda does not cover every requested date.')
    records.sort(key=lambda r: (r['date'], r['start_time'], r['course']))
    overlaps = []
    for index, left in enumerate(records):
        for right_index in range(index + 1, len(records)):
            right = records[right_index]
            if left['date'] == right['date'] and left['start_time'] < right['end_time'] and right['start_time'] < left['end_time']:
                overlaps.append({'first_record': index, 'second_record': right_index})
    lines = [f"Classes: {first.isoformat()}" + (f" to {last.isoformat()}" if last != first else ''),
             'Times: Asia/Kolkata (portal configuration).', f'Source: {PORTAL_URL}']
    if not records:
        lines.append('No classes are displayed for the requested dates within the verified Agenda period.')
    for row in records:
        lines.append(f"{row['date']} {row['start_time']}–{row['end_time']} — {row['course']}")
        if row['room']: lines.append('Room: ' + row['room'])
        if row['instructors']: lines.append('Instructor: ' + '; '.join(row['instructors']))
        if row['meeting_link']: lines.append('Class link: ' + row['meeting_link'])
    if overlaps:
        lines.append(f'Overlapping class pairs: {len(overlaps)}. Both entries are retained; confirm conflicts with the college.')
    return {'schema_version': 1, 'start_date': first.isoformat(), 'end_date': last.isoformat(),
            'timezone': 'Asia/Kolkata', 'timezone_source': 'portal_configuration', 'term': None,
            'account_scope': 'current_authenticated_browser_session', 'account_id': None,
            'source_url': PORTAL_URL, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'records': records, 'overlaps': overlaps, 'complete_for_displayed_periods': True,
            'fingerprint': fingerprint(records), 'text': '\n\n'.join(lines)}


class _Reader:
    def __init__(self, page):
        self.page = page
        self.snapshots = []

    def _snapshot(self):
        return self.page.locator('main').evaluate(SNAPSHOT_JS)

    def _stable_snapshot(self):
        try:  # Rows arrive several seconds after the view switches; an empty week simply times out here.
            self.page.locator('td[data-task-index]').first.wait_for(state='attached', timeout=30000)
        except Exception:
            pass
        previous = None
        problem = 'The timetable kept changing while being read.'
        for _ in range(40):
            current = self._snapshot()
            if current == previous:
                try:
                    parse_snapshot(current)
                    return current
                except PortalError as error:
                    problem = str(error)
            previous = current
            self.page.wait_for_timeout(150)
        raise PortalError(problem + ' Retry when loading finishes.')

    def read(self, first, last, start_date, end_date):
        self.page.get_by_role('heading', name='Academic Timetable', exact=True).wait_for(state='visible', timeout=5000)
        dropdown = self.page.locator('select[aria-label="Select View"]')
        if dropdown.count() == 1 and dropdown.is_visible():
            dropdown.select_option('agenda')
        else:
            self.page.get_by_role('button', name='Agenda', exact=True).click()
        # Bounded navigation using the observed Previous/Next controls; never
        # guess a hidden endpoint or synthesize unobserved dates in the UI.
        moves = 0
        while True:
            label = self.page.locator('button.k-nav-current').inner_text()
            start, end = period_dates(label)
            if first < start:
                direction = 'Previous'
            elif first > end:
                direction = 'Next'
            else:
                self.snapshots.append(self._stable_snapshot())
                if last <= end:
                    return timetable_result(self.snapshots, start_date, end_date)
                first = end + timedelta(days=1)
                direction = 'Next'
            if moves >= MAX_WEEK_MOVES:
                raise PortalError('The requested dates exceed the supported 26-week navigation limit.')
            moves += 1
            self.page.get_by_role('button', name=direction, exact=True).click()
            for _ in range(30):
                self.page.wait_for_timeout(100)
                if self.page.locator('button.k-nav-current').inner_text() != label:
                    break
            else:
                raise PortalError('The timetable date control did not move to another period.')


def read_timetable(page, start_date=None, end_date=None) -> dict:
    start_date = start_date or date.today().isoformat()
    first, last = validate_dates(start_date, end_date)
    portal_session.route(page, '/connectportal/user/student/curriculum-scheduling')
    try:
        return _Reader(page).read(first, last, start_date, end_date)
    except PortalError:
        raise
    except Exception as e:  # Playwright timeouts / missing controls
        raise PortalError(f'The Academic Timetable could not be read: {type(e).__name__}') from None
