import fcntl
import grp
import hashlib
import json
import logging
import os
from pathlib import Path
from subprocess import run, CalledProcessError
from typing import List, Optional, Counter, Tuple

import numpy as np
from flask import Response
from flask import request as flask_request
from werkzeug.exceptions import BadRequestKeyError

from exceptions import AutogeneratedFileError, InfoFileError, CleanUpError, ConfigFileError
from models.enums import Subset, Content
from nbgrader.api import Gradebook


def load_json(path: str) -> dict:
    """
    Loads JSON data from a specified file path, with error handling for file access issues.

    Parameters
    ----------
    path : str
        The file path to the JSON file to be loaded.

    Returns
    -------
    dict
        A dictionary containing the JSON data loaded from the file.
    """

    with open(file=path, mode='r') as file:
        return json.load(file)


def load_config(path: str) -> dict:
    try:
        return load_json(path=path)
    except (FileNotFoundError, OSError, PermissionError):
        raise ConfigFileError


def load_info(path: str) -> dict:
    try:
        return load_json(path=path)
    except (FileNotFoundError, OSError, PermissionError):
        raise InfoFileError


def handle_clean_up(path: str, kore_token: str, base_url: str, course_id: str):
    try:
        # Remove students from gradebook.
        with Gradebook(f'sqlite:///{path}/gradebook.db') as gb:
            usernames = [student.id for student in gb.students]
            for username in usernames:
                gb.remove_student(username)

        # Remove students from courses nbgrader group.
        run(['systemd-run', 'curl',
             '-H', 'Content-Type: application/json',
             '-H', 'Accept: application/json',
             '-H', f'Authorization: token {kore_token}',
             '-X', 'DELETE',
             '-d', '{"users":' + json.dumps(usernames) + '}',
             f'http://127.0.0.1:8081/{base_url}hub/api/groups/nbgrader-{course_id}/users'], check=True)

        # Clean up the nbgrader exchange directory.
        run(['rm', '-rf', f'/opt/nbgrader_exchange/{course_id}/'], check=True)

        # Clean up course directory.
        run(['rm', f'{path}/gradebook.db'], check=True)
        for directory in ['autograded', 'feedback', 'release', 'submitted']:
            run(['rm', '-rf', f'{path}/{directory}/'], check=True)
    except [FileNotFoundError, PermissionError, KeyError, CalledProcessError]:
        raise CleanUpError


def make_course_id(lti_state: dict) -> Tuple[str, str, str, str]:
    """
    Make course ID, course title, grader username from LTI data.

    Parameters
    ----------
    lti_state : dict
        The authentication dict for the user.

    Returns
    -------
    tuple[str, str, str]
        The returned tuple contains the course id, course title and the grader user as strings.
    """

    deployment_id = lti_state.get('https://purl.imsglobal.org/spec/lti/claim/deployment_id', '0')
    resource_link_id = lti_state.get('https://purl.imsglobal.org/spec/lti/claim/resource_link').get('id')
    resource_link_title = lti_state.get('https://purl.imsglobal.org/spec/lti/claim/resource_link').get('title')
    context_title = lti_state.get('https://purl.imsglobal.org/spec/lti/claim/context', {}).get('title')

    h = hashlib.shake_256(f'{deployment_id}-{resource_link_id}'.encode())
    course_id = 'c-' + h.hexdigest(8)
    grader_user = course_id[0:32]

    if resource_link_title and context_title:
        course_title = f'{context_title} - {resource_link_title}'
    elif resource_link_title:
        course_title = resource_link_title
    elif context_title:
        course_title = context_title
    else:
        course_title = 'No title available'
    course_title_long = f'{course_title} ({course_id})'.replace('\'', '')
    course_title_short = f'{course_title}'.replace('\'', '')

    return course_id, course_title_long, course_title_short, grader_user


def read_autogenerated_config(autogenerated_file_path: str) -> Tuple[list, list, dict]:
    """
    Read services, roles and groups from the autogenerated configuration file.

    Parameters
    ----------
    autogenerated_file_path : str
        Path to the autogenerated configuration file.

    Returns
    -------
    tuple[list, list, dict]
         The returned tuple contains the services (list), the roles (list) and the groups (dict).
    """

    try:
        with open(file=autogenerated_file_path, mode='r') as autogenerated_file:
            # Read Python code from config file.
            logging.debug('Reading autogenerated service configuration.')
            config_code = autogenerated_file.read()
    except FileNotFoundError:
        # File is not present and a new one will be created.
        logging.debug('No autogenerated service file found! A new one will be created.')
        write_autogenerated_config(autogenerated_file_path=autogenerated_file_path, services=[], roles=[], groups={})
        config_code = ''
    except PermissionError:
        logging.debug('Autogenerated services files not readable!')
        run(['chmod', '600', autogenerated_file_path], check=True)
        with open(file=autogenerated_file_path, mode='r') as autogenerated_file:
            logging.debug('Reading autogenerated service configuration.')
            config_code = autogenerated_file.read()
    except CalledProcessError:
        logging.error('Command cannot be executed!')
        raise AutogeneratedFileError

    # Modify Python code.
    logging.debug('Extracting services, roles and groups from file.')
    config_code = config_code.replace('c = get_config()', '')
    config_code = config_code.replace('c.JupyterHub.services', 'services')
    config_code = config_code.replace('c.JupyterHub.load_roles', 'roles')
    config_code = config_code.replace('c.JupyterHub.load_groups', 'groups')

    # Execute Python code.
    services, roles, groups = [], [], {}
    exec(config_code)

    return services, roles, groups


def write_autogenerated_config(autogenerated_file_path: str, services: list, roles: list, groups: dict) -> None:
    """
    Write services, roles and groups to a Python file. Which is read and used by the JupyterHub after next restart.

    Parameters
    ----------
    autogenerated_file_path : str
        Path to the autogenerated configuration file.

    services : list
        A list containing the services.

    roles : list
        A list containing the roles.

    groups : dict
        A dict containing the groups.

    Returns
    -------
    None
    """

    logging.debug('Writing autogenerated service configuration.')

    # Compose code to be written.
    config_code = '# Autogenerated nbgrader course configuration (DO NOT MODIFY)\n\n'
    config_code += 'c = get_config()\n\n'

    config_code += '# Services\n'
    for service in services:
        config_code += 'c.JupyterHub.services.append(' + str(service) + ')\n'
    config_code += '\n'

    config_code += '# Roles\n'
    for role in roles:
        config_code += 'c.JupyterHub.load_roles.append(' + str(role) + ')\n'
    config_code += '\n'

    config_code += '# Groups\n'
    config_code += 'c.JupyterHub.load_groups.update(' + str(groups) + ')\n'

    # Write code to file.
    try:
        with open(file=autogenerated_file_path, mode='w') as autogenerated_file:
            fcntl.flock(autogenerated_file, fcntl.LOCK_EX)
            autogenerated_file.write(config_code)
            fcntl.flock(autogenerated_file, fcntl.LOCK_UN)
        run(['chmod', '600', autogenerated_file_path], check=True)
    except CalledProcessError:
        logging.error('Command cannot be executed!')
        raise AutogeneratedFileError
    except PermissionError:
        logging.debug('Autogenerated services files not readable!')


def get_hub_base_url(lti_state: dict) -> str:
    """
    Read base url of JupyterHub from lti state json.

    Parameters
    ----------
    lti_state : dict
        lti state file (json) containing lti parameters.

    Returns
    -------
    str
        The base url of the JupyterHub as string.
    """

    base_url = lti_state['https://purl.imsglobal.org/spec/lti/claim/target_link_uri']
    base_url = '/'.join(base_url.strip('/').split('://')[-1].split('/')[1:]) + '/'
    logging.debug(f'Base url of JupyterHub as retrieved from the LTI state file: {base_url}.')

    base_url = '' if base_url == '/' else base_url

    return base_url


def get_active_paths(user_name: str, groups: dict, content: Content, subset: Subset) -> List[str]:
    """
    Retrieves active paths based on the content type within specified base paths.

    Parameters
    ----------
    user_name : str
        The current users user_name.
    groups : dict
        The groups of the user.
    content : Content
        The type of content to search for. Must be an instance of the `Content` enum.
        Valid values are:
        - `Content.COURSES`: Search for course directories.
        - `Content.ASSIGNMENTS`: Search for assignment directories within course sources.
        - `Content.PROBLEMS`: Search for problem files (e.g., `.ipynb` notebooks) within course sources.
    subset : Subset
        The subset of courses to look for. Only valid if content is Content.COURSES.

    Returns
    -------
    List[str]
        A sorted list of active paths as strings. Paths are filtered to exclude directories or files
        that are hidden (i.e., starting with a dot) or are within hidden parent directories.
    """

    # Generating the Subset.ACTIVE course list.
    if subset == Subset.ALL or subset == Subset.ACTIVE:
        owned_groups = [
            group.lstrip('formgrade-')
            for group in groups
            if user_name in groups.get(group)
        ]
        base_paths = [
            item.path.removesuffix('/')
            for item in os.scandir('/home')
            if item.is_dir() and grp.getgrgid(os.stat(item.path).st_gid)[0] in owned_groups
        ]
        logging.debug(f'Owned groups: {owned_groups}')
        logging.debug(f'Base paths: {base_paths}')

        active_paths = []

        for base_path in base_paths:
            paths = []

            if content == Content.COURSES:
                specific_path = Path(f'{base_path}/course_data/')
                if specific_path.exists():
                    paths = [specific_path / '']
            elif content == Content.ASSIGNMENTS:
                specific_path = Path(f'{base_path}/course_data/source/')
                if specific_path.exists():
                    paths = specific_path.glob('*/')
            elif content == Content.PROBLEMS:
                specific_path = Path(f'{base_path}/course_data/source/')
                if specific_path.exists():
                    paths = specific_path.rglob('*.ipynb')
            else:
                raise ValueError(f"Invalid content type: {content}")

            active_paths.extend(
                str(path) for path in paths
                if path.is_dir() or (content == Content.PROBLEMS and path.is_file())
                and not any(part.name.startswith('.') for part in path.parents)
            )

        return sorted(active_paths)

    # Generate the list with path of current course.
    elif content == Content.COURSES and subset == Subset.CURRENT:
        # TODO: Add try except.
        lti_file_path = f'/opt/kore/runtime/lti_{user_name}.json'
        with open(lti_file_path, 'r') as lti_file:
            lti_state = json.load(lti_file)
        _, _, _, grader_user = make_course_id(lti_state=lti_state)
        return [f'/home/{grader_user}/course_data']


def get_backed_up_paths(user_name: str, content: Content) -> List[str]:
    """
    Retrieves backed-up paths for a given user based on the content type.

    Parameters
    ----------
    user_name : str
        The username whose backup directory is to be searched.
    content : Content
        The type of content to search for. Must be an instance of the `Content` enum.
        Valid values are:
        - `Content.COURSES`: Search for backed-up course directories.
        - `Content.ASSIGNMENTS`: Search for backed-up assignment directories within course sources.
        - `Content.PROBLEMS`: Search for backed-up problem files (e.g., `.ipynb` notebooks) within course sources.

    Returns
    -------
    List[str]
        A sorted list of backed-up paths as strings. Paths are filtered to exclude directories or files
        that are hidden (i.e., starting with a dot) or are within hidden parent directories.
    """

    base_dir = Path(f'/var/lib/private/{user_name}')

    if content == Content.COURSES:
        backed_up_paths = [
            str(path).removesuffix('/')
            for path in base_dir.glob('*/')
            if path.is_dir() and not any(part.name.startswith('.') for part in path.parents) and not path.name.startswith('.')
        ]
    elif content == Content.ASSIGNMENTS:
        backed_up_paths = [
            str(assignment_path)
            for source_path in base_dir.glob('*/source/')
            if source_path.is_dir()
            for assignment_path in source_path.glob('*/')
            if assignment_path.is_dir() and not assignment_path.name.startswith('.')
        ]
    elif content == Content.PROBLEMS:
        backed_up_paths = [
            str(problem_path)
            for source_path in base_dir.glob('*/source/')
            if source_path.is_dir()
            for problem_path in source_path.rglob('*.ipynb')
            if problem_path.is_file() and not any(part.name.startswith('.') for part in problem_path.parents)
        ]
    else:
        raise ValueError(f'Invalid content type: {content}. Must be `Content.COURSES`, `Content.ASSIGNMENTS`, or `Content.PROBLEMS`.')

    return sorted(backed_up_paths)


def get_list(autogenerated_file_path: str, content: Content, subset: Subset = Subset.ALL) -> Response:
    """
    Retrieves and returns a list of active or all content (courses, assignments, or problems)
    for a given user, with appropriate error handling.

    Parameters
    ----------
    autogenerated_file_path : str
        The path to the autogenerated configuration file containing user group information.
    content : Content
        The type of content to be retrieved. Can be `Content.COURSES`, `Content.ASSIGNMENTS`, or `Content.PROBLEMS`.
    subset : Subset, optional
        Specifies whether to retrieve only active content (`Subset.ACTIVE`) or all content (`Subset.ALL`).
        Default is `Subset.ALL`.

    Returns
    -------
    Response
        A Flask `Response` object containing a JSON-formatted message with either the list of content
        paths and names or an error message. The status code of the response indicates success (200)
        or failure (500).
    """

    try:
        user_name = flask_request.args.get('user')
    except BadRequestKeyError:
        return Response(response=json.dumps({'message': 'BadRequestKeyError'}), status=500)

    # Access list of 'owned' groups, this is necessary to copy assignments stored at '/home/FORMGRADER_USER' and verifying access rights.
    try:
        _, _, groups = read_autogenerated_config(autogenerated_file_path=autogenerated_file_path)
    except AutogeneratedFileError:
        return Response(response=json.dumps({'message': 'AutogeneratedFileError'}), status=500)

    active_paths = get_active_paths(user_name=user_name, groups=groups, content=content, subset=subset)

    # Exit early if there are no active courses.
    if not active_paths:
        logging.error('No active courses found.')
        return Response(response=json.dumps({'message': 'NoActiveCoursesFoundError'}), status=500)

    if subset == Subset.ACTIVE or subset == Subset.CURRENT:
        try:
            unique_names = generate_unique_names(content=content, active_paths=active_paths)
        except (FileNotFoundError, PermissionError, CalledProcessError, OSError):
            return Response(response=json.dumps({'message': 'UniqueNamesError'}), status=500)

        content_list = {
            'message': f'List of {content.value} successfully retrieved.',
            'names': unique_names,
            'paths': active_paths
        }

        return Response(response=json.dumps(content_list), status=200)

    if subset == Subset.ALL:
        backed_up_paths = get_backed_up_paths(user_name=user_name, content=content)

        # Generate names to display in the dropdown menu of the kore extension.
        try:
            unique_names = generate_unique_names(content=content, active_paths=active_paths, backed_up_paths=backed_up_paths)
        except (FileNotFoundError, PermissionError, CalledProcessError, OSError):
            return Response(response=json.dumps({'message': 'UniqueNamesError'}), status=500)

        content_list = {
            'message': f'List of {content.value} successfully retrieved.',
            'names': unique_names,
            'paths': active_paths + backed_up_paths,
        }
        logging.info(f'Generated {content.value} list: {content_list}')

        return Response(response=json.dumps(content_list), status=200)


def generate_unique_names(content: Content, active_paths: List[str], backed_up_paths: Optional[List[str]] = None) -> List[str]:
    """
    Generates a list of unique names for the provided content based on active and backed-up paths.

    This function creates human-readable names for the content based on its type (courses, assignments, or problems).
    It handles both active and backed-up paths, ensuring that names are unique by appending counts to duplicates.

    Parameters
    ----------
    content : Content
        The type of content to generate names for. Can be `Content.COURSES`, `Content.ASSIGNMENTS`, or `Content.PROBLEMS`.
    active_paths : List[str]
        A list of paths for the active content. Each path should correspond to an existing directory or file.
    backed_up_paths : Optional[List[str]], optional
        A list of paths for the backed-up content. If provided, names for these paths will also be generated.
        Default is None.

    Returns
    -------
    List[str]
        A list of unique, human-readable names for the content. Names are formatted based on the content type and
        are ensured to be unique, with duplicates being distinguished by appending counts.
    """

    active_names = []
    for active_path in active_paths:
        user_name = active_path.split('/')[2]
        info_file_path = f'/home/{user_name}/course_data/info.json'
        try:
            info = load_info(info_file_path)
            title_short = info['title_short']
            if content == Content.COURSES:
                active_names.append(title_short)
            elif content == Content.ASSIGNMENTS:
                active_names.append(f"{active_path.removesuffix('/').split('/')[-1]} ({title_short})")
            elif content == Content.PROBLEMS:
                active_names.append(f"{active_path.removesuffix('.ipynb').split('/')[-1]} ({title_short}, {active_path.removesuffix('/').split('/')[-2]})")
            else:
                raise ValueError(f'Invalid content type: {content}. Must be `Content.COURSES`, `Content.ASSIGNMENTS`, or `Content.PROBLEMS`.')
        except (FileNotFoundError, PermissionError, CalledProcessError, OSError):
            raise

    backed_up_names = []
    if backed_up_paths:
        if content == Content.COURSES:
            backed_up_names = [f"{path.split('/')[-1]} (Backup)" for path in backed_up_paths]
        elif content == Content.ASSIGNMENTS:
            backed_up_names = [f"{path.split('/')[-1]} (Backup, {path.split('/')[-3]})" for path in backed_up_paths]
        elif content == Content.PROBLEMS:
            backed_up_names = [f"{path.removesuffix('.ipynb').split('/')[-1]} (Backup, {path.split('/')[-4]}, {path.split('/')[-2]})" for path in backed_up_paths]
        else:
            raise ValueError(f'Invalid content type: {content}. Must be `Content.COURSES`, `Content.ASSIGNMENTS`, or `Content.PROBLEMS`.')

    unique_names = []
    for content_names in [active_names, backed_up_names] if backed_up_paths else [active_names]:
        unique_array, unique_count = np.unique(content_names, return_counts=True)

        if not np.all(unique_count == 1):
            counts = dict(Counter[content_names])
            content_names = [key if i == 0 else key + f' ({i})' for key in unique_array for i in range(counts[key])]

        content_names = [name.replace('_', ' ') for name in content_names]
        unique_names.extend(content_names)

    logging.debug(f'Unique {content.value} names: {unique_names}')
    return unique_names
