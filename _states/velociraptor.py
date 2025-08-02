import json
import grpc
import time
import yaml
from enum import Enum
import pyvelociraptor
from pyvelociraptor import api_pb2
from pyvelociraptor import api_pb2_grpc
import logging

class DiffStatus(Enum):
    EQUAL = 0
    DIFFERENT = 1
    ERROR = 2


log = logging.getLogger(__name__)
apiconfig = ""

def get_velo_server_artifacts ():
    out = run_velo_query('SELECT get_server_monitoring() FROM scope()')
    if len(out) > 0 and len(out[0]) > 0:
        return out[0][0]['get_server_monitoring()']
    else:
        log.error("not able to retrieve server artifacts")
        return {}

def get_velo_client_artifacts ():
    out = run_velo_query('SELECT get_client_monitoring() FROM scope()')
    if len(out) > 0 and len(out[0]) > 0:
        return out[0][0]['get_client_monitoring()']['artifacts']
    else:
        log.error("not able to retrieve client artifacts")
        return {}

def add_velo_server_artifact (artifact, params):
    query='SELECT add_server_monitoring(artifact="'
    query += artifact + '", parameters=dict('
    if params is not None:
        if 'Artifacts' in params:
          params['Artifacts'] = 'Artifact\n' + '\n'.join(params['Artifacts']) + '\n'

        query += ', '.join(f'{key}="{value}"' for key, value in params.items())        
    query += ')) FROM scope()'

    #log.info(f"<<<<<< {query}")
    out = run_velo_query(query)
    #log.info(out)
    
    if not out or 'None' in out:
        log.error(f"error while adding {artifact}")
        return 1
    else:
        return 0

def add_velo_client_artifact (artifact, params):
    query = 'SELECT add_client_monitoring(artifact="'
    query += artifact + '", parameters=dict('
    if params is not None:
        query += ', '.join(f'{key}="{value}"' for key, value in params.items())
    query += ')) FROM scope()'

    out = run_velo_query(query)
    #log.info(out)
    
    if not out or 'None' in out:
        log.error(f"error while adding {artifact}")
        return 1
    else:
        return 0



def del_velo_server_artifact (artifact):
    query = 'SELECT rm_server_monitoring(artifact="'
    query += artifact + '") FROM scope()'

    out = run_velo_query(query)
    #log.info(out)
    
    if not out or 'None' in out:
        log.error(f"error while deleting {artifact}")
        return 1
    else:
        return 0

def del_velo_client_artifact (artifact):
    query = 'SELECT rm_client_monitoring(artifact="'
    query += artifact + '") FROM scope()'

    out = run_velo_query(query)
    #log.info(out)
    
    if not out or 'None' in out:
        log.error(f"error while deleting {artifact}")
        return 1
    else:
        return 0



def apply_artifacts (is_srv, diff, artifacts):
    ret = 1

    if is_srv:
        add_artifact='add_velo_server_artifact'
        del_artifact='del_velo_server_artifact'
    else:
        add_artifact='add_velo_client_artifact'
        del_artifact='del_velo_client_artifact'


    for art in diff['toadd']:
        if globals()[add_artifact](art, artifacts[art]):
            log.error(f"unable to add artifact {art}")
            return ret
        else:
            log.info(f"added artifact {art}")

    for art in diff['toupdate']:
        if globals()[del_artifact](art):
            log.error(f"unable to delete artifact {art}")
            return ret
        else:
            log.info(f"deleted artifact {art}")

        if globals()[add_artifact](art, artifacts[art]):
            log.error(f"unable to add artifact {art}")
            return ret
        else:
            log.info(f"added artifact {art}")
 
    for art in diff['todelete']:
        if globals()[del_artifact](art):
            log.error(f"unable to delete artifact {art}")
            return ret
        else:
            log.info(f"deleted artifact {art}")

   
    ret = 0
    return ret

def diff_artifacts_params (artifact, current_params, desired_params):
    ret = DiffStatus.ERROR

    if current_params is None:
        log.error("artifact {artifact} params not found")
        return ret
    else:
        #log.error(current_params)
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
    skip_artifacts=['Server.Monitor.Health', 'Generic.Client.Stats', 'Linux.Events.ProcessExecutions']
    
    ret = {'status': 1, 'toadd': [], 'todelete': [], 'toupdate': [], "toskip": []}

    desired_artifacts_only_name = list(desired_artifacts.keys())

    #log.info(desired_artifacts_only_name)
    for curr_art in current_artifacts['artifacts']:
        #log.info(f">>>>>>>>>>>{curr_art}")
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


def artifacts_configured(name, _apiconfig):
    global apiconfig
    ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}

    log.error("VRINIT")

    apiconfig = _apiconfig

    pillar_artifacts = __pillar__["velociraptor"]["server"]["artifacts"]
    #log.info(pillar_artifacts)

    current_srv_artifacts = get_velo_server_artifacts()
    srv_diff = diff_artifacts(current_srv_artifacts, pillar_artifacts["server"])
    apply_artifacts(True, srv_diff, pillar_artifacts["server"])
    if srv_diff["toadd"] or srv_diff["todelete"] or srv_diff["toupdate"]:
        ret['changes'].update({"server_diff": {"added": srv_diff["toadd"], "deleted": srv_diff["todelete"], "updated": srv_diff["toupdate"]}})

    current_client_artifacts = get_velo_client_artifacts()
    client_diff = diff_artifacts(current_client_artifacts, pillar_artifacts["client"])
    apply_artifacts(False, client_diff, pillar_artifacts["client"])
    
    if client_diff["toadd"] or client_diff["todelete"] or client_diff["toupdate"]:
        ret['changes'].update({"client_diff": {"added": client_diff["toadd"], "deleted": client_diff["todelete"], "updated": client_diff["toupdate"]}})
    
    ret['result'] = True

    return ret

def run_velo_query (query, timeout=0):
    #configfile="/etc/salt/api.config.yaml"
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

