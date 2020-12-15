import argparse
import configparser
import datetime
import json
import logging
import os
import pathlib
import re
import threading
import sys

from urllib.parse import urlparse, urlencode, parse_qsl
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from xdg import BaseDirectory
except ImportError:
    BaseDirectory = None


PROGRAMNAME = 'gitlab-todotxt'
HERE = pathlib.Path(os.path.abspath(__file__)).parent
HOME = pathlib.Path.home()
CONFIGDIR = HOME / ".config" / PROGRAMNAME
CONFIGFILE = HOME / ".config" / PROGRAMNAME / (PROGRAMNAME + ".conf")
CACHEDIR = HOME / ".cache" / PROGRAMNAME
CACHEFILE = CACHEDIR / (PROGRAMNAME + ".cache")

if BaseDirectory is not None:
    CONFIGDIR = pathlib.Path(BaseDirectory.save_config_path(PROGRAMNAME) or CONFIGDIR)
    CONFIGFILE = CONFIGDIR / (PROGRAMNAME + ".conf")
    CACHEDIR = pathlib.Path(BaseDirectory.save_cache_path(PROGRAMNAME) or CACHEDIR)
    CACHEFILE = CACHEDIR / (PROGRAMNAME + ".cache")

DATE_FMT = '%Y-%m-%d'
DEFAULT_FORMAT = '{delegate} {title} {due} {project} {milestone} {estimate} {spent} {url}'


def get_config(args):
    conf = configparser.ConfigParser(interpolation=None)
    conffile = pathlib.Path(args.config).expanduser().resolve()

    if conffile.exists() and conffile.is_file():
        conf.read([conffile])
    
    return conf


def duration_as_str(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    result = ''
    if hours > 0:
        result += f'{hours}h'
    if minutes > 0:
        result += f'{minutes}m'

    return result


def unspacify(text):
    for char in "  \t\n":
        text = text.replace(char, '_')
    return text


class GitlabSource:
    def __init__(self, name, config):
        self.displayname = name
        # TODO configurable
        self.delegation_mark = '@delegated'
        self._tasks = []
        self.config = config

        for required in ['url', 'token', 'file']:
            if required not in config:
                raise RuntimeError(f"Missing configuration option '{required}' for '{name}'")

        self.target = pathlib.Path(config['file']).expanduser().resolve()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.url = urlparse(config['url'])
        self.match_users = set([u.strip()
                                for u in config.get('users', '').split(',')
                                if len(u.strip()) > 0])
        self.match_namespaces = set([m.strip()
                                     for m in config.get('namespaces', '').split(',')
                                     if len(m.strip()) > 0])
        self.match_projects = set([p.strip()
                                   for p in config.get('projects', '').split(',')
                                   if len(p.strip()) > 0])
        self.show_unassigned = config.get('unassigned', 'n').lower() \
                               in ['1', 'yes', 'y', 'true', 'on']
        self.labels_are_projects = config.get('labels-are-projects', 'n').lower() \
                                   in ['1', 'yes', 'y', 'true', 'on']
        self.milestone_prefix = config.get('milestone-prefix', 'milestone:')
        self.format = config.get('format', DEFAULT_FORMAT)
        self._projects_by_id = {}
        self._projects_by_name = {}
        self._projects = set()
        self._uid = None
        self._username = None
        self._contexts = set()
        self.last_refresh = datetime.datetime.min
        # TODO configurable
        self.refresh_interval = datetime.timedelta(minutes=2)
        self.load_completed = threading.Event()
        self._lock = threading.Lock()

    def process(self):
        if self.last_refresh > datetime.datetime.now() - self.refresh_interval:
            return False

        if self._lock.acquire(blocking=False):
            logging.debug("Starting {}".format(self.displayname))
            thread = threading.Thread(target=self.do_load)
            thread.start()
            return thread
        return False

    def do_load(self):
        self._tasks = []
        self._projects = set()

        cache_entries = None
        if CACHEFILE.exists():
            cache_entries = json.loads(CACHEFILE.read_text())
            projects = cache_entries.get(self.displayname, {'projects': []})['projects']
            self._projects_by_id = dict([(data[0], (data[1], data[2]))
                                        for data in projects])
            self._projects_by_name = dict([(data[1] + "/" + data[2], data[0])
                                          for data in projects])
        else:
            cache_entries = {self.displayname: {'projects': []}}

        issues = []
        reload_projects = set()

        for item in self.query_api('issues'):
            issue = {
                'created': parse_timestamp(item['created_at'].split('.', 1)[0]),
                'closed': None,
                'title': item['title'],
                'iid': item['iid'],
                'uid': item['id'],
                'url': item['web_url'],
                'state': item['state'],
                'labels': {unspacify(label) for label in item.get('labels', [])},
                'assignees': set([user['username'] for user in item['assignees']]),
                'projectid': item['project_id'],
                'due': None,
                'estimate': None,
                'spent': None,
                'milestone': None,
                'estimate': None,
                'spent': None,
            }

            if item['closed_at'] is not None:
                issue['closed'] = parse_timestamp(item['closed_at'].split('.', 1)[0])

            if item['due_date'] is not None:
                issue['due'] = datetime.datetime.strptime(item['due_date'], DATE_FMT).date()

            if item['due_date'] is None and \
               item['milestone'] is not None and \
               item['milestone']['due_date'] is not None:
                issue['due'] = datetime.datetime.strptime(item['milestone']['due_date'], DATE_FMT).date()

            if item['milestone'] is not None:
                issue['milestone'] = unspacify(item['milestone']['title'])

            if item['time_stats']['time_estimate'] > 0:
                issue['estimate'] = duration_as_str(item['time_stats']['time_estimate'])

            if item['time_stats']['total_time_spent'] > 0:
                issue['spent'] = duration_as_str(item['time_stats']['total_time_spent'])

            issues.append(issue)

            if item['project_id'] not in self._projects_by_id:
                reload_projects.add(item['project_id'])

        for project_id in reload_projects:
            for item in self.query_api(f'projects/{project_id}'):
                fullname = item.get('path_with_namespace', None)
                if fullname is None:
                    continue
                if self.displayname not in cache_entries:
                    cache_entries[self.displayname] = {'projects': []}
                cache_entries[self.displayname]['projects'].append([item['id'],
                                                                    item['namespace']['path'],
                                                                    item['name']])

            CACHEFILE.write_text(json.dumps(cache_entries))
            self._projects_by_id = dict([(data[0], (data[1], data[2]))
                                        for data in cache_entries[self.displayname]['projects']])
            self._projects_by_name = dict([(data[1] + "/" + data[2], data[0])
                                          for data in cache_entries[self.displayname]['projects']])

        for issue in issues:
            namespace, project = self._projects_by_id.get(issue.get('projectid', None), ['', 'unknown_project'])

            include = all([
                len(self.match_namespaces) == 0 or namespace in self.match_namespaces,
                len(self.match_projects) == 0 or project in self.match_projects,
                self._username in issue['assignees'] or
                    len(self.match_users) == 0 or
                    len(issue['assignees'].intersection(self.match_users)) > 0 or
                    (len(issue['assignees']) == 0 and self.show_unassigned),
                ])

            if not include:
                continue

            self._projects.add(project)

            if issue['closed'] is not None:
                # Format for closed issues
                text = 'x ' + issue['closed'].strftime(DATE_FMT) + " " + issue['created'].strftime(DATE_FMT)
            else:
                # Format for open issues
                text = issue['created'].strftime(DATE_FMT)

            project = '+' + unspacify(project)
            title = issue['title']

            delegation = ' '.join(['to:' + user
                                   for user in sorted(issue['assignees']) if user != self._username])
            if len(delegation) > 0:
                delegation = self.delegation_mark + ' ' + delegation
            else:
                delegation = ''

            labels = ''
            if len(issue['labels']) > 0 and self.labels_are_projects:
                self._projects |= set([label.lower()for label in issue['labels']])
                labels = ' '.join('+' + label for label in sorted(issue['labels']))
            
            url = issue['url']

            milestone = ''
            if issue['milestone'] is not None and len(issue['milestone']) > 0:
                milestone = self.milestone_prefix + issue['milestone']

            due = ''
            if issue['due'] is not None:
                due = 'due:' + issue['due'].strftime(DATE_FMT)

            spent = ''
            if issue['spent'] is not None:
                spent = 'spent:' + issue['spent']

            estimate = ''
            if issue['estimate'] is not None:
                estimate = 'estimate:' + issue['estimate']

            text = text + ' ' + self.format.format(title=issue['title'],
                                                   delegate=delegation,
                                                   project=project,
                                                   url=url,
                                                   due=due,
                                                   estimate=estimate,
                                                   spent=spent,
                                                   milestone=milestone)

            # TODO: upon synchronisation this must be added to tasks to reconnect after parsing
            # text += " id:" + self.displayname + ':' + str(issue['uid'])
            self._tasks.append(text)

        self.last_refresh = datetime.datetime.now()
        self.load_completed.set()

        try:
            self.target.write_text("\n".join(sorted([line for line in self._tasks])))
        except exc:
            logging.error(f"Failed to write {self.displayname} to {self.target}: {exc}")
        self._lock.release()

    def test_connection(self):
        for result in self.query_api('user'):
            self._uid = result['id']
            self._username = result['username']
            return True
        return False

    def query_api(self, endpoint, query=None):
        baseurl = f"{self.url.scheme}://{self.url.netloc}/api/v4/{endpoint}"
        total_pages = 1
        page = 0
        if query is None:
            query = {}

        while page < total_pages:
            url = baseurl
            if page > 0:
                query['page'] = str(page+1)
            if len(query) > 0:
                url += '?' + urlencode(query)
            req = Request(url=url,
                          headers={'Private-Token': self.config['token']})
            try:
                with urlopen(req) as f:
                    rawdata = f.read()
                    if 'X-Total-Pages' in f.headers:
                        total_pages = int(f.headers['X-Total-Pages'])
                    try:
                        chunk = json.loads(rawdata)
                        if isinstance(chunk, dict):
                            yield chunk
                        elif isinstance(chunk, list):
                            for item in chunk:
                                yield item
                    except json.JSONDecodeError as exc:
                        logging.error(f"Failed to understand the reply from {baseurl}: {exc}")
                page += 1
            except HTTPError as exc:
                logging.error(f"HTTP request failed: {exc}")
                break


def parse_timestamp(value):
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        raise


def tr(text):
    return text


def run():
    logging.basicConfig(format="[%(levelname)s] %(message)s")
    logging.getLogger().setLevel('ERROR')

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config',
                        type=str,
                        default=CONFIGFILE,
                        help=tr("Location of your configuration file. Defaults to %(default)s."))
    args = parser.parse_args(sys.argv[1:])
    config = get_config(args)

    CACHEDIR.mkdir(mode=0o750, parents=True, exist_ok=True)

    sources = []

    for sectionname in config.sections():
        if sectionname == 'General':
            continue
        section = config[sectionname]

        try:
            source = GitlabSource(sectionname, section)
            if not source.test_connection():
                logging.fatal(f"Could not connect to {section}")
                return
            sources.append(source)
        except RuntimeError as exc:
            logging.error(f"Failed to load source {sectionname}: {exc}")

    threads = [source.process() for source in sources]

    for thread in threads:
        thread.join()

