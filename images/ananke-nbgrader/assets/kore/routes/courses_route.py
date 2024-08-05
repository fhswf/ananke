import json
import logging
import os
import time
from glob import glob
from subprocess import run, CalledProcessError

from flask import Response, Blueprint, current_app
from flask import request as flask_request
from nbgrader.api import Gradebook

from exceptions import AutogeneratedFileError
from misc.utils import get_hub_base_url, read_autogenerated_config, write_autogenerated_config, get_course_list
from models.lti_file_reader import LTIFileReader
from models.subset import Subset

courses_bp = Blueprint('courses', __name__)


# Defining subroute(s) for courses filtering. Available subroutes are:
# - active: Listing all active/running courses. Currently used for course backup, reset and deletion.
# TODO do i need a /courses/has-notebooks route?
@courses_bp.route('/courses/active', methods=['GET'])
def active_courses():
    config_loader = current_app.config['CONFIG_LOADER']
    autogenerated_file_path = config_loader.autogenerated_file_path

    if flask_request.method == 'GET':
        try:
            return get_course_list(autogenerated_file_path=autogenerated_file_path, subset=Subset.ACTIVE)
        except ValueError:
            return Response(response=json.dumps({'message': 'ValueError'}), status=500)


@courses_bp.route('/courses', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def courses():
    config_loader = current_app.config['CONFIG_LOADER']

    autogenerated_file_path = config_loader.autogenerated_file_path
    date_time_format = config_loader.date_time_format

    kore_token = current_app.config['KORE_TOKEN']

    if flask_request.method == 'GET':
        try:
            return get_course_list(autogenerated_file_path=autogenerated_file_path)
        except ValueError:
            return Response(response=json.dumps({'message': 'ValueError'}), status=500)

    if flask_request.method == 'POST':
        try:
            user_name, path = flask_request.json['user'], flask_request.json['path'].removesuffix('/')
            logging.debug(f'User: {user_name}')
            logging.debug(f'Path of course to be copied: {path}')

        except BadRequestKeyError:
        except KeyError:
            logging.error('Request key is not in form!')
            return Response(response=json.dumps({'message': 'BadRequestKeyError'}), status=500)
            return Response(response=json.dumps({'message': 'KeyError'}), status=500)

        logging.info(f'User {user_name} is copying course from {path}.')

        # Read and parse JSON file containing LTI data of current user.
        lti_file_reader: LTIFileReader = LTIFileReader(user_name=user_name, file_path=f'runtime/lti_{user_name}.json')
        lti_file_reader.read_file()
        lti_file_reader.extract_values()

        if lti_file_reader.read_success and lti_file_reader.parse_success:
            course_id, course_title, grader_user = lti_file_reader.course_id, lti_file_reader.course_title, lti_file_reader.grader_user
        else:
            return lti_file_reader.error_response

        # Generate list of assignments present in the course chosen.
        assignments = [assignment.removesuffix('/') for assignment in glob(pathname=f'{path}/*/') if glob(pathname=f'{assignment}/**/*.ipynb', recursive=True)]

        # Check if the .../source/ folder for the grader user is present otherwise create it.
        source_folder = f'/home/{grader_user}/course_data/source/'
        if not os.path.isdir(source_folder):
            try:
                logging.debug(f'Executing: mkdir -p {source_folder}')
                run(['mkdir', '-p', source_folder], check=True)

            except CalledProcessError:
                logging.error('Command cannot be executed!')
                return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        for assignment in assignments:
            # Get name of assignment to be copied.
            assignment_name = assignment.split('/')[-1]
            actual_time = time.strftime(date_time_format)
            logging.debug(f'Assignment name: {assignment_name}')
            logging.debug(f'Actual time: {actual_time}')

            # Copy assignment and change ownership.
            src = f'{assignment}/'
            dst = f'/home/{grader_user}/course_data/source/{assignment_name} ({actual_time})/'

            try:
                logging.debug(f'Executing: cp -r {src} {dst}')
                run(['cp', '-r', src, dst], check=True)
                logging.debug(f'Executing: chown -R {grader_user}:{grader_user} {dst}')
                run(['chown', '-R', f'{grader_user}:{grader_user}', dst], check=True)

            except CalledProcessError:
                logging.error('Command cannot be executed!')
                return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        return Response(response=json.dumps({'message': 'Selected course copied successfully! \n'
                                                        'Please refresh the webpage (Formgrader) to see the imported course.'}), status=200)

    # Backup a course.
    if flask_request.method == 'PUT':
        try:
            user_name, src, name = flask_request.json['user'], flask_request.json['path'].removesuffix('/'), flask_request.json['name']
        except KeyError:
            logging.error('Request key is not in form!')
            return Response(response=json.dumps({'message': 'KeyError'}), status=500)

        logging.info(f'User {user_name} is backing up course ({src}).')

        actual_date_time = time.strftime(date_time_format)
        dst = f'/var/lib/private/{user_name}/{name}_{actual_date_time}/'

        # TODO should the gradebook be copied?
        try:
            run(['cp', '-r', src, dst], check=True)
            run(['chown', '-R', f'{user_name}:{user_name}', dst], check=True)
        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        return Response(response=json.dumps({'message': 'Selected course backed up successfully!'}), status=200)

    if flask_request.method == 'PATCH':
        try:
            user_name = flask_request.json['user']
            logging.debug(f'User: {user_name}')

        except KeyError:
            logging.error('Request key is not in form!')
            return Response(response=json.dumps({'message': 'KeyError'}), status=500)

        logging.info(f'User {user_name} is resetting current course.')

        # Read and parse JSON file containing LTI data of current user.
        lti_file_reader: LTIFileReader = LTIFileReader(user_name=user_name, file_path=f'runtime/lti_{user_name}.json')
        lti_file_reader.read_file()
        lti_file_reader.extract_values()

        if lti_file_reader.read_success and lti_file_reader.parse_success:
            lti_state = lti_file_reader.lti_state
            course_id, course_title, grader_user = lti_file_reader.course_id, lti_file_reader.course_title, lti_file_reader.grader_user
        else:
            return lti_file_reader.error_response

        # Remove students from gradebook.
        with Gradebook(f'sqlite:////home/{grader_user}/course_data/gradebook.db') as gb:
            usernames = [student.id for student in gb.students]
            for username in usernames:
                gb.remove_student(username)

        # Remove students from courses nbgrader group.
        base_url = get_hub_base_url(lti_state)
        logging.debug(f'Removing all students from nbgrader group of course {course_id}.')
        # TODO add check=True
        # TODO add a custom error?
        run(['systemd-run', 'curl',
             '-H', 'Content-Type: application/json',
             '-H', 'Accept: application/json',
             '-H', f'Authorization: token {kore_token}',
             '-X', 'DELETE',
             '-d', '{"users":' + json.dumps(usernames) + '}',
             f'http://127.0.0.1:8081/{base_url}hub/api/groups/nbgrader-{course_id}/users'])

        # Clean up the nbgrader exchange directory.
        try:
            logging.debug(f'Executing: rm -rf /opt/nbgrader_exchange/{course_id}/')
            run(['rm', '-rf', f'/opt/nbgrader_exchange/{course_id}/'], check=True)

        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        # Clean up course directory.
        try:
            logging.debug(f'Executing: rm /home/{grader_user}/course_data/gradebook.db')
            run(['rm', f'/home/{grader_user}/course_data/gradebook.db'], check=True)

        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        for directory in ['autograded', 'feedback', 'release', 'submitted']:
            try:
                logging.debug(f'Executing: rm -rf /home/{grader_user}/course_data/{directory}/')
                run(['rm', '-rf', f'/home/{grader_user}/course_data/{directory}/'], check=True)

            except CalledProcessError:
                logging.error('Command cannot be executed!')
                return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        return Response(response=json.dumps({'message': 'Selected course reset successfully!'}), status=200)

    # TODO: Change code so that deletion of course is done by a list of available courses where the user has permissions for.
    #  This will make it possible to delete courses where the corresponding course on LMS side was deleted already.
    if flask_request.method == 'DELETE':
        try:
            user_name = flask_request.json['user']
            logging.debug(f'User: {user_name}')
        except KeyError:
            logging.error('Request key is not in form!')
            return Response(response=json.dumps({'message': 'KeyError'}), status=500)

        logging.info(f'User {user_name} is deleting current course.')

        # Read and parse JSON file containing LTI data of current user.
        lti_file_reader: LTIFileReader = LTIFileReader(user_name=user_name, file_path=f'runtime/lti_{user_name}.json')
        lti_file_reader.read_file()
        lti_file_reader.extract_values()

        if lti_file_reader.read_success and lti_file_reader.parse_success:
            course_id, course_title, grader_user = lti_file_reader.course_id, lti_file_reader.course_title, lti_file_reader.grader_user
        else:
            return lti_file_reader.error_response

        # Get user's courses and corresponding information.
        try:
            services, roles, groups = read_autogenerated_config(autogenerated_file_path=autogenerated_file_path)
        except AutogeneratedFileError:
            return Response(response=json.dumps({'message': 'AutogeneratedFileError'}), status=500)

        # Access group and delete it from groups list.
        group = groups.get(f'formgrade-{course_id}')
        if not group:
            logging.error('Group not found in autogenerated configuration file!')
            return Response(response=json.dumps({'message': 'GroupNotFoundError'}), status=500)

        del groups[f'formgrade-{course_id}']
        logging.debug(f'Removed group for course {course_id}!')

        # Delete roles from roles lists.
        for role in roles:
            if role.get('name') == f'formgrader-{course_id}-role':
                del roles[roles.index(role)]
                logging.debug(f'Removed role for course {course_id}!')
            if role.get('name') == 'formgrader-service-role':
                del role['services'][role['services'].index(course_id)]

        # Delete services from services list.
        for service in services:
            if service['name'] == course_id:
                del services[services.index(service)]
                logging.debug(f'Removed service {course_id}!')
                break

        # Write resulting configuration file.
        try:
            write_autogenerated_config(autogenerated_file_path=autogenerated_file_path, services=services, roles=roles, groups=groups)
        except AutogeneratedFileError:
            return Response(response=json.dumps({'message': 'AutogeneratedFileError'}), status=500)

        # Delete nbgrader exchange directory for course.
        try:
            logging.debug(f'Removing nbgrader exchange for course {course_id}!')
            run(['rm', '-rf', f'/opt/nbgrader_exchange/{course_id}/'], check=True)
        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        # Delete grader user for course.
        try:
            logging.debug(f'Removing grader user for course {course_id}!')
            run(['userdel', f'{grader_user}'], check=True)
            run(['rm', '-rf', f'/home/{grader_user}/'], check=True)
        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        # Generate new nbgrader configuration code and write it to file.
        with open(file='/opt/conda/envs/jhub/etc/jupyter/nbgrader_config.py') as nb_grader_config:
            content = nb_grader_config.read()
        start = content.find('c.NbGrader.course_titles')
        end = content.find('}', start)
        pre = content[:start]
        code = content[start:end + 1]
        post = content[end + 1:]
        code = code.replace('c.NbGrader.course_titles = ', 'mapping.update(')
        code = code.replace('}', '})')
        mapping = {}
        exec(code + '\n')

        if course_id in mapping.keys():
            del mapping[course_id]

        with open(file='/opt/conda/envs/jhub/etc/jupyter/nbgrader_config.py', mode='w') as nb_grader_config:
            nb_grader_config.write(pre)
            nb_grader_config.write(f'c.NbGrader.course_titles = {str(mapping)}')
            nb_grader_config.write(post)

        # Restart JupyterHub to adopt the changes.
        logging.info('Restarting JupyterHub in 3 seconds...')
        run(['systemd-run', '--on-active=3', 'systemctl', 'restart', 'jupyterhub'])

        return Response(response=json.dumps({'message': 'Selected course deleted successfully! JupyterHub will restart soon!'}), status=200)
