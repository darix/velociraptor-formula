#!py

import yaml
import logging

config_header = """#
# documentation is at https://docs.velociraptor.app/docs/deployment/references/
#
"""
log = logging.getLogger(__name__)



def recursive_merge(current_config, new_config):
  merged_config = current_config.copy()
  for top_key, top_value in new_config.items():
    if type(top_value) == dict:
      for key, value in top_value.items():
        merged_config[top_key][key] = value
    else:
      merged_config[top_key] = top_value

  return merged_config

def run():
  config = {}

  client_defaults = {
    "Client": {
      "writeback_linux": "/var/lib/velociraptor-client/velociraptor.writeback.yaml",
      "local_buffer": {
        "filename_linux": "/var/lib/velociraptor-client/Velociraptor_Buffer.bin",
      }
    }
  }

  server_defaults = {
    "Datastore": {
      "location": "/var/lib/velociraptor/data",
      "filestore_directory": "/var/lib/velociraptor/filestore",
    },
    "Logging": {
      "output_directory": "/var/lib/velociraptor/logs"
    }
  }

  velociraptor_server_config = "/etc/velociraptor/server.config"
  velociraptor_client_config = "/etc/velociraptor/client.config"

  if "velociraptor" in __pillar__ and "server" in __pillar__["velociraptor"] and "client" in __pillar__["velociraptor"]:

    velociraptor_server_pillar = __pillar__["velociraptor"]["server"]
    velociraptor_client_pillar = __pillar__["velociraptor"]["client"]

    parsed_config = {}
    with open(velociraptor_server_config) as yaml_file:
      parsed_config = yaml.load(yaml_file.read(), Loader=yaml.Loader)

    config["velociraptor_packages"] = {
      "pkg.installed": [
        { "names": [
            # 'velociraptor-kafka-humio-gateway',
            'velociraptor',
          ]
        }
      ]
    }

    # only run this once so we do not regenerate the config over and over.
    # the certificates are also on the clients
    if not(parsed_config and "Client" in parsed_config and "ca_certificate" in parsed_config["Client"]):
      config["velociraptor_generate_config"] = {
        "cmd.run": [
          { "name":    f"/usr/bin/velociraptor config generate --nobanner > {velociraptor_server_config}" },
        ]
      }

    merged_config = recursive_merge(parsed_config, client_defaults)
    merged_config = recursive_merge(merged_config, server_defaults)

    if "config" in velociraptor_client_pillar:
      merged_config = recursive_merge(merged_config, velociraptor_client_pillar["config"])

    if "config" in velociraptor_server_pillar:
      merged_config = recursive_merge(merged_config, velociraptor_server_pillar["config"])

    client_config = {}
    for key in ["version", "Client"]:
      client_config[key] = merged_config[key]

    server_content = config_header
    server_content += yaml.dump(merged_config)

    client_content = config_header
    client_content += yaml.dump(client_config)

    config["velociraptor_merge_settings"] = {
      "file.managed": [
        { "name":  velociraptor_server_config },
        { "user": "root" },
        { "group": "velociraptor" },
        { "mode":  "0640" },
        { "contents": server_content },
      ]
    }

    config["velociraptor_client_config"] = {
      "file.managed": [
        { "name":  velociraptor_client_config },
        { "user": "root" },
        { "group": "velociraptor" },
        { "mode":  "0640" },
        { "contents": client_content },
      ]
    }

    config["velociraptor_client_service"] = {
      "service.running": [
        { "name":    "velociraptor-client.service" },
        { "enable":  "True" },
        { "require": ["velociraptor_client_config"]},
        { "onchanges": ["velociraptor_client_config"]},
      ]
    }

    config["velociraptor_server_service"] = {
      "service.running": [
        { "name":    "velociraptor.service" },
        { "enable":  "True" },
        { "require": ["velociraptor_merge_settings"] },
        { "onchanges": ["velociraptor_merge_settings"] },
      ]
    }

  return config
