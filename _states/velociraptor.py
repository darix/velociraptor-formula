import json
import grpc
import time
from enum import Enum
import pyvelociraptor
from pyvelociraptor import api_pb2
from pyvelociraptor import api_pb2_grpc
import logging
import subprocess
import os
import pwd
from salt.exceptions import SaltConfigurationError, SaltRenderError

log = logging.getLogger(__name__)

#
# ARTIFACTS CONFIGURATION
#
class DiffStatus(Enum):
    EQUAL = 0
    DIFFERENT = 1
    ERROR = 2

apiconfig = ""

def get_velo_server_artifacts ():
    out = run_velo_query('SELECT get_server_monitoring() FROM scope()')
    if len(out) > 0 and len(out[0]) > 0:
        return out[0][0]['get_server_monitoring()']
    else:
        log.error("not able to retrieve server artifacts")
        return None

def get_velo_client_artifacts ():
    out = run_velo_query('SELECT get_client_monitoring() FROM scope()')
    if len(out) > 0 and len(out[0]) > 0:
        return out[0][0]['get_client_monitoring()']['artifacts']
    else:
        log.error("not able to retrieve client artifacts")
        return None

def add_velo_server_artifact (artifact, params):
    query='SELECT add_server_monitoring(artifact="'
    query += artifact + '", parameters=dict('
    if params is not None:
        if 'Artifacts' in params:
          params['Artifacts'] = 'Artifact\n' + '\n'.join(params['Artifacts']) + '\n'

        query += ', '.join(f'{key}="{value}"' for key, value in params.items())
    query += ')) FROM scope()'

    out = run_velo_query(query)

    if not out or 'None' in out:
        log.error(f"error while adding {artifact}")
        return False
    else:
        return True

def add_velo_client_artifact (artifact, params):
    query = 'SELECT add_client_monitoring(artifact="'
    query += artifact + '", parameters=dict('
    if params is not None:
        query += ', '.join(f'{key}="{value}"' for key, value in params.items())
    query += ')) FROM scope()'

    out = run_velo_query(query)

    if not out or 'None' in out:
        log.error(f"error while adding {artifact}")
        return False
    else:
        return True

def del_velo_server_artifact (artifact):
    query = 'SELECT rm_server_monitoring(artifact="'
    query += artifact + '") FROM scope()'

    out = run_velo_query(query)

    if not out or 'None' in out:
        log.error(f"error while deleting {artifact}")
        return False
    else:
        return True

def del_velo_client_artifact (artifact):
    query = 'SELECT rm_client_monitoring(artifact="'
    query += artifact + '") FROM scope()'

    out = run_velo_query(query)

    if not out or 'None' in out:
        log.error(f"error while deleting {artifact}")
        return False
    else:
        return True

def apply_artifacts (is_srv, diff, artifacts):
    ret = False

    if is_srv:
        add_artifact='add_velo_server_artifact'
        del_artifact='del_velo_server_artifact'
    else:
        add_artifact='add_velo_client_artifact'
        del_artifact='del_velo_client_artifact'


    for art in diff['toadd']:
        if globals()[add_artifact](art, artifacts[art]) == False:
            log.error(f"unable to add artifact {art}")
            return ret
        else:
            log.info(f"added artifact {art}")

    for art in diff['toupdate']:
        if globals()[del_artifact](art) == False:
            log.error(f"unable to delete artifact {art}")
            return ret
        else:
            log.info(f"deleted artifact {art}")

        if globals()[add_artifact](art, artifacts[art]) == False:
            log.error(f"unable to add artifact {art}")
            return ret
        else:
            log.info(f"added artifact {art}")

    for art in diff['todelete']:
        if globals()[del_artifact](art) == False:
            log.error(f"unable to delete artifact {art}")
            return ret
        else:
            log.info(f"deleted artifact {art}")

    ret = True
    return ret

def diff_artifacts_params (artifact, current_params, desired_params):
    ret = DiffStatus.ERROR

    if current_params is None:
        log.error("artifact {artifact} params not found")
        return ret
    else:
        for current_param in current_params:
            current_key = current_param['key']
            current_value = current_param['value']
            desired_value = next((value for key, value in desired_params.items() if key == current_key), None)

            if desired_value is None:
                log.error(f"parameter {current_key} not found for artifact {artifact}")
                return ret
            else:
                if current_key == "Artifacts":
                    desired_value = 'Artifact\n' + '\n'.join(desired_value) + '\n'
                if str(desired_value) != str(current_value):
                    log.info(f"{artifact} - {current_key} param desired {desired_value} != current {current_value}")
                    return DiffStatus.DIFFERENT
                else:
                    continue

    return DiffStatus.EQUAL

def diff_artifacts (current_artifacts, desired_artifacts):
    skip_artifacts=['Server.Monitor.Health', 'Generic.Client.Stats']

    ret = {'status': 1, 'toadd': [], 'todelete': [], 'toupdate': [], "toskip": []}

    desired_artifacts_only_name = list(desired_artifacts.keys())

    for curr_art in current_artifacts['artifacts']:
        if curr_art in skip_artifacts:
            log.info(f"{curr_art} will be skipped")
            ret['toskip'].append(curr_art)
            continue
        elif curr_art not in desired_artifacts:
            log.info(f"{curr_art} will be deleted")
            ret['todelete'].append(curr_art)
        else:
            # check diffs in parameters
            current_params=next((item['parameters'] for item in current_artifacts['specs'] if item['artifact'] == curr_art), None)
            if current_params.get('env') is not None:
                current_params=current_params['env']
            else:
                current_params = None

            if current_params is not None:
                desired_params=desired_artifacts[curr_art]
                diff_ret = diff_artifacts_params(curr_art, current_params, desired_params)
                if diff_ret == DiffStatus.DIFFERENT:
                    log.info(f"{curr_art} will be updated")
                    ret['toupdate'].append(curr_art)
                elif diff_ret == DiffStatus.EQUAL:
                    log.debug(f"{curr_art}: no update needed: artifact matches desired state.")
                    ret['toskip'].append(curr_art)
                else:
                    return ret
            else:
                log.debug(f"{curr_art}: no update needed (no params)")
                ret['toskip'].append(curr_art)

    for desired_artifact in desired_artifacts:
        if (desired_artifact not in ret['todelete'] and
           desired_artifact not in ret['toupdate'] and
           desired_artifact not in ret['toskip']):
            log.info(f"{desired_artifact} will be added")
            ret['toadd'].append(desired_artifact)

    ret['status'] = 0

    return ret

def run_velo_query (query, timeout=0):
    #configfile="/etc/salt/api.config.yaml"
    if not os.path.exists(apiconfig):
        raise SaltConfigurationError()

    config = pyvelociraptor.LoadConfigFile(apiconfig)
    ret = []

    creds = grpc.ssl_channel_credentials(
        root_certificates=config["ca_certificate"].encode("utf8"),
        private_key=config["client_private_key"].encode("utf8"),
        certificate_chain=config["client_cert"].encode("utf8"))

    options = (('grpc.ssl_target_name_override', "VelociraptorServer",),)

    env = []
    org_id = None

    with grpc.secure_channel(config["api_connection_string"],
                             creds, options) as channel:
        stub = api_pb2_grpc.APIStub(channel)

        request = api_pb2.VQLCollectorArgs(
            org_id=org_id,
            max_wait=1,
            max_row=100,
            timeout=timeout,
            Query=[api_pb2.VQLRequest(
                Name="Test",
                VQL=query,
            )],
            env=env,
        )

        for response in stub.Query(request):
            if response.Response:
                package = json.loads(response.Response)
                ret.append(package)

            elif response.log:
                print ("%s: %s" % (time.ctime(response.timestamp / 1000000), response.log))

    return ret

def artifacts_configured(name, _apiconfig):
    global apiconfig
    ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}

    log.debug("VR-ARTIFACTS")

    apiconfig = _apiconfig

    pillar_artifacts = __pillar__["velociraptor"]["server"]["artifacts"]
    #log.info(pillar_artifacts)

    if "server" in pillar_artifacts:
        current_srv_artifacts = get_velo_server_artifacts()
        if current_srv_artifacts is None:
            message = "not able to get velociraptor server artifacts"
            raise SaltRenderError(message)
        srv_diff = diff_artifacts(current_srv_artifacts, pillar_artifacts["server"])

        if not __opts__["test"]:
            if apply_artifacts(True, srv_diff, pillar_artifacts["server"]) == False:
                ret['result'] = False
                ret['comment'] = "error while applying server artifacts"
                return ret

        if srv_diff["toadd"] or srv_diff["todelete"] or srv_diff["toupdate"]:
            ret['changes'].update({"server_diff": {"added": srv_diff["toadd"], "deleted": srv_diff["todelete"], "updated": srv_diff["toupdate"]}})

    if "client" in pillar_artifacts:
        current_client_artifacts = get_velo_client_artifacts()
        if current_client_artifacts is None:
            message = "not able to get velociraptor client artifacts"
            raise SaltRenderError(message)
        client_diff = diff_artifacts(current_client_artifacts, pillar_artifacts["client"])

        if not __opts__["test"]:
            if apply_artifacts(False, client_diff, pillar_artifacts["client"]) == False:
                ret['result'] = False
                ret['comment'] = "error while applying client artifacts"
                return ret

        if client_diff["toadd"] or client_diff["todelete"] or client_diff["toupdate"]:
            ret['changes'].update({"client_diff": {"added": client_diff["toadd"], "deleted": client_diff["todelete"], "updated": client_diff["toupdate"]}})

    ret['result'] = True

    return ret

##
## APICONFIG / USER CREATION
##

def velocmd (server_config, cmd):
    _cmd = ["velociraptor", "--config", server_config]
    _cmd.extend(cmd)

    log.debug(f"**** {_cmd}")
    result = subprocess.run(_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        text=True)# user="velociraptor"
    return result

def diff_grants(server_config, username, desired_grants):
    ret = {"error": True, "diff": False, "current_grants": []}

    result = velocmd(server_config, ["acl", "show", username])
    if result.returncode != 0:
        log.error(f"error while retrieving user {username} grants")
        raise SaltRenderError(f"error while retrieving user {username} grants: {result.stderr}")

    try:
        current_grants = json.loads(result.stdout)
        ret["error"] = False

        # quirk: acl show returns {"roles":["api"]} with no grants
        if "roles" in current_grants.keys():
            ret["current_grants"] = []
            ret["diff"] = True
            return ret
        else:
            ret["current_grants"] = list(current_grants.keys())

        for current_grant in current_grants.keys():
            if current_grant not in desired_grants:
                ret["diff"] = True
                return ret

        for desired_grant in desired_grants:
            if desired_grant not in current_grants.keys():
                ret["diff"] = True
                return ret
    except json.JSONDecodeError as e:
        raise SaltRenderError("error parsing grants json:", e)

    return ret

def create_api_user (name, server_config, api_config):
    # todo: manage change in role
    # todo: manage change of username

    ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}
    different_grants = False

    log.debug("VR-APIUSER")

    try:
        users_settings = __pillar__["velociraptor"]["server"]["users"]
        users_config = __pillar__["velociraptor"]["server"]["users_config"]
    except KeyError:
        raise SaltConfigurationError("users configuration missing in velociraptor server")

    for user, settings in users_settings.items():
        if "role" not in settings:
            raise SaltConfigurationError("user has not role set in the pillar")

        role = settings['role']
        api_config_exists = os.path.exists(api_config)
        user_exists = False
        new_user = False

        result = velocmd(server_config, ["user", "show", user])
        if result.returncode == 0:
            ret['result'] = True
            user_exists = True
        else:
            if "User not found" in result.stderr:
                log.info(f"user {user} does not exists")
                user_exists = False
                if __opts__["test"]:
                    ret['changes'].setdefault(user, {})
                    ret['changes'][user]['add_user'] = True

        if not user_exists:
            if not __opts__["test"]:
                # clean user files just in case of wrong permissions
                if os.path.exists(users_config["aclpath"] + user + ".json.db"):
                    os.remove(users_config["userspath"] + user + ".db")
                if os.path.exists(users_config["aclpath"] + user + ".json.db"):
                    os.remove(users_config["aclpath"] + user + ".json.db")

                if role == 'api' or not api_config_exists:
                    log.info(f"user {user} not yet exist or apiconfig does not exists, creating ...")
                    result = velocmd(server_config, ["config", "api_client", "--name", user, "--role", role, api_config])
                else:
                    if "password" not in settings:
                        raise SaltConfigurationError("user password not set")
                    
                    password = settings["password"]
                    log.info(f"user {user} not yet exist, creating ...")
                    result = velocmd(server_config, ["user", "add", "--role", role, user, password])

                if result.returncode != 0:
                    ret['result'] = False
                    ret['comment'] = f"error while creating user {user}"
                    return ret

                new_user = True
                ret['changes'].setdefault(user, {})
                ret['changes'][user]['role'] = role
                log.info(f"user {user} properly created ...")

        if role == 'api' and not api_config_exists:
            ret['changes']['add_apiconfig'] = True
            log.info("apiconfig does not exists")

        if "grants" in settings and settings["grants"] and not __opts__["test"]:
            grants = settings["grants"]
            diff = diff_grants(server_config, user, grants)
            if diff["error"]:
                log.error(f"error while diffing grants")
                return ret
            else:
                if diff["diff"]:
                    different_grants = True
                    ret['changes'].setdefault(user, {})
                    ret['changes'][user]['desired_grants'] = grants
                    ret['changes'][user]['current_grants'] = diff["current_grants"]

                    # clean grants
                    result = velocmd(server_config, ["acl", "grant", user, "{}"])
                    if result.returncode != 0:
                        log.error("error while cleaning grants")
                        ret['result'] = False
                        ret['comment'] = f"error while cleaning grants"
                        return ret

                    # adapt to format required by velociraptor tool
                    grants = {key: True for key in grants}
                    grants = json.dumps(grants)

                    result = velocmd(server_config, ["acl", "grant", user, grants])

                    if result.returncode != 0:
                        ret['result'] = False
                        ret['comment'] = f"error while adding {grants} to user {user}"
                        return ret

                    log.info(f"grants {grants} properly added to user {user}")
            if new_user:
                #fix permissions
                user_info = pwd.getpwnam(users_config["fileowner"])
                uid = user_info.pw_uid
                gid = user_info.pw_gid
                os.chown(users_config["userspath"] + user + ".db", uid, gid)
                os.chown(users_config["aclpath"] + user + ".json.db", uid, gid)
    return ret
