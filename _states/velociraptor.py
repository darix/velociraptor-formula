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

def get_velo_server_artifacts ():
    out = run_velo_query('SELECT get_server_monitoring() FROM scope()')
    if len(out) > 0 and len(out[0]) > 0:
        return out[0][0]['get_server_monitoring()']
    else:
        log.error("empty server artifacts")
        return {}

def diff_srv_artifacts_params (current_params, desired_params):
    ret = DiffStatus.ERROR

    if current_params is None:
        log.error("server artifact {curr_art} params not found")
        return ret
    else:
        log.error(current_params)
        for current_param in current_params:
            current_key = current_param['key']
            current_value = current_param['value']
            desired_value = next((value for key, value in desired_params.items() if key == current_key), None)
            
            if desired_value is None:
                log.error(f"parameter {current_key} not found for server artifact")
                return ret
            else:
                if desired_value != current_value:
                    log.info(f"{current_key} param desired {desired_value} != current {current_value}")
                    return DiffStatus.DIFFERENT
                else:
                    continue

    return DiffStatus.EQUAL

def diff_srv_artifacts (current_artifacts, desired_artifacts):
    skip_server_artifacts=['Server.Monitor.Health']
    
    #Server.Monitor.Health
    #for pillar_art in pillar_artifacts:
    ret = {'status': 1, 'toadd': [], 'todelete': [], 'toupdate': []}

    desired_artifacts_only_name = list(desired_artifacts.keys())

    log.info(desired_artifacts_only_name)
    for curr_art in current_artifacts['artifacts']:
        if curr_art in skip_server_artifacts:
            continue
        elif curr_art not in desired_artifacts:
            log.info(f"{curr_art} will be deleted")
            ret['todelete'].append(curr_art)
        else:
            # check diffs in parameters
            current_params=next((item['parameters']['env'] for item in current_artifacts['specs'] if item['artifact'] == curr_art), None)
            desired_params=desired_artifacts[curr_art]
            diff_ret = diff_srv_artifacts_params(current_params, desired_params)
            if diff_ret == DiffStatus.DIFFERENT:
                log.info(f"{curr_art} will be updated")
                ret['toupdate'].append(curr_art)
            else:
                return ret

    for desired_artifact in desired_artifacts:
        if desired_artifact not in ret['todelete'] and desired_artifact not in ret['toupdate']:
            log.info(f"{desired_artifact} will be added")
            ret['toadd'].append(desired_artifact)
    
    ret['status'] = 0

    return ret     


def artifacts_configured(name):
    ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}

    current_srv_artifacts = get_velo_server_artifacts()
    log.info(current_srv_artifacts)
    log.error("R000000cks")
    #ret['artifacts'] = artifacts
    #vc = get_veloclient()

    #artifacts = vc.get_artifacts()

    pillar_artifacts = __pillar__["velociraptor"]["server"]["artifacts"]
    log.info(pillar_artifacts)

    diff_srv_artifacts(current_srv_artifacts, pillar_artifacts["server"])
  #delta = calculate_diff(artifacts, pillar_config)

  #if delta == None:
  #  ret["result"] = True
  #  ret["comment"] = f"Artifacts configured correctly already"
  #else:
  #  if __opts__["test"]:
  #    ret["comment"] = f"The following artifacts would be modified {delta}"
  #    return ret
  #  else:
  #    if _verify_user_exists(name, ma):
  #      ret["result"] = True
  #      ret["changes"]["user"] = f"User '{name}' already created"
  #    else:
  #      ret["result"] = False
  #      ret["comment"] = f"Something went wrong when trying to create user {name}"
  #      return ret

    return ret

def run_velo_query (query, timeout=0):
    configfile="/etc/salt/api.config.yaml"
    config = pyvelociraptor.LoadConfigFile(configfile)
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

