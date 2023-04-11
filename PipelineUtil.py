#!python
from __future__ import annotations

import argparse
import itertools
import os
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


@dataclass
class Config:
    url: str
    token: str
    filter_project: str
    filter_pipelines: str
    limit_projects: int
    limit_pipelines: int
    limit_pipelines_depth: int
    failed_show_link: bool = False  # experimental feature
    failed_hide_jobs_all: bool = True  # experimental feature
    failed_hide_jobs_okay: bool = True  # experimental feature


def parse_args():
    env_url = 'PIPELINEUTIL_URL'
    env_token = 'PIPELINEUTIL_TOKEN'
    action_bool = argparse.BooleanOptionalAction

    parser = argparse.ArgumentParser(prog='PipelineUtil', description='Displays pipeline status on CI-server.')

    parser.add_argument('-u', '--url', type=str, help=f"url to gitlab instance (or set {env_url} in env)")
    parser.add_argument('-t', '--token', type=str, help=f"token for authentification (or set {env_token} in env)")
    parser.add_argument('-p', '--projects', type=str, help='matches against name including namespace')
    parser.add_argument('-r', '--references', type=str, help='matches against branch/ref the pipeline is run on')
    parser.add_argument('-v', '--verbose', type=bool, default=False, action=action_bool, help='verbose output')

    group = parser.add_argument_group('limits')
    group.add_argument('--limit-projects', type=int, default=3, help='limits projects shown')
    group.add_argument('--limit-pipelines', type=int, default=5, help='limits pipelines shown per project')
    group.add_argument('--limit-pipelines-search-depth', type=int, default=50, help='limits search depth for refs')

    pargs = parser.parse_args()

    config = Config(
        pargs.url if pargs.url else os.environ.get(env_url),
        pargs.token if pargs.token else os.environ.get(env_token),
        pargs.projects,
        pargs.references,
        pargs.limit_projects,
        pargs.limit_pipelines,
        pargs.limit_pipelines_search_depth)

    if pargs.verbose:
        config.failed_hide_jobs_all = False
        config.failed_hide_jobs_okay = False
        config.failed_show_link = True

    return config


def main(config: Config):
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
        print(f"Connecting to 'https://gitlab.com' by default...")
    return Gitlab(url=config.url, private_token=config.token)


def retrieve_projects(gitlab: Gitlab, config: Config) -> list[Project]:
    contains = config.filter_project
    projects_iter = gitlab.projects.list(iterator=True, search=contains, starred=not bool(contains))
    projects = list(itertools.islice(projects_iter, config.limit_projects))
    return sorted(projects, key=lambda p: p.name_with_namespace)


def format_project(project: Project) -> str:
    return Painter.colored(project.name_with_namespace, Modifier.HEADER)


def retrieve_pipelines(project: Project, config: Config) -> list[ProjectPipeline]:
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


def retrieve_jobs(pipeline: ProjectPipeline, config: Config):
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
        configuration = parse_args()
        main(configuration)
    except KeyboardInterrupt:
        print("[...]")
