import json
import logging
import time
from pathlib import Path
from subprocess import run, CalledProcessError

from flask import Blueprint, Response, current_app
from flask import request as flask_request

from misc.utils import get_list, load_info
from models.enums import Content

assignments_bp = Blueprint('assignments', __name__)


@assignments_bp.route('/assignments', methods=['GET', 'POST'])
def assignments():
    config_loader = current_app.config['CONFIG_LOADER']

    autogenerated_file_path = config_loader.autogenerated_file_path
    date_time_format = config_loader.date_time_format

    # Retrieve full assignment list (active and backed up ones).
    if flask_request.method == 'GET':
        try:
            return get_list(autogenerated_file_path=autogenerated_file_path, content=Content.ASSIGNMENTS)
        except ValueError:
            return Response(response=json.dumps({'message': 'ValueError'}), status=500)

    # Copy an assignment.
    if flask_request.method == 'POST':
        try:
            src = flask_request.json['fromPath'].removesuffix('/')
            dst = flask_request.json['toPath'].removesuffix('/')
            dst = f'{dst}/source/'
        except KeyError:
            logging.error('Request key is not in form!')
            return Response(response=json.dumps({'message': 'KeyError'}), status=500)

        info = load_info(f'{Path(src).parents[1]}/info.json')
        grader_user = info['grader_user']

        try:
            tmp = f'{src}_{time.strftime(date_time_format)}'
            run(['cp', '-r', src, tmp], check=True)
            run(['mkdir', '-p', dst], check=True)
            run(['mv', tmp, dst], check=True)
            run(['chown', '-R', f'{grader_user}:{grader_user}', dst], check=True)
        except CalledProcessError:
            logging.error('Command cannot be executed!')
            return Response(response=json.dumps({'message': 'CalledProcessError'}), status=500)

        return Response(response=json.dumps({'message': 'Selected assignment copied successfully! \n'
                                                        'Please refresh the webpage (Formgrader) to see the imported assignment.'}), status=200)
