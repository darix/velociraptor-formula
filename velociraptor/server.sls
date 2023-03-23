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

    use_apparmor        = __pillar__["velociraptor"].get('use_apparmor', False)
    server_self_monitor = __pillar__["velociraptor"].get('server_self_monitor', False)
    use_humio    = ( "humio_gateway" in velociraptor_client_pillar and velociraptor_client_pillar["humio_gateway"] )

    parsed_config = {}
    with open(velociraptor_server_config) as yaml_file:
      parsed_config = yaml.load(yaml_file.read(), Loader=yaml.Loader)

    package_list = ['velociraptor']

    if use_humio:
      package_list.append('velociraptor-kafka-humio-gateway')

    if use_apparmor:
      package_list.append("velociraptor-apparmor-server")

      if server_self_monitor:
        if "apparmor_profile" in velociraptor_client_pillar:
          apparmor_profile = velociraptor_client_pillar["apparmor_profile"]
          if apparmor_profile == "restricted":
            package_list.append("velociraptor-apparmor-client-restricted")
          else:
            package_list.append("velociraptor-apparmor-client-unrestricted")
      if use_humio:
        package_list.append('velociraptor-apparmor-kafka-humio-gateway')

    config["velociraptor_packages"] = {
      "pkg.installed": [
        { "names": package_list },
      ]
    }

    #
    # TODO: this is a bit tricky as generating the config is done before apparmor
    #       but on the other hand we do not want write access in the apparmor profile
    #
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

    if use_apparmor:
      config["ensure_apparmor_is_running"] = {
        "service.running" = [
          { 'name':  'apparmor.service' },
          { 'enable': True },
          { 'require': [ 'velociraptor_packages' ] },
        ]
      }

      if server_self_monitor:
        config["ensure_client_apparmor_profile_is_loaded"] = {
          "cmd.run" = [
            { "name":  f"/sbin/apparmor_parser -r -T -W /etc/apparmor.d/velociraptor-client-{apparmor_profile} &> /dev/null || :" },
            { 'require': [ 'velociraptor_packages' ] },
            { 'watch': [ 'velociraptor_packages' ] },
            { 'onchanges': [ 'velociraptor_packages' ] },
          ]
        }

      config["ensure_server_apparmor_profile_is_loaded"] = {
        "cmd.run" = [
          { "name":  f"/sbin/apparmor_parser -r -T -W /etc/apparmor.d/velociraptor-server &> /dev/null || :" },
          { 'require': [ 'velociraptor_packages' ] },
          { 'watch': [ 'velociraptor_packages' ] },
          { 'onchanges': [ 'velociraptor_packages' ] },
        ]
      }

    if server_self_monitor:
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
