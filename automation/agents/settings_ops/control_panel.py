"""Classic Control Panel tasks ("God Mode" folder): list them and open one by name."""
import difflib
import json
import time

from . import ActionError
from . import system, ui

FOLDER = "shell:::{ED7BA470-8E54-465E-825C-99712043E01C}"
_cache = None  # parsed task list, kept for the process lifetime


def _tasks():
    global _cache
    if _cache is None:
        code, out = system._powershell(
            f"$o = (New-Object -ComObject Shell.Application).NameSpace('{FOLDER}').Items() | ForEach-Object "
            "{ [pscustomobject]@{Name=$_.Name; Path=$_.Path; Group=[string]$_.ExtendedProperty('System.ApplicationName')} }; "
            "ConvertTo-Json -Compress -InputObject @($o)", timeout=60)
        try:
            items = json.loads(out)
        except ValueError:
            items = None
        if code or not items:
            raise ActionError(f'Windows did not list the Control Panel tasks: {out[:200]}')
        _cache = [{'name': i['Name'], 'group': i['Group'] or '', 'path': i['Path']} for i in items if i['Name']]
    return _cache


def _words_in(query, *texts):
    haystack = ' '.join(texts).casefold()
    return all(word in haystack for word in str(query).casefold().split())


def list_tasks(query=''):
    seen, tasks = set(), []
    for task in _tasks():
        key = (task['name'], task['group'])
        if key not in seen and _words_in(query, task['name'], task['group']):
            seen.add(key)
            tasks.append({'name': task['name'], 'group': task['group']})
    return {'count': len(tasks), 'tasks': tasks,
            'text': '\n'.join(f"{t['name']} ({t['group']})" if t['group'] else t['name'] for t in tasks)
                    or f"No Control Panel task matches '{query}'."}


def _invoke(path):
    # The path travels in the environment, never in the script text.
    code, out = system._powershell(
        "$i = (New-Object -ComObject Shell.Application).NameSpace('" + FOLDER + "').Items() | "
        "Where-Object { $_.Path -eq $env:AURA_CP_PATH } | Select-Object -First 1; "
        "if (-not $i) { exit 2 }; $i.InvokeVerb()", env={'AURA_CP_PATH': path})
    if code:
        raise ActionError(f'Windows could not open that Control Panel task: {out[:200]}')


def _new_window(before, before_foreground, timeout=6):
    """Title of the window the task opened (a new one, a retitled one, or one brought to the front), else None."""
    deadline = time.monotonic() + timeout
    while True:
        now, front = ui.top_windows(), ui.foreground()
        for handle, (kind, title) in now.items():
            if before.get(handle) != (kind, title) or front == handle != before_foreground:
                return 'Settings' if kind == ui.SETTINGS_CLASS else title
        if time.monotonic() > deadline:
            return None
        time.sleep(.3)


def open_task(name):
    name = str(name or '').strip()
    if not name:
        raise ActionError('name of a Control Panel task is required.')
    tasks = _tasks()
    hits = [t for t in tasks if t['name'].casefold() == name.casefold()]
    hits = hits or [t for t in tasks if _words_in(name, t['name'])]
    if not hits:
        close = difflib.get_close_matches(name.casefold(), [t['name'].casefold() for t in tasks], n=5, cutoff=0.6)
        hits = [t for t in tasks if t['name'].casefold() in close]
    distinct = {(t['name'], t['group']): t for t in hits}
    if len(distinct) != 1:
        if not distinct:
            raise ActionError(f"No Control Panel task matches '{name}'. Try list_control_panel_tasks with a search word.")
        names = sorted({t['name'] for t in hits})[:10]
        raise ActionError(f"'{name}' matches several Control Panel tasks; pass one exactly: {'; '.join(names)}.")
    task = next(iter(distinct.values()))
    before, front = ui.top_windows(), ui.foreground()
    _invoke(task['path'])  # Opens the task's own window/page; it does not change any value.
    window = _new_window(before, front)
    note = {'Settings': 'This task opened the Settings app: use read_page / set_toggle / click WITHOUT the window param.',
            None: 'No window was detected; if one is on screen, pass its exact title as window.'}
    return {'opened': task['name'], 'group': task['group'], 'window': window,
            **({'note': note[window]} if window in note else {})}
