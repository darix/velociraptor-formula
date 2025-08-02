import subprocess
import json
import logging

# todo: manage change in role
# todo: manage change of username

log = logging.getLogger(__name__)
def velocmd (server_config, cmd):
    _cmd = ["velociraptor", "--config", server_config]
    _cmd.extend(cmd)

    log.debug(f"**** {_cmd}")
    result = subprocess.run(_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True)
    return result

def diff_grants(server_config, username, desired_grants):
    ret = {"error": True, "diff": False}

    result = velocmd(server_config, ["acl", "show", username])
    if result.returncode != 0:
        log.error(f"error while retrieving user {username} grants")
        return ret

    try:
        current_grants = json.loads(result.stdout)

        for current_grant in current_grants.keys():
            if current_grant not in desired_grants:
                ret["error"] = False
                ret["diff"] = True
                return ret

        for desired_grant in desired_grants:
            if desired_grant not in current_grants.keys():
                ret["error"] = False
                ret["diff"] = True
                return ret
    except json.JSONDecodeError as e:
        log.error("error parsing json:", e)
        return ret


    return ret

def create_api_user (name, server_config, api_config):
    ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}
    new_user = False
    different_grants = False

    user_settings = __pillar__["velociraptor"]["server"]["user"]

    username = next(iter(user_settings))
    role = user_settings[username]['role']
    grants = user_settings[username]['grants']

    result = velocmd(server_config, ["user", "show", username])
    log.info(f"+++++{username} - {role} out {result.stdout} err {result.stderr}") 
    if result.returncode == 0:
         ret['result'] = True
         ret['comment'] = f"user {username} already created"    
         #diff grants
         diff = diff_grants(server_config, username, grants)
         if diff["error"]:
             log.error(f"error while diffing grants")
             return ret
         else:
             if diff["diff"]:
                 different_grants = True

                 # clean grants
                 result = velocmd(server_config, ["acl", "grant", username, "{}"])
                 if result.returncode != 0:
                     log.error("error while cleaning grants")
                     ret['result'] = False
                     ret['comment'] = f"error while cleaning grants"    
                     return ret
                 # update of grants is done later to avoid code redundacy
    else:
         if "User not found" in result.stderr:
            log.info(f"user {username} not yet exist, creating ...")
            result = velocmd(server_config, ["config", "api_client", "--name", username, "--role", role, api_config])

            log.info(f"+++++ out {result.stdout} err {result.stderr}")
            if result.returncode != 0:
                ret['result'] = False
                ret['comment'] = f"error while creating user {username}"
                return ret
            
            new_user = True
            ret['changes'] = {username: f"user {username} properly created with role {role}"}
            log.info(f"user {username} properly created ...")
            
    if new_user or different_grants:
        # adapt to format required by velociraptor tool
        grants = {key: True for key in grants}
        grants = json.dumps(grants)

        result = velocmd(server_config, ["acl", "grant", username, grants])
            
        log.info(f"+++++ out {result.stdout} err {result.stderr}")
        if result.returncode != 0:
            ret['result'] = False
            ret['comment'] = f"error while adding {grants} to user {username}"
            return ret

        log.info(f"grants {grants} properly added")
        ret['result'] = True
        ret['changes'].update({"grants": grants})

    return ret

#velociraptor --config /etc/velociraptor/server.config user show salt
#velociraptor -v --config server.conf config api_client --name salt --role api api.conf
#velociraptor -v --config server.conf acl grant salt {"collect_client":true,"collect_server":true}

