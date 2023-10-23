#!python
from __future__ import annotations

import argparse
import itertools
import os
import tomli_w
import tomllib
import truststore
from dataclasses import dataclass
from enum import Enum

from gitlab import Gitlab, GitlabListError
from gitlab.v4.objects import Project, ProjectPipeline


class Modifier(Enum):
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    GREY = '\033[90m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    ITALICS = '\x1B[3m'

    def __str__(self):
        return self.value


class Painter:
    @staticmethod
    def colored_status_pipeline(status: str):
        mapping: dict[str, Modifier] = {
            "created": Modifier.WARNING,
            "running": Modifier.WARNING,
            "canceled": Modifier.GREY,
            "success": Modifier.OKGREEN,
        }
        color = mapping.get(status, Modifier.FAIL)
        return Painter.colored(status, color)

    @staticmethod
    def colored_status_job(status: str):
        mapping: dict[str, Modifier] = {
            "created": Modifier.WARNING,
            "running": Modifier.WARNING,
            "failed": Modifier.FAIL
        }
        color = mapping.get(status, Modifier.GREY)
        return Painter.colored(status, color)

    @staticmethod
    def colored(text: str, color: Modifier, modifier: Modifier = None):
        return str(color) + (str(modifier) if modifier else '') + text + str(Modifier.ENDC)


class ExternalConfig:
    config = None
    config_file = os.path.expanduser('~/.pipelineutil.toml')
    is_changed = False

    def __init__(self):
        self.__load()
        self.__verify()

    def __load(self):
        exists = os.path.exists(self.config_file)
        if exists:
            with open(self.config_file, 'rb') as f:
                self.config = tomllib.load(f)

    def __verify(self):
        if not self.config:
            self.config = {'servers': {}}

    def __servers(self):
        return self.config['servers'] if self.config and 'servers' in self.config else {}

    def __serves_any(self):
        return len(self.__servers().keys()) > 0

    def __server(self, alias):
        return self.__servers()[alias] if alias in self.__servers() else None

    def active_server(self):
        servers = self.__servers().items()
        filtered = (values for (alias, values) in servers if 'active' in values and values['active'])
        active = next(filtered, None)
        return active if active else self.__active_fallback()

    @staticmethod
    def __active_fallback():
        env_url = 'PIPELINEUTIL_URL'
        env_token = 'PIPELINEUTIL_TOKEN'
        return {
            "url": os.environ.get(env_url),
            "token": os.environ.get(env_token)
        }

    def add_server(self, args):
        is_update = args.alias in self.__servers().keys()
        self.__servers()[args.alias] = ExternalConfig.__create_server_config(args)
        self.is_changed = True
        print(f"{'Updated' if is_update else 'Added'} config for '{args.alias}'.")
        self.switch_server(args.alias)

    @staticmethod
    def __create_server_config(args):
        server_config = {'url': args.url, 'active': True}
        if args.token:
            server_config['token'] = args.token
        return server_config

    def switch_server(self, alias: str):
        if not self.__server(alias):
            print(f"Server '{alias}' is unknown.")
            return
        for server in self.__servers():
            server_config = self.__servers()[server]
            server_config['active'] = server == alias
        print(f"Switched to server '{alias}'.")
        self.is_changed = True
        self.list_servers()

    def list_servers(self):
        if not self.__serves_any():
            return

        max_len_alias = max([len(alias) for alias in self.__servers().keys()])
        max_len_url = max([len(self.__servers()[c]['url']) for c in self.__servers().keys()])

        aliases_ordered = list(self.__servers().keys())
        aliases_ordered.sort()

        for alias in aliases_ordered:
            server_config = self.__servers()[alias]

            is_active = server_config['active'] if 'active' in server_config else False
            alias_text = f"{alias:<{max_len_alias}s}"
            has_token = 'token' in server_config

            display_active = '*' if is_active else ' '
            display_alias = Painter.colored(alias_text, Modifier.OKGREEN) if is_active else alias_text
            display_url = f"{server_config['url']:<{max_len_url}s}"
            display_token = '*' * len(server_config['token']) if has_token else '<no token>'
            print(f"{display_active} {display_alias} {display_url} {display_token}")

    def remove_server(self, alias):
        if not self.__server(alias):
            print(f"Server '{alias}' is unknown.")
            return

        del self.__servers()[alias]
        self.is_changed = True

        any_active = any(server['active'] for (server_alias, server) in self.__servers().items() if 'active' in server)
        any_remaining = len(self.__servers().keys()) > 0
        if not any_active and any_remaining:
            next_active = list(self.__servers())[0]
            self.__servers()[next_active]['active'] = True
            print(f"Server '{next_active}' is now active.")

        if any_remaining:
            self.list_servers()
        else:
            print(f"No servers remaining.")

    def update(self):
        if self.is_changed:
            with open(self.config_file, 'wb+') as f:
                tomli_w.dump(self.config, f)


@dataclass
class RunConfig:
    url: str
    token: str | None
    filter_project: str
    filter_pipelines: str
    limit_projects: int
    limit_pipelines: int
    limit_pipelines_depth: int
    failed_show_link: bool = False  # experimental feature
    failed_hide_jobs_all: bool = True  # experimental feature
    failed_hide_jobs_okay: bool = True  # experimental feature


def parse_args():
    opt = argparse.BooleanOptionalAction
    parser = argparse.ArgumentParser(prog='PipelineUtil', description='Displays pipeline status on CI-server.')
    parser.add_argument('-v', '--verbose', type=bool, default=False, action=opt, help='verbose output')

    subparsers = parser.add_subparsers()

    parser_run = subparsers.add_parser('run', help='check status')
    parser_run.set_defaults(which='run')
    group_filter = parser_run.add_argument_group('filter')
    group_filter.add_argument('-p', '--projects', type=str,
                              help='matches against name including namespace')
    group_filter.add_argument('-r', '--references', type=str,
                              help='matches against branch/ref the pipeline is run on')
    group_limits = parser_run.add_argument_group('limits')
    group_limits.add_argument('--limit-projects', type=int, default=3,
                              help='limits projects shown')
    group_limits.add_argument('--limit-pipelines', type=int, default=5,
                              help='limits pipelines shown per project')
    group_limits.add_argument('--limit-pipelines-search-depth', type=int, default=50,
                              help='limits search depth for refs')

    parser_add = subparsers.add_parser('add', help='add server')
    parser_add.set_defaults(which='add')
    parser_add.add_argument('alias', type=str,
                            help='name of the gitlab instance')
    parser_add.add_argument('url', type=str,
                            help='url of the gitlab instance')
    parser_add.add_argument('token', nargs='?', type=str,
                            help='token for authentification (stored as plaintext)')

    parser_switch = subparsers.add_parser('switch', aliases=['s'], help='switch server')
    parser_switch.set_defaults(which='switch')
    parser_switch.add_argument('alias', type=str, help='to switch to (as configured)')

    parser_list = subparsers.add_parser('list', aliases=['ls'], help='list servers')
    parser_list.set_defaults(which='list')

    parser_remove = subparsers.add_parser('remove', aliases=['rm'], help='remove server')
    parser_remove.set_defaults(which='remove')
    parser_remove.add_argument('alias', type=str, help='to be removed (from the configuration)')

    return parser.parse_args()


def run_command(args: argparse.Namespace):
    # Read configuration.
    config = ExternalConfig()
    # Run commands.
    if args.which == 'run':
        config_active = config.active_server()
        config_run = convert(config_active, args)
        main(config_run)
    elif args.which == 'add':
        config.add_server(args)
    elif args.which == 'switch':
        config.switch_server(args.alias)
    elif args.which == 'list':
        config.list_servers()
    elif args.which == 'remove':
        config.remove_server(args.alias)
    # Update configuration.
    config.update()


def convert(config, args: argparse.Namespace):
    config = RunConfig(
        config['url'],
        config['token'] if 'token' in config else None,
        args.projects,
        args.references,
        args.limit_projects,
        args.limit_pipelines,
        args.limit_pipelines_search_depth)

    if args.verbose:
        config.failed_hide_jobs_all = False
        config.failed_hide_jobs_okay = False
        config.failed_show_link = True
    return config


def main(config: RunConfig):
    gitlab = connect(config)
    for project in retrieve_projects(gitlab, config):
        print(format_project(project))
        for pipeline in retrieve_pipelines(project, config):
            print(format_pipeline(pipeline))
            if not is_okay(pipeline) and not config.failed_hide_jobs_all:
                if config.failed_show_link:
                    print(f"   # {pipeline.web_url}")
                for job in retrieve_jobs(pipeline, config):
                    print(format_job(job))


def connect(config):
    if not config.url:
        print(f"Connects to 'https://gitlab.com' by default...")
    return Gitlab(url=config.url, private_token=config.token)


def retrieve_projects(gitlab: Gitlab, config: RunConfig) -> list[Project]:
    contains = config.filter_project
    projects_iter = gitlab.projects.list(iterator=True, search=contains, starred=not bool(contains))
    projects = list(itertools.islice(projects_iter, config.limit_projects))
    return sorted(projects, key=lambda p: p.name_with_namespace)


def format_project(project: Project) -> str:
    return Painter.colored(project.name_with_namespace, Modifier.HEADER)


def retrieve_pipelines(project: Project, config: RunConfig) -> list[ProjectPipeline]:
    try:
        iterator = project.pipelines.list(iterator=True)
    except GitlabListError as error:
        print(f"|- Skipped: {Painter.colored(error.error_message, Modifier.FAIL)}")
        return []

    found = []
    for idx, pipeline in enumerate(iterator):
        if pipeline is None or idx >= config.limit_pipelines_depth:
            break  # no more pipelines.
        if not config.filter_pipelines or config.filter_pipelines in pipeline.ref:
            found.append(pipeline)
        if len(found) >= config.limit_pipelines:
            break  # enough pipelines found.
    return found


def format_pipeline(pipeline: ProjectPipeline) -> str:
    pipeline_id = f"{str(pipeline.id) + ' ':-<19s}"
    pipeline_ref = f"{pipeline.ref[:29] + ' ':-<31s}" + ">"
    pipeline_status = Painter.colored_status_pipeline(pipeline.status)
    return f"|- {pipeline_id} {pipeline_ref} {pipeline_status}"


def is_okay(pipeline: ProjectPipeline):
    return pipeline.status in ["success", "canceled"]


def retrieve_jobs(pipeline: ProjectPipeline, config: RunConfig):
    jobs = sorted(pipeline.jobs.list(), key=lambda j: j.created_at)
    filtered = jobs if not config.failed_hide_jobs_okay else [j for j in jobs if j.status not in ["skipped", "success"]]
    return filtered


def format_job(job) -> str:
    job_stage = f"{job.stage:<20.19s}"
    job_name = f"{job.name:<32.31s}"
    job_status = Painter.colored_status_job(job.status)
    return f"   > {job_stage}{job_name} {job_status}"


if __name__ == '__main__':
    try:
        truststore.inject_into_ssl()
        pargs = parse_args()
        run_command(pargs)
    except KeyboardInterrupt:
        print("[...]")
