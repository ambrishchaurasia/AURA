"""MyUPES dated attendance reader. DOM reads only: no cookies, storage, framework state or network payloads.
Takes the signed-in work tab from portal_session.open_portal. The overall course percentage and the selected-date
percentage are distinct; no heading, search form or empty response alone establishes an attendance result."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import calendar
import re
from urllib.parse import urlsplit

from automation.agents import portal_session
from automation.agents.portal_timetable import PortalError

PORTAL_PATH = '/connectportal/user/student/student-attendance'
PORTAL_URL = 'https://myupes-beta.upes.ac.in' + PORTAL_PATH
MONTHS = {name: i for i, name in enumerate(calendar.month_name) if name}
LIMITS = {'program': 200, 'term': 120, 'course': 300}


def validate_inputs(program=None, term=None, course=None, start_date=None, end_date=None) -> dict:
    """Same limits as the source: all five required, labels 1..max chars and not blank, ISO dates, ordered, at most 367 dates."""
    values = {'program': program, 'term': term, 'course': course}
    for key, limit in LIMITS.items():
        value = values[key]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise PortalError(f'Attendance needs an exact {key} label (1-{limit} characters); use list_attendance_options to find valid ones.')
    for value in (start_date, end_date):
        if not (isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise PortalError('Dates must be YYYY-MM-DD strings.')
    try:
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        raise PortalError('Dates must be real calendar dates in YYYY-MM-DD form.') from None
    if not 0 <= (last - first).days <= 366:
        raise PortalError('Choose an ordered attendance range of at most 367 dates.')
    return {**values, 'start_date': start_date, 'end_date': end_date}


# DOM reads only. Roles and labels were observed in the live attendance view.
SNAPSHOT_JS = r'''root => {
  const text = e => e ? e.innerText.trim() : '';
  const controls = Array.from(root.querySelectorAll('[role="combobox"]'));
  const values = controls.map(e => e.tagName === 'INPUT' ? e.value : text(e).replace(/\s*Select\s*$/, '').replace(/[-]/g,'').trim());
  const tables = Array.from(root.querySelectorAll('table')).filter(e => text(e).includes('Total Present') && text(e).includes('Datewise Percentage'));
  const details = Array.from(root.querySelectorAll('h3')).filter(e => text(e) === 'Attendance Details');
  const overall = Array.from(root.querySelectorAll('p')).filter(e => /^Total Attendance Summary\s*:/.test(text(e)));
  const pairs = tables.length === 1 ? Array.from(tables[0].rows).flatMap(row => Array.from(row.cells).map(text)) : [];
  return {control_count:controls.length, values, detail_count:details.length, table_count:tables.length,
          overall:overall.map(text), cells:pairs,
          result_courses:Array.from(root.querySelectorAll('[role="treeitem"]')).map(text),
          busy:!!Array.from(root.querySelectorAll('button')).find(e => /Search/.test(text(e)) && e.disabled)};
}'''


def percentage(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}(?:\.\d{1,2})?%', value.strip()):
        raise PortalError('An attendance percentage is missing or unreadable.')
    try:
        number = Decimal(value.strip()[:-1])
    except InvalidOperation:
        raise PortalError('An attendance percentage is invalid.') from None
    if not 0 <= number <= 100:
        raise PortalError('An attendance percentage is outside 0-100.')
    return float(number)


def parse_snapshot(snapshot, requested):
    values = validate_inputs(**requested)
    expected = [values['program'], values['term'], values['course'],
                date.fromisoformat(values['start_date']).strftime('%d-%m-%Y'),
                date.fromisoformat(values['end_date']).strftime('%d-%m-%Y')]
    if snapshot.get('control_count') != 5 or snapshot.get('values') != expected:
        raise PortalError('Attendance filters no longer match the requested program, term, course and dates.')
    if snapshot.get('busy') is not False or snapshot.get('detail_count') != 1 or snapshot.get('table_count') != 1:
        raise PortalError('No complete attendance result is visible. A search form or loading state is not a result.')
    courses = [' '.join(re.sub(r'[-]', '', value).split()) for value in snapshot.get('result_courses', [])]
    if courses != [values['course']]:
        raise PortalError('The displayed attendance result does not identify exactly the requested course.')
    cells = snapshot.get('cells', [])
    labels = ['Total Present', 'Attendances Condoned', 'Number of Sessions Held', 'Datewise Percentage']
    if len(cells) != 8 or cells[::2] != labels:
        raise PortalError('Attendance count labels are missing, duplicated or changed.')
    if any(not re.fullmatch(r'\d{1,6}', value) for value in cells[1:6:2]):
        raise PortalError('Attendance counts are missing or unreadable.')
    present, condoned, held = map(int, cells[1:6:2])
    if present > held or condoned > held:
        raise PortalError('Attendance counts contradict the number of sessions held.')
    dated = percentage(cells[7])
    if condoned == 0 and held and abs(dated - present * 100 / held) > 0.011:
        raise PortalError('Datewise attendance percentage contradicts its present/session counts.')
    overall = snapshot.get('overall', [])
    if len(overall) != 1 or not re.fullmatch(r'Total Attendance Summary\s*:\s*\d{1,3}(?:\.\d{1,2})?%', overall[0]):
        raise PortalError('The overall course attendance percentage could not be verified.')
    total_percentage = percentage(overall[0].split(':', 1)[1].strip())
    return {**values, 'present': present, 'condoned': condoned, 'sessions_held': held,
            'datewise_percentage': dated, 'overall_course_percentage': total_percentage,
            'account_id': None, 'source_url': PORTAL_URL, 'source_kind': 'portal_attendance_details',
            'text': f"{values['course']} - {values['program']}, {values['term']}\n"
                    f"{values['start_date']} to {values['end_date']}: {present} present / {held} sessions held; "
                    f"{condoned} condoned. Portal datewise percentage: {dated:g}%.\n"
                    f"Overall course attendance (portal summary): {total_percentage:g}%. "
                    "The overall figure is separate from the selected date range."
                    + (' No sessions are held in this result; no attendance rate is inferred.' if held == 0 else '')}


class _Reader:
    def __init__(self, page):
        self.page = page

    def _root(self):
        url = urlsplit(self.page.url)
        if url.scheme != 'https' or url.hostname != 'myupes-beta.upes.ac.in' or url.path != PORTAL_PATH:
            raise PortalError('The authenticated attendance page is no longer open.')
        root = self.page.locator('main')
        if root.count() != 1:
            raise PortalError('The attendance page is ambiguous or unavailable.')
        return root

    def _capture(self):
        return self._root().evaluate(SNAPSHOT_JS)

    def _stable_snapshot(self, requested):
        # The result can take up to ~30 s after Search; wait for its heading, then require two identical reads.
        self._root().get_by_role('heading', name='Attendance Details', exact=True).wait_for(state='attached', timeout=30000)
        previous = None
        problem = 'The attendance result kept changing while being read.'
        for _ in range(40):
            current = self._capture()
            if current == previous:
                try:
                    return parse_snapshot(current, requested)
                except PortalError as error:
                    problem = str(error)
            previous = current
            self.page.wait_for_timeout(150)
        raise PortalError(problem + ' Retry when loading finishes.')

    def _controls(self):
        controls = self._root().get_by_role('combobox')
        if controls.count() != 5:
            raise PortalError('The attendance filter controls changed.')
        return controls

    def _select(self, index, value):
        self._controls().nth(index).click()
        option = self.page.get_by_role('option', name=value, exact=True)
        option.wait_for(state='visible', timeout=30000)  # cascading lists load from the server
        if option.count() != 1:
            raise PortalError('The requested attendance filter is unavailable or ambiguous.')
        option.click()

    def options(self):
        """Open each of the three filter comboboxes in turn, read the visible option texts, close with Escape (no selection)."""
        found = {}
        for index, key in enumerate(('program', 'term', 'course')):
            self._controls().nth(index).click()
            options = self.page.get_by_role('option')
            try:
                options.first.wait_for(state='visible', timeout=10000)
            except Exception:
                pass  # e.g. term/course list empty until the earlier filter is chosen
            found[key] = [' '.join(re.sub(r'[-]', '', t).split()) for t in options.all_text_contents()]
            self.page.keyboard.press('Escape')
            self.page.wait_for_timeout(300)
        return found

    def _date(self, index, value):
        requested = date.fromisoformat(value)
        toggles = self._root().get_by_role('button', name='Toggle calendar', exact=True)
        if toggles.count() != 2:
            raise PortalError('Attendance date controls changed.')
        toggles.nth(index).click()
        for _ in range(25):
            header = self.page.get_by_role('button', name=re.compile(r'^(?:' + '|'.join(MONTHS) + r') \d{4}$'))
            if header.count() != 1:
                raise PortalError('The attendance calendar month could not be identified.')
            month, year = header.inner_text().split()
            current = date(int(year), MONTHS[month], 1)
            delta = (requested.year - current.year) * 12 + requested.month - current.month
            if delta == 0:
                break
            if abs(delta) > 24:
                raise PortalError('Choose attendance dates within 24 calendar months of the displayed month.')
            button = self.page.get_by_role('button', name='' if delta > 0 else '', exact=True)
            if button.count() != 1:
                raise PortalError('The attendance calendar navigation is ambiguous.')
            button.click()
        else:
            raise PortalError('The attendance calendar did not reach the requested month.')
        grid = self.page.get_by_role('grid', name=header.inner_text(), exact=True)
        if grid.count() != 1:
            raise PortalError('The attendance date grid is ambiguous.')
        if grid.get_by_role('columnheader').all_text_contents() != ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']:
            raise PortalError('The attendance calendar weekday order changed.')
        cells = grid.get_by_role('gridcell')
        labels = cells.all_text_contents()
        start = current.weekday()
        # Some calendars include the previous week when the month starts Monday.
        if start == 0 and labels and labels[0].strip() != '1':
            start = 7
        days = calendar.monthrange(current.year, current.month)[1]
        if [v.strip() for v in labels[start:start + days]] != [str(i) for i in range(1, days + 1)]:
            raise PortalError('The attendance calendar days could not be verified.')
        cells.nth(start + requested.day - 1).click()

    def read(self, requested):
        for index, key in enumerate(('program', 'term', 'course')):
            self._select(index, requested[key])
        self._date(0, requested['start_date'])
        self._date(1, requested['end_date'])
        # Close an old result before searching, so unchanged old rows cannot be mistaken for a fresh result.
        close = self._root().get_by_role('button', name=re.compile(r'Close$'))
        if close.count() == 1:
            close.click()
        if self._root().get_by_role('heading', name='Attendance Details', exact=True).count():
            raise PortalError('The previous attendance result could not be cleared.')
        search = self._root().get_by_role('button', name=re.compile(r'Search$'))
        if search.count() != 1:
            raise PortalError('The attendance search control is ambiguous.')
        search.click()
        result = self._stable_snapshot(requested)
        return {**result, 'observed_at': datetime.now(timezone.utc).isoformat()}


def _run(page, work):
    portal_session.route(page, PORTAL_PATH)
    try:
        return work(_Reader(page))
    except PortalError:
        raise
    except Exception as e:  # Playwright timeouts / missing controls
        raise PortalError(f'The attendance page could not be read: {type(e).__name__}') from None


def read_attendance(page, program=None, term=None, course=None, start_date=None, end_date=None) -> dict:
    requested = validate_inputs(program, term, course, start_date, end_date)
    return _run(page, lambda reader: reader.read(requested))


def list_attendance_options(page) -> dict:
    """Option texts currently offered by the program, term and course comboboxes (term/course may depend on earlier choices)."""
    options = _run(page, lambda reader: reader.options())
    text = '\n'.join(f"{key}: {'; '.join(values) or '(none offered)'}" for key, values in options.items())
    return {**options, 'source_url': PORTAL_URL, 'text': text}
