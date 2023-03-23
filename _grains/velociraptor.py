import yaml
import logging
import os
log = logging.getLogger(__name__)

def client_settings():
    ret={}

    velociraptor_client_config = "/etc/velociraptor/client.config"
    velociraptor_server_config = "/etc/velociraptor/server.config"

    # we only export the data from the machine which is actually running the server and not other random machines
    if os.path.exists(velociraptor_client_config) and os.path.exists(velociraptor_server_config):
      with open(velociraptor_client_config) as yaml_file:
        parsed_config = yaml.load(yaml_file.read(), Loader=yaml.Loader)

        main_key = "velociraptor"
        ret[main_key] = {}
        ret[main_key]["client"] = {}
        ret[main_key]["client"]["config"] = {}
        for key in ["nonce", "ca_certificate"]:
          ret[main_key]["client"]["config"][key] = parsed_config["Client"][key]

    return ret
