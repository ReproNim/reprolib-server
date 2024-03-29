from sanic import Sanic
from sanic import response
from sanic.log import logger
from pyld import jsonld
from sanic_jinja2 import SanicJinja2
from difflib import get_close_matches
import requests
import json
import re
import os, sys
from sanic_cors import CORS

production = 'DEV8dac6d02a913' not in os.environ
basedir = '/vagrant'
basedir = basedir if production else os.getcwd()
logdir = os.path.join(basedir, "reprolib")
if not os.path.exists(logdir):
    os.makedirs(logdir, exist_ok=True)

LOG_SETTINGS = dict(
    version=1,
    disable_existing_loggers=False,
    loggers={
        "sanic.root": {"level": "INFO", "handlers": ["console", "consolefile"]},
        "sanic.error": {
            "level": "INFO",
            "handlers": ["error_console", "error_consolefile"],
            "propagate": True,
            "qualname": "sanic.error",
        },
        "sanic.access": {
            "level": "INFO",
            "handlers": ["access_console", "access_consolefile"],
            "propagate": True,
            "qualname": "sanic.access",
        },
    },
    handlers={
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": sys.stdout,
        },
        "error_console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": sys.stderr,
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": sys.stdout,
        },
        "consolefile": {
            'class': 'logging.FileHandler',
            'filename': os.path.join(logdir, "console.log"),
            "formatter": "generic",
        },
        "error_consolefile": {
            'class': 'logging.FileHandler',
            'filename': os.path.join(logdir, "error.log"),
            "formatter": "generic",
        },
        "access_consolefile": {
            'class': 'logging.FileHandler',
            'filename': os.path.join(logdir, "access.log"),
            "formatter": "access",
        },
    },
    formatters={
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter",
        },
        "access": {
            "format": "%(asctime)s - (%(name)s)[%(levelname)s][%(host)s]: "
                      + "%(request)s %(message)s %(status)d %(byte)d",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter",
        },
    },
)

app = Sanic(log_config=LOG_SETTINGS)
CORS(app)

jinja = SanicJinja2(app)
item_resp = {}
activity_map = {}
activityPrefLabel_map = {}
protocolPrefLabel_map = {}

async def replace_url(file_content, request):
    gh_url = "https://raw.githubusercontent.com/ReproNim/reproschema/master"
    hostname = await determine_env(request.headers['host'])
    for attribute, value in file_content.items():
        # if value is str, replace substring
        if isinstance(value, str) and gh_url in value:
            value = value.replace(gh_url, 'https://' + hostname)
            # print(107, attribute, '-', value)
            file_content[attribute] = value
        # if value is list, replace substring in list of strings
        if isinstance(value, list):
            new_list = []
            is_present = False
            for c in value:
                if gh_url in c:
                    is_present = True
                    c = c.replace(gh_url, 'https://' + hostname)
                    new_list.append(c)
            if is_present:
                file_content[attribute] = new_list
            else:
                file_content[attribute] = value

        # if value is dict, repeat process
        if isinstance(value, dict):
            file_content[attribute] = await replace_url(value, request)
    return file_content


async def determine_env(hostname):
    if '0.0.0.0' in hostname:
        return hostname
    else:
        return hostname + '/rl'


@app.route("/update")
def update(request):
    import subprocess as sp
    out = sp.run(['git', 'pull'], cwd='/opt/reproschema', capture_output=True)
    if out.returncode == 0:
        logger.info(out)
    else:
        logger.error(out)
    return response.json(out.__dict__, ensure_ascii=False, escape_forward_slashes=False)


@app.route("/")
async def test(request):
    hostname = await determine_env(request.headers['host'])
    api_list = {'activities': [], 'protocols': []}
    for activity in next(os.walk('/opt/reproschema-library/activities'))[1]:
        act_walks = next(os.walk('/opt/reproschema-library/activities/' + activity))
        activityAlphaNum = re.sub('[^A-Za-z0-9]+', '', activity)  # keep only alphanumeric characters
        for file in act_walks[2]:  # loop over all files in the activity directory
            if file.endswith('_schema') and (file == activity+'_schema' or file == activity.lower()+'_schema' or file == activityAlphaNum+'_schema'):
                with open(os.path.join(act_walks[0], file), "r") as fa:
                    try:
                        act_schema = json.load(fa)
                        if 'prefLabel' in act_schema:
                            if isinstance(act_schema['prefLabel'], str):
                                activityPrefLabel_map[activity] = act_schema['prefLabel']
                            else:
                                activityPrefLabel_map[activity] = act_schema['prefLabel']['en']
                        else: activityPrefLabel_map[activity] = act_schema['prefLabel']
                    except Exception as e:
                        print(153, 'error ---', file, e)
                        # logger.error('error in json', file, e)
        if activity in activityPrefLabel_map:
            prefLabel = activityPrefLabel_map[activity]
        else: prefLabel = activity
        act_dict = {
            'name': prefLabel,
            'html_path': 'https://' + hostname + '/activities/' +
                         activity,
            'jsonld_path': 'https://' + hostname + '/activities/' +
                        activity + '.jsonld',
            'ttl_path': 'https://' + hostname + '/activities/' +
                        activity + '.ttl',
            'ui': 'https://schema.repronim.org/ui/#/activities/0/?url='+'https://' + hostname + '/activities/' + activity
        }

        api_list['activities'].append(act_dict)

    # sort in place alphabetically
    api_list['activities'].sort(key=lambda i: i['name'].lower())

    # for protocol in next(os.walk('/opt/reproschema-library/protocols'))[1]:
    #     protocol_walks = next(os.walk('/opt/reproschema-library/protocols/' + protocol))
    #     protocolAlphaNum = re.sub('[^A-Za-z0-9]+', '', protocol)  # keep only alphanumeric characters
    #     for file in protocol_walks[2]:  # loop over all files in the protocol directory
    #         if file.endswith('_schema') and (
    #                 file == protocol + '_schema' or file == protocol.lower() + '_schema' or file == protocolAlphaNum + '_schema'):
    #             with open(os.path.join(protocol_walks[0], file), "r") as fp:
    #                 try:
    #                     protocol_schema = json.load(fp)
    #                     protocolPrefLabel_map[protocol] = protocol_schema['skos:prefLabel']
    #                 except Exception as e:
    #                     print(181, 'error', file, e)
    #                     # logger.error('error in json', file, e)
    #     if protocol in protocolPrefLabel_map:
    #         protocol_pref_label = protocolPrefLabel_map[protocol]
    #     else:
    #         protocol_pref_label = protocol
    #
    #     protocol_dict = {
    #         'name': protocol_pref_label,
    #         'html_path': 'https://' + hostname + '/protocols/' +
    #                      protocol,
    #         'jsonld_path': 'https://' + hostname + '/protocols/' +
    #                      protocol + '.jsonld',
    #         'ttl_path': 'https://' + hostname + '/protocols/' +
    #                      protocol + '.jsonld',
    #         'ui': 'https://schema.repronim.org/ui/#/?url='+'https://' + hostname + '/protocols/' + protocol
    #     }
    #     api_list['protocols'].append(protocol_dict)
    # # sort in place alphabetically
    # api_list['protocols'].sort(key=lambda i: i['name'].lower())
    return jinja.render("index.html", request, data=api_list)


@app.route('/contexts/generic')
async def get_generic_context(request):
    response_headers = {'Content-type': 'application/ld+json'}
    with open("/opt/reproschema/contexts/generic", "r") as f1:
        file_content = json.load(f1)
    new_file = await replace_url(file_content, request)
    return response.json(new_file, ensure_ascii=False,
                         escape_forward_slashes=False, headers=response_headers)


@app.route('/activities/<act_name>/items/<item_id>')
async def get_item(request, act_name, item_id):
    view_options = 2  # default view is jsonld
    response_headers = {'Content-type': 'application/ld+json'}
    filename, file_extension = os.path.splitext(item_id)
    if not file_extension:
        file_extension = '.jsonld'
    if request.headers.get('accept') == 'application/json' or \
            request.headers.get('accept') == 'application/ld+json':
        view_options = 2
    else:
        # if not file_extension:
        #     view_options = 1  # html view
        if file_extension == '.jsonld':
            view_options = 2
    try:
        with open("/opt/reproschema-library/activities/" + act_name
                  + '/items/' + filename, "r") as f2:
            file_content = json.load(f2)
            # print(178, file_content)
            new_file = await replace_url(file_content, request)
    except:
        print('error getting contents')
        return response.text('Could not fetch data. Check item name')

    # if view_options == 1:
    #     # render html
    #     return jinja.render("field.html", request, data=new_file)

    if view_options == 2:
        return response.json(new_file, ensure_ascii=False,
                             escape_forward_slashes=False, headers=response_headers)


@app.route('/activities/<act_name>')
async def get_activity(request, act_name):
    hostname = await determine_env(request.headers['host'])
    filename, file_extension = os.path.splitext(act_name)
    if not file_extension:
        file_extension = '.jsonld'
    for activity in next(os.walk('/opt/reproschema-library/activities'))[1]:
        act_walks = next(os.walk('/opt/reproschema-library/activities/' + activity))

        for file in act_walks[2]: # loop over all files in the activity directory
            if file.endswith('_schema'):
                # print(150, file, os.path.join(act_walks[0], file))
                with open(os.path.join(act_walks[0], file), "r") as fa:
                    try:
                        act_schema = json.load(fa)
                        # print(155, act_schema['@id'])
                        activity_map[act_schema['@id']] = os.path.join(act_walks[0], file)
                    except Exception as e:
                        logger.error('error in json', file, e)
    matched_id = get_close_matches(filename, list(activity_map.keys()), 3, 0.2)[0]
    # print(269, activity_map[matched_id]) # returns path of matched file id

    with open(activity_map[matched_id], "r") as f5:
        try:
            file_content = json.load(f5)
            new_file = await replace_url(file_content, request)
        except ValueError:
            print('error!!')

    view_options = 2  # default view is html
    response_headers = {'Content-type': 'application/ld+json'}

    if 'application/json' in request.headers.get('accept') or \
            'application/ld+json' in request.headers.get('accept'):
        view_options = 2
    else:
        # if not file_extension:
        #     #view_options = 1 # html view
        #     file_extension = '.jsonld'
        if file_extension == '.jsonld':
            view_options = 2
        elif file_extension == '.ttl':
            view_options = 3

    if view_options == 2:
        # print('in json ')
        # jsonld
        return response.json(new_file, ensure_ascii=False,
                             escape_forward_slashes=False, headers=response_headers)

    elif view_options == 3:
        try:
            #print('in turtle ', new_file)
            # turtle
            normalized_file = jsonld.normalize(
                new_file, {'base': 'https://' + hostname + '/activities/' + filename + '/', 'algorithm': 'URDNA2015', 'format':
                    'application/n-quads'})
            return response.text(normalized_file, headers=response_headers)
        except Exception as e:
            print(e)
            raise


@app.route('/terms/<term_name>')
async def get_terms(request, term_name):
    # view_options = 1  # default view is html
    view_options = 2  # make jsonld default for now
    response_headers = {'Content-type': 'application/ld+json'}
    filename, file_extension = os.path.splitext(term_name)
    if not file_extension:
        file_extension = '.jsonld'
    if request.headers.get('accept') == 'application/json' or \
            request.headers.get('accept') == 'application/ld+json':
        view_options = 2
    else:
        # if not file_extension:
        #     view_options = 1  # html view
        if file_extension == '.jsonld':
            view_options = 2
    with open("/opt/reproschema/terms/" + filename, "r") as f1:
        file_content = json.load(f1)
    new_file = await replace_url(file_content, request)

    if view_options == 2:
        # jsonld
        return response.json(new_file, ensure_ascii=False,
                             escape_forward_slashes=False, headers=response_headers)

    # if view_options == 1:
    #     # html. for time being it renders jsonld
    #     try:
    #         # TODO
    #         return jinja.render("field.html", request, data=new_file)
    #     except Exception as e:
    #         logger.error(e)
    #         # if it raises an Exception then deliver the jsonld
    #         return response.json(new_file, ensure_ascii=False,
    #                              escape_forward_slashes=False,
    #                              headers=response_headers)


@app.route('/resources/<r_name>')
async def get_resources(request, r_name):
    response_headers = {'Content-type': 'application/ld+json'}
    with open("/opt/reproschema/resources/" + r_name, "r") as f1:
        file_content = json.load(f1)
        return response.json(file_content, ensure_ascii=False,
                         escape_forward_slashes=False, headers=response_headers)

if __name__ == "__main__":
    logger.info("Starting reprolib-server")
    app.run(host="0.0.0.0", port=8000)

